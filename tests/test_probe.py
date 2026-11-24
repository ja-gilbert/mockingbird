"""Flexibility probe: programs for the protocols on the competition page, run in
the model with the host limited to the real port's byte rate (model.Host moves
one byte per 196 clocks). The results are written up in
docs/flexibility-probe.md."""
from pathlib import Path

import pytest

from mockingbird import asm, i2c, isa, model, spi, uart

PROGS = Path(__file__).resolve().parents[1] / "programs"


def load(name, edit=None, **cfg):
    """-> (a chip running the program, the Program). edit rewrites the source first."""
    text = (PROGS / f"{name}.s").read_text()
    prog = asm.assemble(edit(text) if edit else text)
    chip = model.Chip()
    chip.load(prog, **cfg)
    chip.start()
    return chip, prog


def run(chip, host, clocks, wires=None):
    for t in range(clocks):
        if wires:
            wires(t)
        host.clock()
        chip.clock()


def test_host_moves_one_byte_per_frame():
    chip = model.Chip()                              # engine stopped: nothing drains the TX FIFO
    host, e = model.Host(chip), chip.engines[0]
    host.send(*range(6))
    level = []
    for _ in range(6 * host.FRAME):
        host.clock()
        chip.clock()
        level.append(len(e.tx))
    assert (level[host.APPLY - 1], level[host.APPLY]) == (0, 1)
    assert [level[k * host.FRAME + host.APPLY] for k in range(6)] == [1, 2, 3, 4, 4, 4]
    assert host.refused == 2 and list(host.tx) == [4, 5]


# ---- UART at the common baud rates

BAUDS = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)


def nine_ticks_tx(text):
    assert text.count("[6]") == 2 and text.count("[5]") == 1
    return text.replace("[6]", "[7]").replace("[5]", "[6]")


def nine_ticks_rx(text):
    assert text.count("[10]") == 1 and text.count("[6]") == 1
    return text.replace("[10]", "[11]").replace("[6]", "[7]")


def test_uart_dividers_at_common_baud_rates():
    def off(clock_hz, baud, ticks):
        return abs(isa.clkdiv_for(clock_hz, baud, ticks)[2])
    assert all(off(50e6, b, 8) < 0.5 for b in BAUDS[:6])     # shipped programs, 8 ticks per bit
    assert all(off(50e6, b, 8) > 3 for b in BAUDS[6:])       # 460800 and 921600 miss
    assert all(off(50e6, b, 9) < 0.5 for b in BAUDS[6:])     # ...and hit with 9 ticks per bit
    assert all(off(60e6, b, 8) < 2 for b in BAUDS)           # at 60 MHz 8 ticks stay within 2 %


def test_uart_921600_baud_with_the_delay_fields_retimed():
    div, _, error = isa.clkdiv_for(50e6, 921600, 9)
    cpb = 9 * div                                            # 54 clocks per bit
    assert div == 6 and abs(error) < 0.5
    data = list(range(0x30, 0x50))                           # 32 bytes

    chip, prog = load("uart_tx", nine_ticks_tx, CLKDIV=div)
    host = model.Host(chip)
    host.send(*data)
    run(chip, host, len(data) * 10 * cpb + 2000)
    assert uart.decode(chip.pin_trace(prog.pins["TX"]), cpb) == data

    chip, prog = load("uart_rx", nine_ticks_rx, CLKDIV=div)
    host = model.Host(chip, pop=True)
    wave = [1] * 40 + [s for b in data for s in uart.waveform(b, cpb)] + [1] * 2000
    run(chip, host, len(wave), lambda t: chip.set_input(prog.pins["RX"], wave[t]))
    assert host.rx == data                                   # back to back at 92 kB/s, nothing lost
    assert not chip.engines[0].status() & isa.ST_RX_OVF


# ---- SPI controller, modes 0 to 3

@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_spi_controller_all_four_modes(mode):
    data = [0xC3, 0x3C, 0x00, 0xFF, 0xA5, 0x5A, 0x81, 0x7E]
    chip, prog = load("spi_master" if mode == 0 else f"spi_master_mode{mode}")
    pin = prog.pins
    host = model.Host(chip, pop=True)
    host.send(len(data) - 1, *data)
    run(chip, host, 24 * host.FRAME,
        lambda t: chip.set_input(pin["MISO"], (chip.pins.out >> pin["MOSI"]) & 1))   # MISO <- MOSI
    assert host.rx == data
    cs, sck, mosi = (chip.pin_trace(pin[k]) for k in ("CS", "SCK", "MOSI"))
    assert spi.decode(cs, sck, mosi, mosi, mode) == [(data, data)]
    frame = max(n for level, n in model.runs(cs) if level == 0)
    per_byte = 2 * host.FRAME                                # one PUSH and one POP frame per byte
    assert (len(data) - 1) * per_byte <= frame <= (len(data) + 1) * per_byte


# ---- I2C controller at 100 and 400 kHz

I2C_LIMITS_NS = {                                            # minimum times from the I2C specification
    100_000: dict(low=4700, high=4000, hd_sta=4000, su_sto=4000, su_dat=250),
    400_000: dict(low=1300, high=600, hd_sta=600, su_sto=600, su_dat=100),
}


def edges(line, to):
    return [i for i in range(1, len(line)) if line[i] == to and line[i - 1] != to]


def i2c_times(sda, scl):
    """Shortest bus times of one transaction, in clocks."""
    start = next(i for i in edges(sda, 0) if scl[i])
    stop = [i for i in edges(sda, 1) if scl[i]][-1]
    falls = [i for i in edges(scl, 0) if start < i < stop]
    rises = [i for i in edges(scl, 1) if start < i < stop]
    data_moves = [i for i in edges(sda, 0) + edges(sda, 1) if start < i < stop and not scl[i]]
    return dict(
        hd_sta=falls[0] - start,
        su_sto=stop - rises[-1],
        low=min(next(r for r in rises if r > f) - f for f in falls),
        high=min(next(f for f in falls if f > r) - r for r in rises[:-1]),
        su_dat=min(next(r for r in rises if r > i) - i for i in data_moves),
        period=min(b - a for a, b in zip(rises, rises[1:])),
    )


@pytest.mark.parametrize("clock_hz,rate,clkdiv", [
    # The SCL cycle is 12 ticks for a data bit and 11 for the ACK bit, so the divider
    # is chosen for 11 ticks: the smallest CLKDIV that stays at or under the bus rate.
    (50e6, 100_000, 46), (50e6, 400_000, 12), (60e6, 100_000, 55), (60e6, 400_000, 14),
])
def test_i2c_controller_meets_bus_timing(clock_hz, rate, clkdiv):
    chip, prog = load("i2c_master", CLKDIV=clkdiv)
    sda, scl = prog.pins["SDA"], prog.pins["SCL"]
    host = model.Host(chip)
    host.send(2, 0xA0, 0x12, 0x34)                           # count - 1, address 0x50 write, two bytes
    target = i2c.Target(0x50)
    bus = i2c.Bus(target)

    def wires(t):
        low = chip.pins.driving_low()
        s, c = bus.clock((low >> (sda - 8)) & 1, (low >> (scl - 8)) & 1)
        chip.set_input(sda, s)
        chip.set_input(scl, c)

    run(chip, host, 420 * clkdiv + 2000, wires)
    assert target.data == [0x12, 0x34]
    assert i2c.decode(bus.sda, bus.scl) == [[(0xA0, True), (0x12, True), (0x34, True)]]
    t = i2c_times(bus.sda, bus.scl)
    for name, limit in I2C_LIMITS_NS[rate].items():
        assert t[name] * 1e9 / clock_hz >= limit - 1e-6, (name, t[name])
    assert clock_hz / t["period"] <= rate + 1e-6             # never faster than the mode allows


# ---- JTAG: a host-driven bit pump

def test_jtag_pump_shifts_through_a_bypass_register():
    chip, prog = load("jtag")
    pin = prog.pins
    host = model.Host(chip, pop=True)
    tdi = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 1]
    tms = [0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1]
    host.send(*[sum((tdi[n + k] | tms[n + k] << 1) << (2 * k) for k in range(4))
                for n in range(0, 16, 4)])
    # Target: a one-bit BYPASS register. It takes TDI at each rising TCK edge and
    # shows it on TDO after the falling edge.
    target, seen = dict(tck=0, taken=0, tdo=0), []

    def wires(t):
        out = chip.pins.out
        tck, level = (out >> pin["TCK"]) & 1, (out >> pin["TDI"]) & 1
        if tck and not target["tck"]:
            target["taken"] = level
            seen.append((level, (out >> pin["TMS"]) & 1))
        if target["tck"] and not tck:
            target["tdo"] = target["taken"]
        target["tck"] = tck
        chip.set_input(pin["TDO"], target["tdo"])

    run(chip, host, 12 * host.FRAME, wires)
    assert seen == list(zip(tdi, tms))                       # what the target sampled
    tdo = [(byte >> (4 + k)) & 1 for byte in host.rx for k in range(4)]
    assert tdo == [0] + tdi[:-1]                             # BYPASS: TDI one TCK later


# ---- PS/2 device to host

def ps2_wave(byte, half=2000):
    """One device-to-host frame as per-clock (clk, dat) samples. The device moves
    DAT while CLK is high and the host reads it at the falling edge. half is the
    half period in clocks: 2000 at 50 MHz is 12.5 kHz."""
    parity = 1 - bin(byte).count("1") % 2                    # odd parity
    clk, dat = [1] * half, [1] * half
    for bit in [0] + [(byte >> k) & 1 for k in range(8)] + [parity, 1]:
        clk += [1] * half + [0] * half
        dat += [bit] * (2 * half)
    return clk, dat


def test_ps2_receiver_reads_device_clocked_frames():
    chip, prog = load("ps2_rx")
    host = model.Host(chip, pop=True)
    codes = [0x1C, 0xF0, 0x1C]                               # key A pressed, then released
    clk, dat = [1] * 500, [1] * 500
    for code in codes:
        c, d = ps2_wave(code)
        clk, dat = clk + c, dat + d
    clk, dat = clk + [1] * 4000, dat + [1] * 4000

    def wires(t):
        chip.set_input(prog.pins["CLK"], clk[t])
        chip.set_input(prog.pins["DAT"], dat[t])

    run(chip, host, len(clk), wires)
    assert host.rx == codes
    assert not chip.engines[0].status() & isa.ST_RX_OVF
