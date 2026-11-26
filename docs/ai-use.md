# AI Use Log

## 11-10-2026
Claude Code drafted an initial CLAUDE.md, currently it has not been committed
into this repository.

## 11-20-2026
Claude Code (Claude Fable 5.1) acted as hardware architect for ISA v0. I set
the constraints (Tiny Tapeout 8x4 tile, PIO-style engine, UART, SPI and I2C
as targets, I write the engine myself). Claude recommended the six design
constraints, the instruction encoding, the SPI host protocol and the FIFO
acceptance scheme, and wrote docs/isa-v0.md. I reviewed and accepted each
in writing before the freeze. Claude also sketched the UART TX/RX, SPI
master and I2C master programs to show the ISA covers them.

## 11-21-2026
Claude wrote directly, with me reviewing the diffs: mockingbird/ (isa.py,
asm.py, model.py, uart.py), programs/*.s, src/host_port.v, src/fifo8.v,
src/project.v, test/test.py, test/test_engine.py, tests/*.py and the
test/Makefile changes. Claude gave the port list and behavioral contract
for src/engine.v, which I write myself. I raised six spec questions
(output timing, divider reset, reserved MOV, CS hold, PROG while running,
STALLED meaning); Claude proposed the resolutions, I accepted them, and
they are logged in docs/decisions.md.

## 11-22-2026
Claude wrote the code for src/engine.v in five passes with a short lesson
per pass; I wrote each pass in, linted it and reviewed it against the spec.
Claude test-ran pass 5 in a scratch copy before I typed it, and fixed three
bugs in its own test files that the first real engine run exposed (compare
timing and one wrong expectation in test/test_engine.py, the pin sampler in
test/test.py). All 15 engine tests, 3 chip tests and 23 model tests pass.

Also on the 22nd, after the engine passed, Claude wrote the verification
for the remaining protocols: independent SPI and I2C decoders 
(mockingbird/spi.py, mockingbird/i2c.py), a simulated I2C device with
clock stretching, the decoder tests in tests/test_decoders.py, and four
chip-level tests in test/test.py (UART RX, SPI loopback, I2C write with
ACK and stretching, I2C NACK). Claude also added the Python and engine
tests to the CI workflow and wrote the first draft of docs/info.md. I 
reviewed the diff. Totals now: 27 Python tests, 15 engine tests, 7 chip
tests, all passing.

## 11-23-2026
A separate Claude review session found a bug in programs/uart_rx.s, which
Claude had written: a blocking PUSH froze the receiver when the RX FIFO 
was full, so it lost its place in the stream and returned garbage bytes 
with no overflow flag. I brought the finding to the implementation session.
Claude confirmed it in the model (garbage in 256 of 320 trial timings), and 
wrote one model test and chip-level test that fail on the old program, and 
changed the PUSH to non-blocking. 28 Python tests, 15 engine tests and 8 chip
tests pass.

Claude proposed a roadmap after version 0: a flexibility probe in the Python
model, then version 1 decisions, build, verification, potential FPGA prototype
and write-up. A second Claude session reviewed the proposal against the 
competition page and made two changes: build the gap list from the page's
own protocol list, and judge each row against the whole chip, including the
host port's byte rate and the 4-byte FIFOs, with tests paced at one byte per
196 clocks. Claude then wrote the paced host model, the SPI mode, JTAG and 
PS/2 programs, the WS2812 decoder and test, the probe tests and 
docs/flexibility-probe.md. I am going to write programs/ws2812.s myself
from Claude's brief.

## 11-25-2026
I wrote programs/ws2812.s myself from a brief by Claude: 8 words. My first version used CLKDIV 5 and passed the tests with zero margin on the four low times. Claude reviewed it without changing anything, it confirmed my timing in the model and on the RTL, showed that the zero margin was forced at that tick, and gave the best possible margin for each CLKDIV. Then, I retimed the program to CLKDIV 2 with delays 9, 9, and 8, which I worked out myself. Claude's second review confirmed the 80 ns worst-case margin in the model and on the RTL through the host port, measured that the engine consumes one byte per 486 clocks and tolerates a byte up to 4 clocks late, and ran the full regression suite. Claude then updated row 14 and the gap list in
docs/flexibility-probe.md with these results.