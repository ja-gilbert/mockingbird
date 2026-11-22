; SPI master, mode 0, MSB first, 6 ticks per bit.
; Host pushes (byte count - 1), then the bytes. Every byte sent pushes one
; received byte to the RX FIFO.
.pin MISO 0                ; input space
.pin CS   2                ; output space
.pin SCK  3
.pin MOSI 4
.cfg SHIFT 0
.cfg CLKDIV 1

init:  SETP PIN CS, 1
       SETP PIN SCK, 0
frame: PULL
       MOV  Y, OSR             ; Y = bytes - 1
       SETP PIN CS, 0 [2]
byte:  PULL
       SET  X, 7
bit:   OUT  PIN MOSI, 1        ; data while SCK low
       SETP PIN SCK, 1 [1]     ; rising edge, 3 ticks high
       IN   PIN MISO, 1        ; sample during high
       SETP PIN SCK, 0         ; falling edge
       JMP  X--, bit           ; 3 ticks low
       PUSH                    ; received byte
       JMP  Y--, byte
       SETP PIN CS, 1 [2]
       JMP  frame
