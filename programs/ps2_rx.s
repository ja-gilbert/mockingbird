; PS/2 device-to-host receiver (keyboard or mouse). The device drives both
; lines and sets the pace, 10 to 16.7 kHz; each bit is read just after a
; falling clock edge. Frame: start, 8 data bits LSB first, odd parity, stop.
; Pushes the 8 data bits. Parity is not checked: the engine has no way to
; compute it. A full RX FIFO drops the byte and sets RX_OVF, as in uart_rx.s.
.pin CLK 1                 ; input space
.pin DAT 2
.cfg SHIFT 2               ; IN_RIGHT: LSB first
.cfg CLKDIV 50             ; 1 us ticks at 50 MHz; only has to be much faster than the device

start: WAIT PIN CLK, 1
       WAIT PIN CLK, 0         ; falling edge 1: start bit, not stored
       SET  X, 7
bit:   WAIT PIN CLK, 1
       WAIT PIN CLK, 0         ; falling edges 2..9: a data bit is valid
       IN   PIN DAT, 1
       JMP  X--, bit
       WAIT PIN CLK, 1
       WAIT PIN CLK, 0         ; falling edge 10: parity, not stored
       WAIT PIN CLK, 1
       WAIT PIN CLK, 0         ; falling edge 11: stop
       PUSH NOBLOCK
       JMP  start
