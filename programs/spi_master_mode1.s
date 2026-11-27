; SPI master, mode 1 (CPOL 0, CPHA 1), MSB first, 6 ticks per bit.
; Same host protocol as spi_master.s (mode 0): the host pushes (byte count - 1),
; then the bytes. Every byte sent pushes one received byte to the RX FIFO.
.pin MISO 0                ; input space
.pin CS   2                ; output space
.pin SCK  3
.pin MOSI 4
.cfg SHIFT 0
.cfg CLKDIV 1

init:  SETP PIN CS, 1
       SETP PIN SCK, 0         ; clock idles low
frame: PULL
       MOV  Y, OSR             ; Y = bytes - 1
       SETP PIN CS, 0 [2]
byte:  PULL
       SET  X, 7
bit:   SETP PIN SCK, 1         ; leading edge: both sides change their data
       OUT  PIN MOSI, 1 [1]
       SETP PIN SCK, 0         ; trailing edge: both sides sample
       IN   PIN MISO, 1
       JMP  X--, bit
       PUSH                    ; received byte
       JMP  Y--, byte
       SETP PIN CS, 1 [2]
       JMP  frame
