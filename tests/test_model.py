from pathlib import Path

from mockingbird import asm, isa, model, uart

PROGS = Path(__file__).resolve().parents[1] / "programs"


def chip_with(name, **cfg):
    chip = model.Chip()
    chip.load(asm.assemble((PROGS / f"{name}.s").read_text()), **cfg)
    return chip


def test_uart_tx_bytes_and_bit_timing():
    div = 4
    chip = chip_with("uart_tx", CLKDIV=div)
    e = chip.engines[0]
    chip.start()
    assert e.push(0x55) and e.push(0xA3)
    chip.clock(2 * 10 * 8 * div + 100)
    tx = chip.pin_trace(0)
    assert uart.decode(tx, 8 * div) == [0x55, 0xA3]
    # runs: reset low, idle high, then every run up to the final idle is a
    # whole number of bit times: exact 8-tick bits, exact 8-tick stop bit
    r = model.runs(tx)
    assert all(length % (8 * div) == 0 for _, length in r[2:-1]), r
    assert e.status() & isa.ST_TX_EMPTY and e.status() & isa.ST_STALLED


def test_host_fifo_acceptance():
    e = model.Chip().engines[0]
    assert [e.push(i) for i in range(5)] == [True] * 4 + [False]
    assert e.status() & isa.ST_TX_FULL
    assert e.pop() is None


def test_clarifications_2026_11_21():
    # PROG is ignored while running; the divider restarts from zero after a stop
    chip = model.Chip()
    e = chip.engines[0]
    chip.load(asm.assemble("SETP PIN 0, 1\ndone: JMP done"), CLKDIV=4)
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_RUN)
    e.host_prog(0x1234)
    assert e.mem[0] != 0x1234 and e.ptr == 2
    chip.clock(2)                                   # stopped mid-count
    e.host_cfg(isa.CFG["CTRL"], 0)
    chip.clock(1)
    e.host_cfg(isa.CFG["CTRL"], isa.CTRL_RUN)
    chip.clock(3)
    assert chip.pins.out == 0                       # first tick is 4 clocks after RUN
    chip.clock(1)
    assert chip.pins.out == 1
    # reserved MOV combinations are NOPs; dst NULL discards
    m = model.Chip().engines[0]
    m.mem[:4] = [isa.encode(isa.SET, 0, 5),                       # X = 5
                 isa.encode(isa.MOV, 0, (0 << 5) | (3 << 3) | 0),  # op 3: NOP
                 isa.encode(isa.MOV, 0, (1 << 5) | (0 << 3) | 6),  # src 6: NOP
                 isa.encode(isa.MOV, 0, (4 << 5) | (1 << 3) | 0)]  # NULL <= ~X
    m.run = True
    for _ in range(4):
        m.clock(0)
    assert (m.x, m.y, m.pc) == (5, 0, 4)


def test_uart_rx_good_and_bad_frames():
    div = 4
    chip = chip_with("uart_rx", CLKDIV=div)
    chip.start()
    wave = (uart.waveform(0x5A, 8 * div, idle_before=20, idle_after=40)
            + uart.waveform(0x0F, 8 * div, idle_after=40, stop=0)
            + uart.waveform(0x81, 8 * div, idle_after=200))
    for s in wave:
        chip.set_input(1, s)
        chip.clock()
    e = chip.engines[0]
    assert [e.pop(), e.pop(), e.pop()] == [0x5A, 0x81, None]


def test_spi_loopback_msb_first():
    chip = chip_with("spi_master")
    e = chip.engines[0]
    chip.start()
    for b in (1, 0xC3, 0x3C):
        assert e.push(b)
    for _ in range(400):
        chip.set_input(0, (chip.pins.out >> 4) & 1)   # MISO <- MOSI
        chip.clock()
    assert [e.pop(), e.pop(), e.pop()] == [0xC3, 0x3C, None]
    cs = model.runs(chip.pin_trace(2))
    assert [lvl for lvl, _ in cs] == [1, 0, 1]         # idle, one frame, idle


def test_i2c_write_gets_nack_on_empty_bus():
    chip = chip_with("i2c_master", CLKDIV=2)
    e = chip.engines[0]
    chip.start()
    assert e.push(0) and e.push(0xA0)                   # one byte: address 0x50 write
    for _ in range(2000):
        for idx in (8, 9):                              # pull-ups: released -> high
            chip.set_input(idx, 0 if (chip.pins.oe >> (idx - 8)) & 1 else 1)
        chip.clock()
    assert e.pop() == 0xFF                              # NACK marker
    scl_released = model.runs(chip.oe_trace(9))
    rises = sum(1 for lvl, _ in scl_released if lvl == 0) - 1   # minus the initial released state
    assert rises == 10, scl_released                    # 8 data + ACK + STOP
