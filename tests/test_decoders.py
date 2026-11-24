"""The protocol decoders checked on hand-built waveforms, with no model involved."""
import pytest

from mockingbird import i2c, spi


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
