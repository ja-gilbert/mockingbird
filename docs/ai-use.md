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
Claude is guiding src/engine.v in five passes: it tells me what each pass
contains and why, and I read through the lint output with Claude.