; UART RX, 8N1, LSB first, 8 ticks per bit, sampled mid-bit.
; Same CLKDIV as uart_tx. A bad stop bit drops the byte.
; A full RX FIFO also drops the byte and sets RX_OVF. The PUSH must not
; block: the sender owns the timing, so a stalled engine would lose its
; place in the stream and take a data bit for the next start bit.
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
good:  PUSH NOBLOCK            ; byte to host, or dropped with RX_OVF; ISR cleared
       JMP  start
