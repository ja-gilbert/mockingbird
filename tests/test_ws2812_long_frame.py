"""A long WS2812 frame: 60 LEDs, 180 bytes. The host offers a byte every 196
clocks and the program takes one every 486, so the TX FIFO fills, pushes are
refused and retried, and the program has to keep its timing through all of it."""
from pathlib import Path

from mockingbird import asm, isa, model, ws2812

PROG = Path(__file__).resolve().parents[1] / "programs" / "ws2812.s"


def test_ws2812_180_byte_frame_with_a_full_fifo():
    prog = asm.assemble(PROG.read_text())
    chip = model.Chip()
    chip.load(prog)
    chip.start()
    host, engine = model.Host(chip), chip.engines[0]
    data = [(37 * k + 11) & 0xFF for k in range(180)]
    host.send(*data)
    fullest = 0
    for _ in range(len(data) * 8 * 70 + 3000):       # the frame, then a reset gap
        host.clock()
        chip.clock()
        fullest = max(fullest, len(engine.tx))
    assert ws2812.decode(chip.pin_trace(prog.pins["DIN"]), 50_000_000) == [data]
    assert fullest == isa.FIFO_DEPTH                 # the FIFO really was full
    assert host.refused > 0 and not host.tx          # pushes were refused, retried, and all arrived
