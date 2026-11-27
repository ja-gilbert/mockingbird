"""The protocol decoders checked on hand-built waveforms, with no model involved."""
import pytest

from mockingbird import i2c, spi, ws2812


def spi_wave(byte):
    """One mode-0 frame for a byte, two samples per SCK phase: cs, sck, mosi."""
    cs, sck, mosi = [1, 1, 0], [0, 0, 0], [0, 0, 0]
    for k in range(7, -1, -1):
        bit = (byte >> k) & 1
        cs += [0] * 4
        sck += [0, 0, 1, 1]
        mosi += [bit] * 4
    return cs + [0, 1, 1], sck + [0, 0, 0], mosi + [0, 0, 0]


def test_spi_decode_frame_and_partial_byte():
    cs, sck, mosi = spi_wave(0xA6)
    miso = [1 - b for b in mosi]
    assert spi.decode(cs, sck, mosi, miso) == [([0xA6], [0x59])]
    with pytest.raises(ValueError):
        spi.decode(cs[:-12] + [1, 1], sck[:-12] + [0, 0], mosi[:-12] + [0, 0], miso[:-12] + [0, 0])

    with pytest.raises(ValueError):
        spi.decode(cs, sck, mosi, miso, mode=2)      # mode 2 needs SCK idling high

def i2c_wave(byte, ack):
    """START, one byte, the ACK bit, STOP: sda, scl, two samples per phase."""
    sda, scl = [1, 1, 0, 0], [1, 1, 1, 1]            # START: SDA falls while SCL is high
    for bit in [(byte >> k) & 1 for k in range(7, -1, -1)] + [0 if ack else 1]:
        sda += [bit] * 4
        scl += [0, 0, 1, 1]
    return sda + [0, 0, 0, 0, 1, 1], scl + [0, 0, 1, 1, 1, 1]    # STOP: SDA rises while SCL is high


def test_i2c_decode_ack_nack_and_partial_byte():
    assert i2c.decode(*i2c_wave(0xA0, True)) == [[(0xA0, True)]]
    assert i2c.decode(*i2c_wave(0x3D, False)) == [[(0x3D, False)]]
    sda, scl = i2c_wave(0xA0, True)
    with pytest.raises(ValueError):
        i2c.decode(sda[:16] + sda[-6:], scl[:16] + scl[-6:])     # STOP after three bits


def test_i2c_target_acks_only_its_address():
    for addr, acked in ((0x50, True), (0x51, False)):
        target = i2c.Target(addr)
        bus = i2c.Bus(target)
        sda, scl = i2c_wave(0xA0, False)             # the controller never drives the ACK bit low
        for s, c in zip(sda, scl):
            bus.clock(not s, not c)
        assert i2c.decode(bus.sda, bus.scl) == [[(0xA0, acked)]]


def ws_wave(byte, high0=20, low0=42, high1=40, low1=22):
    """One byte at 50 MHz, MSB first: a 0 is 400 ns high then 840 ns low, a 1 is
    800 ns high then 440 ns low. Then 60 us of low, which is a reset."""
    line = [0, 0]
    for k in range(7, -1, -1):
        bit = (byte >> k) & 1
        line += [1] * (high1 if bit else high0) + [0] * (low1 if bit else low0)
    return line + [0] * 3000


def test_ws2812_decode_and_timing_limits():
    assert ws2812.decode(ws_wave(0xA5) + ws_wave(0x3C), 50e6) == [[0xA5], [0x3C]]
    assert ws2812.decode(ws_wave(0xA5)[:-3000] + ws_wave(0x3C)[2:], 50e6) == [[0xA5, 0x3C]]
    with pytest.raises(ValueError):
        ws2812.decode(ws_wave(0xA5, high0=30), 50e6)             # 600 ns high: neither a 0 nor a 1
    with pytest.raises(ValueError):
        ws2812.decode(ws_wave(0xA5, low1=40), 50e6)              # 800 ns low after a 1: too long
    with pytest.raises(ValueError):
        ws2812.decode(ws_wave(0xA5)[:-3000 - 22 - 40], 50e6)     # seven bits, then the line stays low


def test_ws2812_margins_measure_the_distance_to_each_limit():
    assert ws2812.margins(ws_wave(0xA5), 50e6) == dict(T0H=150, T1H=150, T0L=140, T1L=140)
    assert ws2812.margins(ws_wave(0xA5, low1=30), 50e6)["T1L"] == 0      # 600 ns low: exactly on the limit
    assert ws2812.margins(ws_wave(0xA5, high0=10), 50e6)["T0H"] == -50   # 200 ns high: 50 ns outside
