; JTAG bit pump. The host runs the TAP state machine; the engine moves the pins.
; Each host byte holds four (TDI, TMS) pairs, first pair in bits 1:0, with TDI
; the lower bit of each pair. For every byte the engine pushes one byte back
; holding the four TDO samples in bits 7:4, first sample in bit 4.
; Five ticks per TCK cycle: 10 MHz at CLKDIV 1 on a 50 MHz clock.
.pin TDO 0                 ; input space
.pin TCK 2                 ; output space
.pin TDI 3                 ; TDI and TMS are a two-pin group
.pin TMS 4
.cfg SHIFT 3               ; OUT_RIGHT and IN_RIGHT: LSB first both ways
.cfg CLKDIV 1

init:  SETP PIN TCK, 0
loop:  PULL                    ; four pairs; TCK stays low while waiting
       SET  X, 3
bit:   OUT  PIN TDI, 2         ; TDI and TMS together, while TCK is low
       SETP PIN TCK, 1         ; rising edge: the target samples them
       IN   PIN TDO, 1         ; TDO as it was at the rising edge
       SETP PIN TCK, 0         ; falling edge: the target moves TDO
       JMP  X--, bit
       PUSH                    ; four TDO samples
       JMP  loop
