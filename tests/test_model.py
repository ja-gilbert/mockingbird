from pathlib import Path

from mockingbird import asm, i2c, isa, model, spi, uart

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


def test_uart_rx_overflow_is_flagged_and_stays_in_frame():
    # Twelve bytes back to back with the host not listening. The FIFO keeps four and
    # the rest are dropped with RX_OVF set. The host then drains in the middle of a
    # frame: that frame and the ones after it must still be received correctly.
    div = 4
    cpb = 8 * div
    chip = chip_with("uart_rx", CLKDIV=div)
    chip.start()
    e = chip.engines[0]
    sent = list(range(0x41, 0x4D))
    wave = [1] * 40 + [s for b in sent for s in uart.waveform(b, cpb)] + [1] * 400
    drain_at = 40 + 6 * 10 * cpb + 100              # inside the seventh byte
    got = []
    for t, level in enumerate(wave):
        if t == drain_at:
            assert e.status() & isa.ST_RX_OVF       # the host can see that it lost bytes
            got += [e.pop() for _ in range(4)]
        chip.set_input(1, level)
        chip.clock()
    got += [e.pop() for _ in range(5)]
    assert got == [0x41, 0x42, 0x43, 0x44, 0x47, 0x48, 0x49, 0x4A, None], got


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
    cs, sck, mosi = (chip.pin_trace(i) for i in (2, 3, 4))
    assert [lvl for lvl, _ in model.runs(cs)] == [1, 0, 1]        # idle, one frame, idle
    assert spi.decode(cs, sck, mosi, mosi) == [([0xC3, 0x3C], [0xC3, 0x3C])]


def i2c_run(chip, bus, clocks, sda=8, scl=9):
    """Clock the model on an open-drain bus: a line is low while its direction
    bit is on and its level bit is 0."""
    for _ in range(clocks):
        low = chip.pins.driving_low()
        s, c = bus.clock((low >> (sda - 8)) & 1, (low >> (scl - 8)) & 1)
        chip.set_input(sda, s)
        chip.set_input(scl, c)
        chip.clock()


def test_i2c_write_gets_nack_on_empty_bus():
    chip = chip_with("i2c_master", CLKDIV=2)
    e = chip.engines[0]
    chip.start()
    assert e.push(0) and e.push(0xA0)                   # one byte: address 0x50 write
    bus = i2c.Bus()
    i2c_run(chip, bus, 2000)
    assert e.pop() == 0xFF                              # NACK marker
    assert i2c.decode(bus.sda, bus.scl) == [[(0xA0, False)]]


def test_i2c_write_acked_with_clock_stretching():
    for stretch in (0, 60):
        chip = chip_with("i2c_master", CLKDIV=2)
        e = chip.engines[0]
        chip.start()
        for b in (1, 0xA0, 0x5C):                       # count - 1, address 0x50 write, data
            assert e.push(b)
        target = i2c.Target(0x50, stretch)
        bus = i2c.Bus(target)
        i2c_run(chip, bus, 3000)
        assert target.data == [0x5C] and e.pop() is None            # no NACK marker
        assert i2c.decode(bus.sda, bus.scl) == [[(0xA0, True), (0x5C, True)]]
        longest_low = max(n for lvl, n in model.runs(bus.scl) if lvl == 0)
        assert (longest_low >= 60) == bool(stretch), longest_low    # the controller waited
