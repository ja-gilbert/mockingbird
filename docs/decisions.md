# Decision Log

## 11-20-2026 (ISA v0 freeze)

- **Private 32x16 program memory per engine.** Engines never contend for
  fetch, and a second engine costs only its own memory. Alternative: one
  shared memory with a wider PC. Rejected because small duplicated blocks
  suit the 8x4 tile and every target program fits (I2C master is 31 words).
- **Page-relative JMP with a 5-bit target.** Covers all 32 words in v0, and
  a larger memory in v1 needs no new encoding.
- **Latch-time FIFO acceptance in the host port.** The status byte returned
  during a PUSH or POP frame is latched one clock after the 8th bit, and the
  same latched flags decide whether that command is applied. The host knows
  from the reply whether its byte went in or came out, no second round trip.
- **No autopull, side-set or fractional divider in v0.** Each is deferred
  until a protocol needs it; see "Deferred to v1" in docs/isa-v0.md.

## 11-21-2026 (clarifications; spec, model and top updated)

- Pin writes register at the clock edge that completes the instruction;
  the write strobes are combinational during the tick cycle.
- The divider counter is held at zero while RUN = 0, so the first tick
  comes exactly CLKDIV clocks after RUN rises. Everything else holds.
- MOV with dst 5..7, src 5..7 or op 3 is a NOP: pc + 1, delay applied.
  dst 4 (NULL) is a defined discard. Opcodes 9..15 are NOPs too.
- SPI host timing: CS stays low at least 4 core clocks after the 24th SCK
  rise; MOSI is stable one clock either side of each SCK rise.
- PROG is ignored, and PTR unchanged, while that engine's RUN = 1.
  CFG is accepted at any time.
- STALLED is the result of the last execution attempt. It holds while
  RUN = 0 and clears on CLR or reset.

## 11-22-2026 (checkpoint)

- **Checkpoint met four days early; staying with the custom engine.** Two
  UART bytes pushed through the SPI host port leave TX with the reference
  model's exact bit timing and decode correctly (uart_tx_bytes_match_model).
  The RISC-V fallback should not be needed.
  
## 11-22-2026 (first hardening run)

- **50 MHz confirmed.** The first 8x4 hardening run (one engine) has no
  setup or hold violations in the fast, typical and slow corners, passes
  DRC and LVS, and the gate-level test passes. The 25 MHz fallback is not
  needed. The design uses about 7% of the core area, so more engines fit.

## 11-23-2026 (roadmap after version 0)
- **Flexibility probe before any version 1 design.** The chip has been 
tested against the competition page's own protocol list, in the Python model
only, and the result has also been recorded by Claude in 
docs/flexibility-probe.md. Each row is judged against the whole chip (4-byte
FIFOs, one byte per 196-clock host frame), not only the instruction set, and 
probe tests pace the host at that rate. Nothing under src/ changes during the
probe. The gap list is going to drive my version 1 decisions.
- **WS2812 program written by me** from a brief, I'm going to write this one 
end-to-end to learn the instruction set as a programmer.
- **Order after the probe:** version 1 decisions, version 1 build with me 
updating the engine with the changes from the contract and failing tests, 
deeper verification, potential FPGA prototype, and a final write-up.

## 11-25-2026 (timing margin rule)
- **Protocol programs must keep at least 50 ns inside every datasheet window** when the host keeps up. The first WS2812 version met every window with zero margin and passed the decoder, so the decoder alone is not enough. Starvation limits are tested separately and are allowed to sit on a limit. 
