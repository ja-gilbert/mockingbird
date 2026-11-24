# Brief: programs/ws2812.s

Jamie writes this program. Claude wrote the decoder and the test, not the program.

## Goal

Drive a strip of WS2812B LEDs. The host pushes bytes, three per LED in the
order green, red, blue. Your program sends every byte it gets, most
significant bit first, on one output pin.

## The protocol

- The line rests low.
- Every bit is one high pulse followed by a low gap. The length of the high
  pulse says whether it is a 0 or a 1.

| Bit | High | Low | Allowed error on each |
|---|---|---|---|
| 0 | 0.40 us | 0.85 us | 0.15 us |
| 1 | 0.80 us | 0.45 us | 0.15 us |

- A low of 50 us or more ends the frame: the LEDs latch what they received.
  So the program ends a frame by doing nothing. When the host stops pushing,
  the line just stays low.

## What you have to work with

- One clock is 20 ns. A tick is CLKDIV clocks. You choose CLKDIV.
- Each instruction takes one tick, plus its `[delay]` of 0 to 15 more ticks.
- A pin changes at the end of the tick that writes it.
- You should need only `PULL`, `SET`, `SETP PIN`, `OUT PIN` and `JMP`.
- `.cfg SHIFT 0` makes `OUT` take the most significant bit first.
- The spec is `docs/isa-v0.md`. `programs/uart_tx.s` is the closest example.

## Requirements

- File `programs/ws2812.s` with `.pin DIN 0`, `.cfg SHIFT 0` and your
  `.cfg CLKDIV`.
- Every high pulse and every low gap inside its window from the table. That
  includes the gap between the last bit of one byte and the first bit of the
  next, where your program has extra work to do.
- 16 words or fewer. Under 10 is possible.

## A question to start from

Draw the waveform of a 0 above the waveform of a 1, aligned at the rising
edge. Which stretch of the bit is the same in both, and which stretch is the
only place they differ?

## Count before you run

Fill this in for your program. It is the whole exercise.

| Stretch | Instructions | Ticks | Nanoseconds | Window |
|---|---|---|---|---|
| High, bit 0 | | | | 250 to 550 |
| High, bit 1 | | | | 650 to 950 |
| Low after a 0, inside a byte | | | | 700 to 1000 |
| Low after a 1, inside a byte | | | | 300 to 600 |
| Low after a 0, at a byte boundary | | | | 700 to 1000 |
| Low after a 1, at a byte boundary | | | | 300 to 600 |

The last two rows decide your CLKDIV. A coarse tick makes the boundary gap
too long.

## Check your work

```
.venv/bin/python -m mockingbird.asm programs/ws2812.s
.venv/bin/python -m pytest tests/test_ws2812.py -q
```

The first prints your listing. The second pushes two frames through a host
limited to one byte per 196 clocks, as the real port is, reads your pin with
a decoder that enforces the table above, and expects the same bytes back.
When a window is missed the error names the clock and the measured time.
Until the file exists the test reports "skipped".

## If you get stuck

Read this only after a real attempt. The engine cannot branch on a data bit.
It does not need to. Split the bit into three stretches: always high, then
the level of the data bit itself, then always low. `OUT PIN` puts a data bit
on the pin directly.

## Afterwards

Note the word count, your CLKDIV and what was awkward. Those go into row 14
of `docs/flexibility-probe.md`.
