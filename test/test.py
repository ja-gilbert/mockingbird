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
from mockingbird import asm, isa, model, uart  # noqa: E402

PROGS = Path(__file__).resolve().parents[1] / "programs"
SCK_HALF = 8   # core clocks per SCK half period; the spec minimum is 4


class SpiHost:
    """Mode-0 SPI master on ui_in[5:7], reading MISO on uo_out[7]."""

    def __init__(self, dut):
        self.dut = dut
        self.ui = 1 << isa.HOST_CS
        dut.ui_in.value = self.ui

    def _pin(self, idx, v):
        self.ui = (self.ui & ~(1 << idx)) | (v << idx)
        self.dut.ui_in.value = self.ui

    async def xfer(self, cmd, eng=0, reg=0, data=0):
        """One 24-bit frame -> (id, status, rx_head)."""
        clk, word, resp = self.dut.clk, isa.host_frame(cmd, eng, reg, data), 0
        self._pin(isa.HOST_CS, 0)
        await ClockCycles(clk, SCK_HALF)
        for i in range(23, -1, -1):
            self._pin(isa.HOST_MOSI, (word >> i) & 1)
            await ClockCycles(clk, SCK_HALF)
            resp = (resp << 1) | ((int(self.dut.uo_out.value) >> isa.HOST_MISO) & 1)
            self._pin(isa.HOST_SCK, 1)
            await ClockCycles(clk, SCK_HALF)
            self._pin(isa.HOST_SCK, 0)
        await ClockCycles(clk, SCK_HALF)
        self._pin(isa.HOST_CS, 1)
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

    def from_start_bit(r):                # first 1->0 edge; the trailing idle is open-ended
        i = next(i for i in range(1, len(r)) if r[i][0] == 0 and r[i - 1][0] == 1)
        return r[i:-1]
    rtl, ref = model.runs(trace), model.runs(chip.pin_trace(0))
    assert from_start_bit(rtl) == from_start_bit(ref), (from_start_bit(rtl), from_start_bit(ref))
    assert await host.status() & isa.ST_TX_EMPTY
