; UART RX, 8N1, LSB first, 8 ticks per bit, sampled mid-bit.
; Same CLKDIV as uart_tx. A bad stop bit drops the byte.
.pin RX 1
.cfg SHIFT 2               ; IN_RIGHT
.cfg JMPPIN 1
.cfg CLKDIV 54

start: WAIT PIN RX, 0          ; start bit seen at tick 0
       SET  X, 7 [10]          ; ticks 1..11
bit:   IN   PIN RX, 1          ; tick 12 = centre of bit 0, then every 8
       JMP  X--, bit [6]
       JMP  PIN, good          ; tick 76 = centre of stop bit
       WAIT PIN RX, 1          ; framing error: wait for idle
       JMP  start
good:  PUSH                    ; byte to host; ISR cleared
       JMP  start
