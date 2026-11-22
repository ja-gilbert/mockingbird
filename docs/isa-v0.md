# Mockingbird ISA v0 (frozen 2026-11-20)

Reference for the assembler, the Python model and the RTL. Written by Claude
from the architecture agreed on 2026-11-20; see docs/ai-use.md. Changes after
the freeze go through docs/decisions.md.

## Parameters

| Name | v0 value | Notes |
|---|---|---|
| WIDTH | 8 | data path: X, Y, ISR, OSR, FIFO words |
| DEPTH | 32 | program words per engine, private memory |
| NENGINES | 1 | engine module instantiated in a generate loop |
| FIFO_DEPTH | 4 | TX and RX FIFO, per engine |
| Core clock | 50 MHz target | `clock_hz` in info.yaml; fall back to 25 MHz if timing fails |

## Pins

Three 16-entry pin spaces, addressed by a 4-bit index.

| Index | Input space | Output space | Direction space |
|---|---|---|---|
| 0..7 | `ui_in[i]` | `uo_out[i]` | none (writes ignored) |
| 8..15 | `uio_in[i-8]` | `uio_out[i-8]` | `uio_oe[i-8]` |

Reserved for the host port: input 5 = CS, input 6 = SCK, input 7 = MOSI,
output 7 = MISO. Engine writes to output 7 are masked. Engine reads of
inputs 5..7 return the live pin.

Chip reset (`rst_n` low) sets every output level to 0 and every direction to
0 (input). Engine CLR does not touch pins.

## Timing model

- **Tick.** Each engine has a 16-bit CLKDIV. A divider counter counts core
  clocks while RUN = 1 and asserts a tick when it reaches CLKDIV - 1, then
  resets to 0. CLKDIV values 0 and 1 both mean a tick every clock. The
  counter is held at zero while RUN = 0 and by CLR, so the first tick after
  RUN rises comes exactly CLKDIV clocks later (one clock for 0 or 1),
  however the engine was stopped.
- **One instruction per tick.** On a tick: if the delay counter is nonzero
  it decrements and nothing else happens. Otherwise the instruction at PC
  executes. If it stalls, PC and all state hold and the delay is not
  started. If it completes, its effects apply, PC advances or jumps, and the
  delay counter is loaded from the delay field.
- **Only three things stall:** WAIT with its condition false, PULL with
  blk = 1 on an empty TX FIFO, PUSH with blk = 1 on a full RX FIFO. Status
  bit STALLED is 1 while stalled.
- **Delay** is 0..15 extra ticks after the instruction completes, including
  after a stall resolves.
- **Inputs** pass through a two-flop synchronizer: a pin level present
  before clock edge t is seen by an instruction executing at edge t + 2 or
  later. The model reproduces this delay exactly.
- **Outputs.** An instruction presents its pin writes as combinational
  strobes during its tick cycle; the pin register file registers them at
  the clock edge that completes the instruction, the same edge at which pc
  advances. The pad shows the new level from that edge on. A later
  instruction reads it back only after the synchronizer delay above.
- **RUN = 0** freezes the engine: pc, delay counter, X, Y, ISR, OSR, FIFOs,
  pins and the STALLED flag all hold their values. Only the divider counter
  is cleared.

## Engine state

PC (5 bits), X, Y, ISR, OSR (8 bits each), delay counter (4 bits), TX FIFO
and RX FIFO (4 x 8 bits each), sticky RX_OVF flag. Program memory is 32 x 16
bits, private to the engine, contents undefined until written.

CLR: PC <= START, X = Y = ISR = OSR = 0, delay = 0, both FIFOs emptied,
RX_OVF = 0, any stall cleared. CLKDIV, START, SHIFT, JMPPIN, PTR and the
program memory are unchanged.

## Instruction format

`[15:12] op | [11:8] delay | [7:0] arg`. Count fields use 0 to mean 8.

| op | Mnemonic | arg bits | Semantics |
|---|---|---|---|
| 0 | JMP | `[7:5] cond, [4:0] target` | If cond holds, `PC <= {PC[msb:5], target}` (page-relative; identical to absolute with DEPTH = 32). Else PC + 1. |
| 1 | WAIT | `[7] pol, [6:4] 0, [3:0] idx` | Stall until `in[idx] == pol`. |
| 2 | IN | `[7] null, [6:3] idx, [2:0] cnt` | Shift cnt bits into ISR from `in[idx +: cnt]`, or zeros if null = 1. |
| 3 | OUT | `[7] dir, [6:3] idx, [2:0] cnt` | Shift cnt bits out of OSR to `out[idx +: cnt]`, or to `oe[idx +: cnt]` if dir = 1. |
| 4 | PUSH | `[7] blk, [6:0] 0` | RX FIFO <= ISR, then ISR <= 0. blk = 1: stall while full. blk = 0: if full, drop, set RX_OVF, still clear ISR. |
| 5 | PULL | `[7] blk, [6:0] 0` | OSR <= TX FIFO head, pop. blk = 1: stall while empty. blk = 0: if empty, OSR <= X. |
| 6 | MOV | `[7:5] dst, [4:3] op, [2:0] src` | dst <= op(src). Codes 0 X, 1 Y, 2 ISR, 3 OSR, 4 NULL. op: 0 copy, 1 bitwise invert, 2 bit reverse. MOV to ISR or OSR replaces the whole register. dst 4 discards the result. Every other combination (dst 5..7, with 5 reserved for PC in v1; src 5..7; op 3) is a NOP: no register changes, pc + 1, delay applied. |
| 7 | SET | `[7] reg, [6:0] imm` | reg 0: X <= imm. reg 1: Y <= imm. Range 0..127. |
| 8 | SETP | `[7] dir, [6] val, [5:4] 0, [3:0] idx` | dir = 0: `out[idx] <= val`. dir = 1: `oe[idx] <= val`. |
| 9..15 | reserved | | NOP in v0: no state change, pc + 1, delay applied. |

Argument bits the table marks 0 (WAIT [6:4], PUSH and PULL [6:0], SETP
[5:4]) are ignored when set.

JMP conditions:

| cond | Name | Holds when | Side effect |
|---|---|---|---|
| 0 | always | always | none |
| 1 | `!X` | X == 0 | none |
| 2 | `X--` | X != 0 | X <= X - 1 (only when it holds) |
| 3 | `!Y` | Y == 0 | none |
| 4 | `Y--` | Y != 0 | Y <= Y - 1 (only when it holds) |
| 5 | `X!=Y` | X != Y | none |
| 6 | `PIN` | `in[JMPPIN] == 1` | none |
| 7 | `!PIN` | `in[JMPPIN] == 0` | none |

Shift semantics (n = count, SHIFT register bits):

- OUT with OUT_RIGHT = 1: data = `OSR[n-1:0]`, then `OSR >>= n` (zero fill). LSB first.
- OUT with OUT_RIGHT = 0: data = `OSR[7:8-n]`, then `OSR <<= n`. MSB first.
- IN with IN_RIGHT = 1: `ISR = (ISR >> n) | (data << (8-n))`. LSB first; a full byte lands in ISR[7:0].
- IN with IN_RIGHT = 0: `ISR = (ISR << n) | data`. MSB first.
- Pin groups: bit k of data pairs with pin index idx + k. Indices beyond 15 are ignored.

`NOP` is the assembler alias for `MOV Y, Y`.

## Config registers (per engine, written by host CFG)

| reg | Name | Bits | Meaning |
|---|---|---|---|
| 0 | CLKDIV | 15:0 | ticks every CLKDIV clocks; 0 and 1 mean every clock |
| 1 | CTRL | 0 RUN, 1 CLR | CLR is a self-clearing pulse |
| 2 | START | 4:0 | PC loaded by CLR |
| 3 | SHIFT | 0 OUT_RIGHT, 1 IN_RIGHT | shift directions |
| 4 | JMPPIN | 3:0 | input index tested by JMP PIN / !PIN |
| 5 | PTR | 4:0 | program load pointer, auto-increments on PROG |
| 6, 7 | reserved | | ignored |

All config registers reset to 0.

## Host port (fixed SPI slave)

Mode 0: CS active low, MOSI sampled on SCK rising edge, MISO changes on SCK
falling edge. 24 clocks per frame, MSB first.

MOSI frame: `[23:21] cmd | [20:19] eng | [18:16] reg | [15:0] data`.

| cmd | Name | Effect, applied at the 24th rising edge |
|---|---|---|
| 0 | STATUS | none |
| 1 | PROG | `mem[eng][PTR] <= data; PTR <= PTR + 1`, only while the engine's RUN = 0; ignored otherwise, PTR unchanged |
| 2 | CFG | `cfg[eng][reg] <= data` |
| 3 | PUSH | if accepted, TX FIFO of eng <= `data[7:0]` |
| 4 | POP | if accepted, RX FIFO of eng pops one |
| 5 | PEEK | reserved: response carries `mem[eng][PTR]`, PTR + 1 (v1) |
| 6, 7 | reserved | ignored |

MISO frame: `[23:16] ID = 0x4D | [15:8] status | [7:0] rx_head`.

- ID is driven from CS falling edge, so it is valid on clocks 1..8.
- After the 8th rising edge the port latches, for engine `eng`: status,
  rx_head, `accept_push = !TX_FULL` and `accept_pop = RX_VALID`. Status and
  rx_head are driven on clocks 9..24 and describe the state before this
  frame's command executes.
- PUSH executes only if `accept_push`; POP only if `accept_pop`. Because
  only the host fills the TX FIFO and only the host empties the RX FIFO,
  the latched status is an exact acknowledgement: TX_FULL = 0 in a PUSH
  frame means that byte was accepted; RX_VALID = 1 in a POP frame means
  rx_head is exactly the byte removed.
- `eng` >= NENGINES: command ignored, status and rx_head read 0.

Status byte: bit 0 RX_VALID, 1 TX_FULL, 2 RUNNING, 3 STALLED, 4 TX_EMPTY,
5 RX_FULL, 6 RX_OVF (sticky, cleared by CLR), 7 zero. STALLED is the
outcome of the engine's most recent execution attempt; it holds while
RUN = 0 and is cleared by CLR and by reset.

Program loading: stop the engine first. PROG frames addressed to an engine
with RUN = 1 are ignored and leave PTR unchanged; the host can see RUNNING
in the same frame's status byte. CFG writes are accepted at any time and
take effect immediately.

Electrical rules: CS, SCK and MOSI pass through two-flop synchronizers and
edges are detected in the core clock domain. SCK period must be at least 8
core clocks (6.25 MHz at 50 MHz). CS high resets the bit counter, so frames
shorter than 24 clocks are discarded and clocks beyond 24 are ignored.
Timing at the pins, in core clocks: CS low at least 4 before the first SCK
rising edge; CS held low at least 4 after the 24th SCK rising edge, which
guarantees the final bit is counted before CS ends the frame because CS and
SCK see the same synchronizer delay; the final SCK falling edge is optional;
CS high at least 4 between frames; MOSI stable from 1 before to 1 after
each SCK rising edge, which a mode-0 master that changes MOSI on the falling
edge meets by a wide margin. MISO is a registered output.

## Multiple engines

Each engine owns its memory, PC, config, FIFOs and registers. Pin registers
are shared: any engine may read any input; if two engines write the same
output or direction bit in the same clock, the higher-numbered engine wins.
The assembler warns when programs loaded together name the same output pin.

## Assembler syntax

```
; comment to end of line
.pin  TX 0             ; name -> index (space chosen by the operand keyword)
.cfg  CLKDIV 54        ; optional config carried with the program
.cfg  SHIFT 1
label:
    SETP PIN TX, 1 [6] ; mnemonic, operands, optional [delay]
```

| Form | Examples |
|---|---|
| `JMP [cond,] label` | `JMP loop`, `JMP X--, bit`, `JMP PIN, good`, `JMP !PIN, err`, `JMP X!=Y, l` |
| `WAIT PIN name, pol` | `WAIT PIN RX, 0` |
| `IN PIN name, n` / `IN NULL, n` | `IN PIN RX, 1` |
| `OUT PIN name, n` / `OUT DIR name, n` | `OUT PIN TX, 1`, `OUT DIR SDA, 1` |
| `PUSH [NOBLOCK]` / `PULL [NOBLOCK]` | default is blocking |
| `MOV dst, [~|::]src` | `MOV Y, OSR`, `MOV OSR, ~OSR`, `MOV ISR, ~NULL`, `MOV X, ::X` |
| `SET X|Y, imm` | `SET X, 7` |
| `SETP PIN name, v` / `SETP DIR name, v` | `SETP DIR SCL, 0` |
| `NOP` | alias for `MOV Y, Y` |

Numbers are decimal or `0x` hex. Labels must be within the JMP's 32-word
page. Program length over DEPTH is an error.

## Deferred to v1, with triggers

| Item | Add when |
|---|---|
| DEPTH 64 or 128, MOV PC far jumps | a program exceeds 32 words (I2C read with repeated START) |
| PEEK read-back | FPGA or silicon bring-up |
| Autopull / autopush | programs run out of words |
| Side-set | a protocol cannot meet timing, or UART TX must shrink from 8 words to 5 |
| Fractional CLKDIV | a required baud rate misses tolerance with integer division |
| Open-drain mode bit per pin | I2C programs become unreadable |
| Engine flags / IRQ, WAIT source 1 | two engines must synchronize |
