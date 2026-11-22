; UART TX, 8N1, LSB first, 8 ticks per bit.
; CLKDIV = clock / (8 * baud): 50 MHz at 115200 baud -> 54
.pin TX 0
.cfg SHIFT 1               ; OUT_RIGHT
.cfg CLKDIV 54

init:  SETP PIN TX, 1          ; idle high (outputs reset to 0)
loop:  PULL                    ; block for a byte; line stays high
       SETP PIN TX, 0 [6]      ; start bit, 7 ticks
       SET  X, 7               ; 8th tick of start bit
bit:   OUT  PIN TX, 1          ; data bit
       JMP  X--, bit [6]       ; 8 ticks per bit, eight bits
       SETP PIN TX, 1 [5]      ; stop bit, 6 ticks
       JMP  loop               ; +1, PULL +1 = 8 ticks of stop
