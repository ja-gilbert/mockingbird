.pin DIN 0
.cfg SHIFT 0
.cfg CLKDIV 2

init:
    SETP PIN DIN, 0


byte:
    PULL
    SET X, 7

bit:
    SETP PIN DIN, 1 [9]     ; Stretch A: Always HIGH
    OUT  PIN DIN, 1 [9]     ; Stretch B: Output data bit
    SETP PIN DIN, 0 [8]     ; Stretch C: Always LOW
    JMP  X--, bit
    JMP  byte