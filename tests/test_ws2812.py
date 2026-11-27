"""Check for programs/ws2812.s. The brief is docs/ws2812-brief.md. These tests
skip until the program exists. The host is paced like the real port (one byte
per 196 clocks) and the decoder enforces the WS2812B datasheet windows."""
from pathlib import Path

import pytest

from mockingbird import asm, model, ws2812

PROG = Path(__file__).resolve().parents[1] / "programs" / "ws2812.s"
CLOCK_HZ = 50_000_000
RESET_CLOCKS = 3000                                  # 60 us, longer than the 50 us reset
MARGIN_NS = 50                                       # how far inside its window every time must sit

pytestmark = pytest.mark.skipif(not PROG.exists(), reason="programs/ws2812.s is not written yet")


def send(chip, host, data):
    host.send(*data)
    for _ in range(len(data) * 8 * 70 + RESET_CLOCKS + 2 * host.FRAME):
        host.clock()
        chip.clock()


def test_ws2812_frames_meet_the_datasheet():
    prog = asm.assemble(PROG.read_text())
    chip = model.Chip()
    chip.load(prog)
    chip.start()
    host = model.Host(chip)
    first = [0x10, 0x80, 0x01, 0xFF, 0x00, 0xA5]     # two pixels, G R B each
    second = [0x55, 0xAA, 0x0F]                      # one more pixel after a reset gap
    send(chip, host, first)
    send(chip, host, second)
    line = chip.pin_trace(prog.pins["DIN"])
    assert ws2812.decode(line, CLOCK_HZ) == [first, second]
    assert line[-1] == 0                             # the line rests low


def test_ws2812_keeps_a_margin_inside_every_window():
    """With the host keeping the FIFO fed, no pulse and no gap comes closer than
    50 ns to a datasheet limit. The decoder accepts a time exactly on a limit,
    so without this check a program with no margin at all still passes."""
    prog = asm.assemble(PROG.read_text())
    chip = model.Chip()
    chip.load(prog)
    chip.start()
    send(chip, model.Host(chip), [0x10, 0x80, 0x01, 0xFF, 0x00, 0xA5, 0x55, 0xAA, 0x0F])
    worst = ws2812.margins(chip.pin_trace(prog.pins["DIN"]), CLOCK_HZ)
    assert set(worst) == {"T0H", "T1H", "T0L", "T1L"}    # every kind of pulse and gap occurred
    assert min(worst.values()) >= MARGIN_NS, worst


def test_ws2812_program_is_small():
    assert len(asm.assemble(PROG.read_text()).words) <= 16
