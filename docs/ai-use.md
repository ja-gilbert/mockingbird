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
## 11-22-2026
Claude wrote the code for src/engine.v in five passes with a short lesson
per pass; I wrote each pass in, linted it and reviewed it against the spec.
Claude test-ran pass 5 in a scratch copy before I typed it, and fixed three
bugs in its own test files that the first real engine run exposed (compare
timing and one wrong expectation in test/test_engine.py, the pin sampler in
test/test.py). All 15 engine tests, 3 chip tests and 23 model tests pass.