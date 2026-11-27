"""Chip-level tests through the SPI host port. The reference model is the
oracle for timing; the UART decoder checks the protocol independently.

Run from test/:   make
"""
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mockingbird import asm, i2c, isa, model, spi, uart, ws2812  # noqa: E402

PROGS = Path(__file__).resolve().parents[1] / "programs"
SCK_HALF = 8   # core clocks per SCK half period; the spec minimum is 4


class SpiHost:
    """Mode-0 SPI master on ui_in[5:7], reading MISO on uo_out[7]."""

    def __init__(self, dut):
        self.dut = dut
        self.ui = 1 << isa.HOST_CS
        dut.ui_in.value = self.ui

    def pin(self, idx, v):
        """Drive one ui_in bit and keep the rest; tests use it for protocol pins too."""
        self.ui = (self.ui & ~(1 << idx)) | (v << idx)
        self.dut.ui_in.value = self.ui

    async def xfer(self, cmd, eng=0, reg=0, data=0):
        """One 24-bit frame -> (id, status, rx_head)."""
        clk, word, resp = self.dut.clk, isa.host_frame(cmd, eng, reg, data), 0
        self.pin(isa.HOST_CS, 0)
        await ClockCycles(clk, SCK_HALF)
        for i in range(23, -1, -1):
            self.pin(isa.HOST_MOSI, (word >> i) & 1)
            await ClockCycles(clk, SCK_HALF)
            resp = (resp << 1) | ((int(self.dut.uo_out.value) >> isa.HOST_MISO) & 1)
            self.pin(isa.HOST_SCK, 1)
            await ClockCycles(clk, SCK_HALF)
            self.pin(isa.HOST_SCK, 0)
        await ClockCycles(clk, SCK_HALF)
        self.pin(isa.HOST_CS, 1)
        await ClockCycles(clk, SCK_HALF)
        return resp >> 16, (resp >> 8) & 0xFF, resp & 0xFF

    async def status(self, eng=0):
        return (await self.xfer(isa.CMD_STATUS, eng))[1]

    async def cfg(self, name, v, eng=0):
        await self.xfer(isa.CMD_CFG, eng, isa.CFG[name], v)

    async def load(self, prog, eng=0, **over):
        await self.cfg("PTR", 0, eng)
        for w in prog.words:
            await self.xfer(isa.CMD_PROG, eng, 0, w)
        for name, v in {**prog.cfg, **over}.items():
            await self.cfg(name, v, eng)

    async def push(self, byte, eng=0):
        """-> accepted"""
        _, st, _ = await self.xfer(isa.CMD_PUSH, eng, 0, byte)
        return not st & isa.ST_TX_FULL

    async def pop(self, eng=0):
        """-> byte, or None when RX was empty"""
        _, st, head = await self.xfer(isa.CMD_POP, eng)
        return head if st & isa.ST_RX_VALID else None


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 20, "ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 1 << isa.HOST_CS
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    return SpiHost(dut)


async def sample(dut, idx, n, out):
    """Output pin idx for each of the next n clocks. Read at the falling edge:
    the value from the last rising edge has settled, and the caller is left
    free to drive pins straight afterwards."""
    for _ in range(n):
        await FallingEdge(dut.clk)
        out.append((int(dut.uo_out.value) >> idx) & 1)


def runs_after_idle(levels, idle):
    """Run lengths of a per-clock trace from the end of its first idle run, without
    the open-ended last run: the stretch that must match the model clock for clock."""
    r = model.runs(levels)
    i = next(i for i, (lvl, _) in enumerate(r) if lvl == idle)
    return r[i + 1:-1]


@cocotb.test()
async def id_and_idle_status(dut):
    host = await reset(dut)
    ident, st, head = await host.xfer(isa.CMD_STATUS)
    assert ident == isa.HOST_ID, f"ID {ident:#04x}"
    assert st == isa.ST_TX_EMPTY, f"status {st:#04x}"
    assert head == 0
    ident, st, _ = await host.xfer(isa.CMD_STATUS, eng=1)   # no such engine: reads 0
    assert ident == isa.HOST_ID and st == 0


@cocotb.test()
async def push_acceptance_and_flush(dut):
    host = await reset(dut)
    accepted = [await host.push(i) for i in range(5)]
    assert accepted == [True] * 4 + [False], accepted
    assert await host.status() == isa.ST_TX_FULL
    assert await host.pop() is None
    await host.cfg("CTRL", isa.CTRL_CLR)
    assert await host.status() == isa.ST_TX_EMPTY


@cocotb.test()
async def uart_tx_bytes_match_model(dut):
    """Checkpoint: bytes pushed through the host port leave TX with the exact
    bit timing of the reference model, and an independent decoder reads them."""
    div, data = 4, (0x5A, 0xA3)
    host = await reset(dut)
    prog = asm.assemble((PROGS / "uart_tx.s").read_text())
    await host.load(prog, CLKDIV=div)
    await host.cfg("CTRL", isa.CTRL_CLR)
    for b in data:
        assert await host.push(b)
    n = len(data) * 10 * 8 * div + 1200
    trace = []
    sampler = cocotb.start_soon(sample(dut, 0, n, trace))
    await host.cfg("CTRL", isa.CTRL_RUN)
    await sampler
    assert uart.decode(trace, 8 * div) == list(data)

    chip = model.Chip()
    chip.load(prog, CLKDIV=div)
    e = chip.engines[0]
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_CLR)
    for b in data:
        e.push(b)
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_RUN)
    chip.clock(n)

    rtl, ref = runs_after_idle(trace, 1), runs_after_idle(chip.pin_trace(0), 1)
    assert rtl == ref, (rtl, ref)
    assert await host.status() & isa.ST_TX_EMPTY


@cocotb.test()
async def uart_rx_frames_reach_host(dut):
    """A good frame, a frame with a forged bad stop bit and another good frame
    arrive on the RX pin. The host pops exactly the two good bytes, and the
    model fed the same waveform agrees."""
    div = 4
    cpb = 8 * div
    host = await reset(dut)
    prog = asm.assemble((PROGS / "uart_rx.s").read_text())
    rx = prog.pins["RX"]
    host.pin(rx, 1)                                 # the line idles high before the engine runs
    await host.load(prog, CLKDIV=div)
    await host.cfg("CTRL", isa.CTRL_RUN | isa.CTRL_CLR)
    wave = (uart.waveform(0x5A, cpb, idle_before=20, idle_after=40)
            + uart.waveform(0x0F, cpb, idle_after=40, stop=0)
            + uart.waveform(0x81, cpb, idle_after=200))
    for level in wave:                              # one sample per core clock
        await FallingEdge(dut.clk)
        host.pin(rx, level)
    assert await host.status() & isa.ST_RX_VALID
    got = [await host.pop() for _ in range(3)]
    assert got == [0x5A, 0x81, None], got
    assert not await host.status() & isa.ST_RX_OVF

    chip = model.Chip()
    chip.set_input(rx, 1)
    chip.clock(4)
    chip.load(prog, CLKDIV=div)
    chip.start()
    for level in wave:
        chip.set_input(rx, level)
        chip.clock()
    e = chip.engines[0]
    assert got == [e.pop() for _ in range(3)]


@cocotb.test()
async def uart_rx_overflow_is_flagged_and_stays_in_frame(dut):
    """Fourteen bytes arrive back to back while the host is not listening. The
    engine keeps the first four, drops what does not fit with RX_OVF set, and
    stays in step with the line: everything the host pops, during the stream
    and after it, is a byte that was really sent, in order."""
    div = 4
    cpb = 8 * div
    host = await reset(dut)
    prog = asm.assemble((PROGS / "uart_rx.s").read_text())
    rx = prog.pins["RX"]
    host.pin(rx, 1)
    await host.load(prog, CLKDIV=div)
    await host.cfg("CTRL", isa.CTRL_RUN | isa.CTRL_CLR)
    sent = list(range(0x41, 0x4F))                  # increasing, so "in order" is easy to check
    wave = [1] * 40 + [s for b in sent for s in uart.waveform(b, cpb)] + [1] * 40

    async def line():
        for level in wave:
            await FallingEdge(dut.clk)
            host.pin(rx, level)

    stream = cocotb.start_soon(line())
    await ClockCycles(dut.clk, 40 + 6 * 10 * cpb + 100)     # inside the seventh byte
    st = await host.status()
    assert st & isa.ST_RX_OVF and st & isa.ST_RX_FULL, f"status {st:#04x}"
    got = [await host.pop() for _ in range(4)]      # the stream is still running
    await stream
    while (b := await host.pop()) is not None:
        got.append(b)
    assert got[:4] == sent[:4], got
    assert 4 < len(got) < len(sent), got            # more arrived after the drain; some were lost
    assert set(got) <= set(sent) and got == sorted(set(got)), got   # only real bytes, in order


@cocotb.test()
async def spi_master_loopback_matches_model(dut):
    """MOSI wired back to MISO. The host gets its bytes back, an independent
    decoder reads the frame off the pins, and CS, SCK and MOSI keep the model's
    timing clock for clock."""
    data, n = (0xC3, 0x3C), 800
    host = await reset(dut)
    prog = asm.assemble((PROGS / "spi_master.s").read_text())
    pin = prog.pins
    await host.load(prog)
    await host.cfg("CTRL", isa.CTRL_CLR)
    for b in (len(data) - 1, *data):                # count - 1, then the bytes
        assert await host.push(b)
    trace = []

    async def loopback():
        for _ in range(n):
            await FallingEdge(dut.clk)
            out = int(dut.uo_out.value)
            trace.append(out)
            host.pin(pin["MISO"], (out >> pin["MOSI"]) & 1)

    wire = cocotb.start_soon(loopback())
    await host.cfg("CTRL", isa.CTRL_RUN)
    await wire
    assert [await host.pop() for _ in range(3)] == [*data, None]

    def line(name):
        return [(w >> pin[name]) & 1 for w in trace]
    assert spi.decode(line("CS"), line("SCK"), line("MOSI"), line("MOSI")) == [(list(data),) * 2]

    chip = model.Chip()
    chip.load(prog)
    e = chip.engines[0]
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_CLR)
    for b in (len(data) - 1, *data):
        e.push(b)
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_RUN)
    for _ in range(n):
        chip.set_input(pin["MISO"], (chip.pins.out >> pin["MOSI"]) & 1)
        chip.clock()
    mask, idle = sum(1 << pin[k] for k in ("CS", "SCK", "MOSI")), 1 << pin["CS"]
    rtl = runs_after_idle([w & mask for w in trace], idle)
    ref = runs_after_idle([o & mask for o, _ in chip.trace], idle)
    assert rtl == ref, (rtl, ref)


async def i2c_write(dut, frame, target, div=2, n=4000):
    """Run programs/i2c_master.s on an open-drain bus with an optional target and
    send one write frame. -> (the RTL's bus, the model's bus on an identical setup,
    whatever the host can pop afterwards)."""
    host = await reset(dut)
    prog = asm.assemble((PROGS / "i2c_master.s").read_text())
    sda, scl = prog.pins["SDA"] - 8, prog.pins["SCL"] - 8       # uio bit numbers
    dut.uio_in.value = (1 << sda) | (1 << scl)                  # pull-ups: the bus idles high
    await host.load(prog, CLKDIV=div)
    await host.cfg("CTRL", isa.CTRL_CLR)
    for b in (len(frame) - 1, *frame):
        assert await host.push(b)
    bus = i2c.Bus(target)

    async def wires():      # a line is low while the chip enables that pad with level 0
        for _ in range(n):
            await FallingEdge(dut.clk)
            low = int(dut.uio_oe.value) & ~int(dut.uio_out.value)
            s, c = bus.clock((low >> sda) & 1, (low >> scl) & 1)
            dut.uio_in.value = (s << sda) | (c << scl)

    running = cocotb.start_soon(wires())
    await host.cfg("CTRL", isa.CTRL_RUN)
    await running
    popped = await host.pop()

    chip = model.Chip()
    chip.load(prog, CLKDIV=div)
    e = chip.engines[0]
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_CLR)
    for b in (len(frame) - 1, *frame):
        e.push(b)
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_RUN)
    ref = i2c.Bus(i2c.Target(target.addr, target.stretch) if target else None)
    for _ in range(n):
        low = chip.pins.driving_low()
        s, c = ref.clock((low >> sda) & 1, (low >> scl) & 1)
        chip.set_input(sda + 8, s)
        chip.set_input(scl + 8, c)
        chip.clock()
    return bus, ref, popped


def i2c_runs(bus):
    return runs_after_idle([s | c << 1 for s, c in zip(bus.sda, bus.scl)], 3)


@cocotb.test()
async def i2c_write_acked_with_clock_stretching(dut):
    """A target ACKs the address and one data byte and holds SCL low after each
    ACK. The engine waits for it, the target receives the byte, an independent
    decoder reads the bus, and both lines keep the model's timing."""
    target = i2c.Target(0x50, stretch=60)
    bus, ref, popped = await i2c_write(dut, (0xA0, 0x5C), target)
    assert target.data == [0x5C] and popped is None             # no NACK marker
    assert i2c.decode(bus.sda, bus.scl) == [[(0xA0, True), (0x5C, True)]]
    assert max(n for lvl, n in model.runs(bus.scl) if lvl == 0) >= 60   # the engine waited
    assert i2c_runs(bus) == i2c_runs(ref)


@cocotb.test()
async def i2c_write_nack_on_empty_bus(dut):
    """Nobody answers: the address byte is not acknowledged, the engine sends a
    STOP and reports 0xFF to the host."""
    bus, ref, popped = await i2c_write(dut, (0xA0,), None, n=2400)
    assert popped == 0xFF
    assert i2c.decode(bus.sda, bus.scl) == [[(0xA0, False)]]
    assert i2c_runs(bus) == i2c_runs(ref)


def frames_of(levels, reset=2500):
    """Split a per-clock WS2812 trace at its reset gaps (2500 clocks is 50 us):
    -> one run-length list per frame, without the idle time around it."""
    frames, current = [], []
    for level, n in model.runs(levels):
        if not level and (n >= reset or not current):
            if current:
                frames.append(current)
            current = []
        else:
            current.append((level, n))
    return frames


@cocotb.test()
async def ws2812_frames_match_model(dut):
    """programs/ws2812.s on the chip. Two frames pushed through the host port
    leave the pin inside the WS2812B datasheet windows, an independent decoder
    reads them back, and every pulse and gap has the model's length to the
    clock. The host here needs 408 clocks per byte; the program takes 486."""
    frames = [[0x10, 0x80, 0x01, 0xFF, 0x00, 0xA5], [0x55, 0xAA, 0x0F]]
    host = await reset(dut)
    prog = asm.assemble((PROGS / "ws2812.s").read_text())
    din = prog.pins["DIN"]
    await host.load(prog)
    await host.cfg("CTRL", isa.CTRL_CLR)
    trace = []
    sampler = cocotb.start_soon(sample(dut, din, 13000, trace))
    await host.cfg("CTRL", isa.CTRL_RUN)
    for data in frames:
        for byte in data:
            assert await host.push(byte)
        await ClockCycles(dut.clk, 4000)             # the rest of the frame, then a reset gap over 50 us
    await sampler
    assert ws2812.decode(trace, 50_000_000) == frames
    idle = isa.ST_RUNNING | isa.ST_STALLED | isa.ST_TX_EMPTY
    assert await host.status() == idle               # frame out: the engine waits in PULL

    chip = model.Chip()
    chip.load(prog)
    chip.start()
    paced = model.Host(chip)
    for data in frames:
        paced.send(*data)
        for _ in range(8000):
            paced.clock()
            chip.clock()
    on_chip, in_model = frames_of(trace), frames_of(chip.pin_trace(din))
    assert len(on_chip) == len(frames) and on_chip == in_model
