"""Starving programs/ws2812.s on purpose, to pin where it stops meeting the
datasheet. The program takes a byte every 486 clocks. When the host is slower,
the FIFO is empty at every PULL: the engine waits with the line low, and each
tick of waiting adds 40 ns to that byte's boundary gap. Those gaps have 80 ns
to spare, which is two ticks, 4 clocks. So a host at 490 clocks per byte still
meets the datasheet, with nothing left over, and a host at 491 does not.

This is the cliff edge, not the margin requirement. The margin requirement is
in tests/test_ws2812.py: 50 ns to spare while the host keeps up."""
from pathlib import Path

import pytest

from mockingbird import asm, model, ws2812

PROG = Path(__file__).resolve().parents[1] / "programs" / "ws2812.s"
BYTE_CLOCKS = 486            # what the program takes when a byte is always waiting
SPARE_CLOCKS = 4             # the 80 ns margin on a boundary gap: two 40 ns ticks


def frame_at(clocks_per_byte, nbytes):
    """-> (pin trace, data) for one frame, with the host pushing a byte every
    clocks_per_byte clocks into a FIFO that was empty when the engine started."""
    prog = asm.assemble(PROG.read_text())
    chip = model.Chip()
    chip.load(prog)
    chip.start()
    host = model.Host(chip, frame=clocks_per_byte)
    data = [(53 * k + 7) & 0xFF for k in range(nbytes)]
    host.send(*data)
    for _ in range((nbytes + 2) * clocks_per_byte + 3000):
        host.clock()
        chip.clock()
    return chip.pin_trace(prog.pins["DIN"]), data


@pytest.mark.parametrize("nbytes", [3, 24, 180])
def test_ws2812_starvation_limit(nbytes):
    limit = BYTE_CLOCKS + SPARE_CLOCKS                       # 490 clocks per byte
    line, data = frame_at(limit, nbytes)
    assert ws2812.decode(line, 50_000_000) == [data]         # every byte 4 clocks late: on the limit, legal
    line, data = frame_at(limit + 1, nbytes)
    with pytest.raises(ValueError, match="low for"):         # one clock slower: a gap leaves its window
        ws2812.decode(line, 50_000_000)
