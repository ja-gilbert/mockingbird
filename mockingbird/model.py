"""Clock-accurate reference model of the engine(s), the pin registers and the
input synchronizer. One call to Chip.clock() is one core clock edge, so pin
traces compare directly against the RTL. The SPI host port's pins are not
modelled: the host API here is the effect each host command has, and the Host
class adds the port's timing, so a test cannot move bytes faster than the
real port does. Spec: docs/isa-v0.md."""
from collections import deque

from . import isa

M8 = 0xFF


class Pins:
    """Shared output/direction registers and the two-flop input synchronizer."""

    def __init__(self):
        self.out = 0   # 16 bits: 0..7 uo_out, 8..15 uio_out
        self.oe = 0    # 8 bits: uio_oe
        self.inp = 0   # 16 bits, driven by the testbench
        self.s1 = self.s2 = 0

    def set_input(self, idx, val):
        self.inp = (self.inp & ~(1 << idx)) | ((val & 1) << idx)

    def write(self, to_dir, idx, val):
        if idx >= isa.NPINS:
            return
        if to_dir:
            if idx >= 8:
                b = idx - 8
                self.oe = (self.oe & ~(1 << b)) | ((val & 1) << b)
        elif idx != isa.HOST_MISO:
            self.out = (self.out & ~(1 << idx)) | ((val & 1) << idx)

    def driving_low(self):
        """uio pads enabled with level 0, as an 8-bit mask: what an open-drain bus sees."""
        return self.oe & ~(self.out >> 8) & 0xFF

    def sync(self):
        self.s2, self.s1 = self.s1, self.inp


class Engine:
    def __init__(self, pins):
        self.pins = pins
        self.mem = [0] * isa.DEPTH
        self.clkdiv = 0
        self.run = False
        self.start = 0
        self.out_right = self.in_right = False
        self.jmppin = 0
        self.ptr = 0
        self.tx, self.rx = deque(), deque()
        self.clr()

    # ---- host side (effects of host commands)
    def clr(self):
        self.pc = self.start
        self.x = self.y = self.isr = self.osr = 0
        self.delay = 0
        self.cnt = 0
        self.tx.clear()
        self.rx.clear()
        self.rx_ovf = False
        self.stalled = False

    def host_prog(self, word):
        if self.run:                      # loading needs RUN = 0; ignored otherwise
            return
        self.mem[self.ptr] = word & 0xFFFF
        self.ptr = (self.ptr + 1) % isa.DEPTH

    def host_cfg(self, reg, val):
        val &= 0xFFFF
        if reg == isa.CFG["CLKDIV"]:
            self.clkdiv = val
        elif reg == isa.CFG["CTRL"]:
            self.run = bool(val & isa.CTRL_RUN)
            if val & isa.CTRL_CLR:
                self.clr()
        elif reg == isa.CFG["START"]:
            self.start = val & 31
        elif reg == isa.CFG["SHIFT"]:
            self.out_right = bool(val & isa.SHIFT_OUT_RIGHT)
            self.in_right = bool(val & isa.SHIFT_IN_RIGHT)
        elif reg == isa.CFG["JMPPIN"]:
            self.jmppin = val & 15
        elif reg == isa.CFG["PTR"]:
            self.ptr = val & 31

    def push(self, byte):
        """Host PUSH. Returns the acceptance the status byte would have reported."""
        if len(self.tx) >= isa.FIFO_DEPTH:
            return False
        self.tx.append(byte & M8)
        return True

    def pop(self):
        """Host POP. None when RX is empty (the pop is then ignored)."""
        return self.rx.popleft() if self.rx else None

    def status(self):
        return ((bool(self.rx) and isa.ST_RX_VALID)
                | ((len(self.tx) >= isa.FIFO_DEPTH) and isa.ST_TX_FULL)
                | (self.run and isa.ST_RUNNING)
                | (self.stalled and isa.ST_STALLED)
                | ((not self.tx) and isa.ST_TX_EMPTY)
                | ((len(self.rx) >= isa.FIFO_DEPTH) and isa.ST_RX_FULL)
                | (self.rx_ovf and isa.ST_RX_OVF))

    # ---- engine side
    def clock(self, inp):
        """One core clock edge; inp is the synchronized input vector."""
        if not self.run:
            self.cnt = 0                  # divider held at zero while stopped
            return
        tick = self.cnt == max(self.clkdiv, 1) - 1
        self.cnt = 0 if tick else self.cnt + 1
        if not tick:
            return
        if self.delay:
            self.delay -= 1
            return
        word = self.mem[self.pc]
        done = self._exec(word, inp)
        self.stalled = not done
        if done:
            self.delay = (word >> 8) & 0xF

    def _exec(self, word, inp):
        """Apply one instruction. False = stalled, nothing changed."""
        op, _, arg = isa.decode(word)
        nxt = (self.pc + 1) % isa.DEPTH
        if op == isa.JMP:
            cond, target = arg >> 5, arg & 31
            pin = (inp >> self.jmppin) & 1
            if cond == 2:
                take = self.x != 0
                if take:
                    self.x -= 1
            elif cond == 4:
                take = self.y != 0
                if take:
                    self.y -= 1
            else:
                take = {0: True, 1: self.x == 0, 3: self.y == 0, 5: self.x != self.y,
                        6: pin == 1, 7: pin == 0}[cond]
            if take:
                nxt = (self.pc & ~31) | target
        elif op == isa.WAIT:
            if (inp >> (arg & 15)) & 1 != arg >> 7:
                return False
        elif op == isa.IN:
            n, idx = isa.cnt_value(arg & 7), (arg >> 3) & 15
            data = 0 if arg & 0x80 else (inp >> idx) & ((1 << n) - 1)
            if self.in_right:
                self.isr = ((self.isr >> n) | (data << (8 - n))) & M8
            else:
                self.isr = ((self.isr << n) | data) & M8
        elif op == isa.OUT:
            n, idx, to_dir = isa.cnt_value(arg & 7), (arg >> 3) & 15, arg >> 7
            mask = (1 << n) - 1
            if self.out_right:
                data, self.osr = self.osr & mask, self.osr >> n
            else:
                data, self.osr = (self.osr >> (8 - n)) & mask, (self.osr << n) & M8
            for k in range(n):
                self.pins.write(to_dir, idx + k, data >> k)
        elif op == isa.PUSH:
            if len(self.rx) >= isa.FIFO_DEPTH:
                if arg & 0x80:
                    return False
                self.rx_ovf = True
            else:
                self.rx.append(self.isr)
            self.isr = 0
        elif op == isa.PULL:
            if not self.tx:
                if arg & 0x80:
                    return False
                self.osr = self.x
            else:
                self.osr = self.tx.popleft()
        elif op == isa.MOV:
            dst, mop, src = arg >> 5, (arg >> 3) & 3, arg & 7
            if dst <= 3 and src <= 4 and mop <= 2:   # anything else is a NOP
                val = (self.x, self.y, self.isr, self.osr, 0)[src]
                if mop == 1:
                    val = ~val & M8
                elif mop == 2:
                    val = int(f"{val:08b}"[::-1], 2)
                if dst == 0:
                    self.x = val
                elif dst == 1:
                    self.y = val
                elif dst == 2:
                    self.isr = val
                else:
                    self.osr = val
        elif op == isa.SET:
            if arg & 0x80:
                self.y = arg & 0x7F
            else:
                self.x = arg & 0x7F
        elif op == isa.SETP:
            self.pins.write(arg >> 7, arg & 15, (arg >> 6) & 1)
        # reserved opcodes execute as NOP
        self.pc = nxt
        return True


class Chip:
    def __init__(self, nengines=1):
        self.pins = Pins()
        self.engines = [Engine(self.pins) for _ in range(nengines)]
        self.trace = []  # (out, oe) after every clock

    def set_input(self, idx, val):
        self.pins.set_input(idx, val)

    def clock(self, n=1):
        for _ in range(n):
            inp = self.pins.s2
            for e in self.engines:      # ascending order: higher engine wins a pin
                e.clock(inp)
            self.pins.sync()
            self.trace.append((self.pins.out, self.pins.oe))

    def load(self, prog, eng=0, **cfg):
        """Load an assembled Program and its .cfg values; cfg kwargs override."""
        e = self.engines[eng]
        e.host_cfg(isa.CFG["PTR"], 0)
        for w in prog.words:
            e.host_prog(w)
        for name, val in {**prog.cfg, **cfg}.items():
            e.host_cfg(isa.CFG[name], val)

    def start(self, eng=0):
        self.engines[eng].host_cfg(isa.CFG["CTRL"], isa.CTRL_RUN | isa.CTRL_CLR)

    def pin_trace(self, idx):
        """Output level of pin idx after every clock."""
        return [(o >> idx) & 1 for o, _ in self.trace]

    def oe_trace(self, idx):
        return [(oe >> (idx - 8)) & 1 for _, oe in self.trace]


class Host:
    """The SPI host port as the FIFOs experience it, without its pins. One 24-bit
    frame moves one byte in one direction, and frames follow each other no faster
    than the pin timing in docs/isa-v0.md allows: 4 clocks of CS setup, 23 SCK
    periods of 8 clocks, 4 clocks of CS hold, 4 clocks of CS high. A PUSH or POP
    is accepted or refused from the FIFO state at the status latch after bit 8
    and takes effect after bit 24, as in src/host_port.v.

    Call clock() once per Chip.clock(), before it. Bytes given to send() are
    pushed in order, each retried until accepted. With pop=True the frames not
    needed for a push pop the RX FIFO into .rx; when both are wanted the frames
    alternate, which is what full-duplex traffic costs on the real port."""

    FRAME = 4 + 23 * 8 + 4 + 4      # 196 clocks from one CS falling edge to the next
    LATCH = 4 + 7 * 8 + 3           # 63: 8th SCK rise, then synchronizer and edge detect
    APPLY = 4 + 23 * 8 + 4          # 192: 24th SCK rise, the same delay, then the FIFO edge

    def __init__(self, chip, eng=0, pop=False):
        self.e = chip.engines[eng]
        self.tx = deque()           # bytes still to push
        self.pop = pop
        self.rx = []                # bytes popped so far
        self.refused = 0            # PUSH frames that found the TX FIFO full
        self._t, self._op, self._ok, self._last = 0, None, False, "pop"

    def send(self, *data):
        self.tx.extend(data)

    def clock(self):
        if self._t == 0:            # CS falls: choose this frame's command
            if self.tx and self.pop:
                self._op = "pop" if self._last == "push" else "push"
            else:
                self._op = "push" if self.tx else "pop" if self.pop else None
            if self._op is None:
                return              # nothing to do: the next frame can start at any clock
        if self._t == self.LATCH:
            self._ok = len(self.e.tx) < isa.FIFO_DEPTH if self._op == "push" else bool(self.e.rx)
        if self._t == self.APPLY:
            if self._op == "pop":
                if self._ok:
                    self.rx.append(self.e.pop())
            elif self._ok:
                self.e.push(self.tx.popleft())
            else:
                self.refused += 1
            self._last = self._op
        self._t = (self._t + 1) % self.FRAME


def runs(bits):
    """Run-length encode: [(level, length), ...]."""
    out = []
    for b in bits:
        if out and out[-1][0] == b:
            out[-1][1] += 1
        else:
            out.append([b, 1])
    return [tuple(r) for r in out]
