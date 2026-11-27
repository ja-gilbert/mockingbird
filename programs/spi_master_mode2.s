; SPI master, mode 2 (CPOL 1, CPHA 0), MSB first, 6 ticks per bit.
; Same host protocol as spi_master.s (mode 0): the host pushes (byte count - 1),
; then the bytes. Every byte sent pushes one received byte to the RX FIFO.
.pin MISO 0                ; input space
.pin CS   2                ; output space
.pin SCK  3
.pin MOSI 4
.cfg SHIFT 0
.cfg CLKDIV 1

init:  SETP PIN CS, 1
       SETP PIN SCK, 1         ; clock idles high
frame: PULL
       MOV  Y, OSR             ; Y = bytes - 1
       SETP PIN CS, 0 [2]
byte:  PULL
       SET  X, 7
bit:   OUT  PIN MOSI, 1        ; data while SCK idles
       SETP PIN SCK, 0 [1]     ; leading edge: both sides sample
       IN   PIN MISO, 1
       SETP PIN SCK, 1         ; trailing edge: the device changes its data
       JMP  X--, bit
       PUSH                    ; received byte
       JMP  Y--, byte
       SETP PIN CS, 1 [2]
       JMP  frame
