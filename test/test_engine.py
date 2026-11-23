"""Engine unit tests: drive src/engine.v directly with the reference model as
the oracle, comparing pc, stall, pins and FIFO traffic after every clock.

Run from test/:   make UNIT=engine
"""
import sys
from collections import deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mockingbird import asm, isa, model  # noqa: E402


def val(sig):
    v = sig.value
    assert v.is_resolvable, f"{sig._name} is {v} (X/Z)"
    return int(v)


class Harness:
    """Plays the top level around the engine: program memory, FIFOs, divider
    and pin file. Steps a model Engine alongside and compares every clock."""

    def __init__(self, dut, words, tx=(), rx=(), cfg=None, inputs=None, tick_every=1):
        self.dut = dut
        self.mem = (list(words) + [0] * isa.DEPTH)[:isa.DEPTH]
        self.tx, self.rx = deque(tx), deque(rx)
        self.pins = model.Pins()
        self.inputs = inputs or (lambda cycle: 0)
        self.tick_every = tick_every
        self.divcnt = 0
        self.trace = []
        self.drops = 0
        self.cycle = 0
        self.mpins = model.Pins()
        self.m = model.Engine(self.mpins)
        self.m.mem = list(self.mem)
        for name, v in (cfg or {}).items():
            self.m.host_cfg(isa.CFG[name], v)
        self.m.clr()                      # picks up START
        self.m.clkdiv = tick_every
        self.m.run = True
        self.m.tx.extend(tx)
        self.m.rx.extend(rx)

    async def reset(self):
        d = self.dut
        d.tick.value = 0
        d.clr.value = 0
        d.start_pc.value = self.m.start
        d.out_right.value = int(self.m.out_right)
        d.in_right.value = int(self.m.in_right)
        d.jmppin.value = self.m.jmppin
        d.instr.value = 0
        d.in_pins.value = 0
        d.tx_empty.value = 1
        d.tx_rdata.value = 0
        d.rx_full.value = 0
        d.rst_n.value = 0
        await RisingEdge(d.clk)
        await RisingEdge(d.clk)
        d.rst_n.value = 1
        await RisingEdge(d.clk)
        if self.m.start:                  # reset leaves pc = 0; clr loads start_pc
            await self.step(clr=True)

    async def step(self, clr=False):
        d, m = self.dut, self.m
        await FallingEdge(d.clk)
        inp = self.inputs(self.cycle)
        tick = self.divcnt == self.tick_every - 1
        d.tick.value = int(tick)
        d.clr.value = int(clr)
        d.instr.value = self.mem[val(d.pc)]
        d.in_pins.value = inp
        d.tx_empty.value = int(not self.tx)
        d.tx_rdata.value = self.tx[0] if self.tx else 0
        d.rx_full.value = int(len(self.rx) >= isa.FIFO_DEPTH)
        await Timer(1, "ns")
        strobes = (val(d.out_we), val(d.oe_we), val(d.tx_pop), val(d.rx_push), val(d.rx_drop))
        if not tick or clr or m.delay:
            assert strobes == (0, 0, 0, 0, 0), \
                f"cycle {self.cycle}: strobes {strobes} while not executing"
        out_we, oe_we, tx_pop, rx_push, rx_drop = strobes
        out_wdata, oe_wdata = val(d.out_wdata), val(d.oe_wdata)
        for bit in range(16):
            if (out_we >> bit) & 1:
                self.pins.write(0, bit, (out_wdata >> bit) & 1)
            if (oe_we >> bit) & 1:
                self.pins.write(1, bit, (oe_wdata >> bit) & 1)
        if tx_pop:
            assert self.tx, f"cycle {self.cycle}: tx_pop on an empty FIFO"
            self.tx.popleft()
        if rx_push:
            assert len(self.rx) < isa.FIFO_DEPTH, f"cycle {self.cycle}: rx_push into a full FIFO"
            self.rx.append(val(d.rx_wdata))
        self.drops += rx_drop
        await RisingEdge(d.clk)
        await Timer(1, "ns")              # let this edge's register updates land before comparing
        if clr:
            m.clr()
            self.tx.clear()
            self.rx.clear()
        else:
            m.clock(inp)
        self.divcnt = 0 if (clr or tick) else self.divcnt + 1
        self.cycle += 1
        self.trace.append(self.pins.out)
        self.compare()

    def compare(self):
        d, m, c = self.dut, self.m, self.cycle
        assert val(d.pc) == m.pc, f"cycle {c}: pc {val(d.pc)} != model {m.pc}"
        assert val(d.stalled) == int(m.stalled), \
            f"cycle {c}: stalled {val(d.stalled)} != model {int(m.stalled)}"
        assert (self.pins.out, self.pins.oe) == (self.mpins.out, self.mpins.oe), \
            f"cycle {c}: pins {self.pins.out:#06x}/{self.pins.oe:#04x} != model " \
            f"{self.mpins.out:#06x}/{self.mpins.oe:#04x}"
        assert list(self.tx) == list(m.tx), f"cycle {c}: tx {list(self.tx)} != model {list(m.tx)}"
        assert list(self.rx) == list(m.rx), f"cycle {c}: rx {list(self.rx)} != model {list(m.rx)}"
        assert bool(self.drops) == m.rx_ovf, f"cycle {c}: drops {self.drops}, model ovf {m.rx_ovf}"


async def run(dut, src, cycles, **kw):
    words = asm.assemble(src).words if isinstance(src, str) else src
    h = Harness(dut, words, **kw)
    cocotb.start_soon(Clock(dut.clk, 20, "ns").start())
    await h.reset()
    for _ in range(cycles):
        await h.step()
    return h


def bit(word, n):
    return (word >> n) & 1


def rising_edges(bits):
    return sum(1 for a, b in zip(bits, bits[1:]) if a == 0 and b == 1)


LOOP = """
    SET X, 3
l:  SETP PIN 0, 1
    SETP PIN 0, 0 [2]
    JMP X--, l
    SETP PIN 1, 1
done: JMP done
"""


@cocotb.test()
async def loop_count_and_delay(dut):
    h = await run(dut, LOOP, 30)
    assert rising_edges([bit(o, 0) for o in h.trace]) == 4        # X = 3 runs 4 times
    assert bit(h.trace[20], 1) == 0 and bit(h.trace[21], 1) == 1  # exact cycle of pin 1


@cocotb.test()
async def sparse_ticks(dut):
    h = await run(dut, LOOP, 90, tick_every=3)
    assert rising_edges([bit(o, 0) for o in h.trace]) == 4
    assert bit(h.trace[64], 1) == 0 and bit(h.trace[65], 1) == 1  # step 21 -> cycle 3*21+2


OUT_BITS = """
    PULL
    SET X, 7
l:  OUT PIN 8, 1
    JMP X--, l
done: JMP done
"""


@cocotb.test()
async def out_lsb_first(dut):
    h = await run(dut, OUT_BITS, 22, tx=[0xA5], cfg={"SHIFT": isa.SHIFT_OUT_RIGHT})
    assert [bit(h.trace[2 + 2 * k], 8) for k in range(8)] == [bit(0xA5, k) for k in range(8)]
    assert not h.tx


@cocotb.test()
async def out_msb_first(dut):
    h = await run(dut, OUT_BITS, 22, tx=[0xA5], cfg={"SHIFT": 0})
    assert [bit(h.trace[2 + 2 * k], 8) for k in range(8)] == [bit(0xA5, 7 - k) for k in range(8)]


IN_BITS = """
    SET X, 7
l:  IN PIN 3, 1
    JMP X--, l
    PUSH
done: JMP done
"""
PATTERN = [1, 0, 1, 1, 0, 0, 1, 0]


def pattern_inputs(cycle):               # IN executes at cycles 1, 3, ..., 15
    return PATTERN[min(max((cycle - 1) // 2, 0), 7)] << 3


@cocotb.test()
async def in_lsb_first(dut):
    h = await run(dut, IN_BITS, 22, inputs=pattern_inputs, cfg={"SHIFT": isa.SHIFT_IN_RIGHT})
    assert list(h.rx) == [sum(b << k for k, b in enumerate(PATTERN))]


@cocotb.test()
async def in_msb_first(dut):
    h = await run(dut, IN_BITS, 22, inputs=pattern_inputs, cfg={"SHIFT": 0})
    assert list(h.rx) == [sum(b << (7 - k) for k, b in enumerate(PATTERN))]


@cocotb.test()
async def wait_stalls_then_delays(dut):
    src = "WAIT PIN 4, 1 [3]\nSETP PIN 0, 1\ndone: JMP done"
    h = await run(dut, src, 20, inputs=lambda c: (1 << 4) if c >= 10 else 0)
    assert bit(h.trace[13], 0) == 0 and bit(h.trace[14], 0) == 1  # seen at 10, +3 delay, SETP at 14


@cocotb.test()
async def pull_blocking_stalls(dut):
    h = await run(dut, "PULL\nSETP PIN 0, 1\ndone: JMP done", 10)
    assert val(dut.stalled) == 1 and val(dut.pc) == 0 and h.pins.out == 0


@cocotb.test()
async def pull_noblock_takes_x(dut):
    h = await run(dut, "SET X, 90\nPULL NOBLOCK\nOUT PIN 8, 8\ndone: JMP done", 8)
    assert h.pins.out >> 8 == 90


@cocotb.test()
async def push_drop_then_block(dut):
    src = """
    SET X, 1
    MOV ISR, X
    PUSH NOBLOCK
    SETP PIN 0, 1
    PUSH
    SETP PIN 1, 1
done: JMP done
"""
    full = [1, 2, 3, 4]
    h = await run(dut, src, 12, rx=full)
    assert h.drops == 1 and h.pins.out == 1 and val(dut.stalled) == 1
    h.rx.popleft()                        # host pops one byte on both sides
    h.m.rx.popleft()
    for _ in range(4):
        await h.step()
    assert list(h.rx) == [2, 3, 4, 0] and h.pins.out == 3   # dropped push still cleared ISR


@cocotb.test()
async def mov_ops(dut):
    src = """
    SET X, 0x33
    MOV Y, ~X
    MOV OSR, ::Y
    OUT PIN 8, 8
    MOV ISR, X
    PUSH
    MOV X, NULL
    MOV ISR, ~NULL
    PUSH
done: JMP done
"""
    h = await run(dut, src, 14)
    assert h.pins.out >> 8 == 0x33 and list(h.rx) == [0x33, 0xFF]


@cocotb.test()
async def jump_conditions(dut):
    src = """
    SET X, 2
    SET Y, 2
    JMP X!=Y, a
    SETP PIN 0, 1
a:  JMP !X, b
    SETP PIN 1, 1
b:  SET X, 0
    JMP !X, c
    SETP PIN 2, 1
c:  JMP !PIN, d
    SETP PIN 3, 1
d:  JMP PIN, e
    SETP PIN 4, 1
e:  SET Y, 2
f:  SETP PIN 6, 1
    SETP PIN 6, 0
    JMP Y--, f
    JMP !Y, g
    SETP PIN 5, 1
g:  JMP g
"""
    h = await run(dut, src, 40, inputs=lambda c: 1 << 4, cfg={"JMPPIN": 4})
    assert h.pins.out == 0b0000_1011, f"{h.pins.out:#06x}"
    assert rising_edges([bit(o, 6) for o in h.trace]) == 3


@cocotb.test()
async def setp_and_out_direction(dut):
    src = """
    SETP DIR 9, 1
    SETP DIR 9, 0 [1]
    SETP DIR 15, 1
    SET X, 3
    MOV OSR, X
    OUT DIR 8, 2
done: JMP done
"""
    # LSB first, so OUT sends OSR[1:0] = 0b11 to directions 8 and 9
    h = await run(dut, src, 12, cfg={"SHIFT": isa.SHIFT_OUT_RIGHT})
    assert h.pins.oe == 0b1000_0011 and h.pins.out == 0


@cocotb.test()
async def clr_restarts_at_start_pc(dut):
    h = Harness(dut, asm.assemble(LOOP).words)
    cocotb.start_soon(Clock(dut.clk, 20, "ns").start())
    await h.reset()
    for _ in range(7):
        await h.step()
    dut.start_pc.value = 4
    h.m.start = 4
    await h.step(clr=True)
    assert val(dut.pc) == 4
    await h.step()                        # SETP PIN 1 runs right after the restart
    assert bit(h.pins.out, 1) == 1


@cocotb.test()
async def reserved_encodings_are_nops(dut):
    src = """
    .word 0x9200        ; opcode 9, delay 2
    .word 0x61A0        ; MOV PC, X: reserved destination, delay 1
    .word 0x6018        ; MOV op 3: reserved operation
    SETP PIN 0, 1
done: JMP done
"""
    h = await run(dut, src, 10)
    assert bit(h.trace[5], 0) == 0 and bit(h.trace[6], 0) == 1
