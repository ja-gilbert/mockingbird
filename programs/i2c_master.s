; I2C master, write transaction, clock stretching, about 90 kHz at 1 us ticks.
; SDA and SCL are bidirectional pads: level held 0, direction 1 drives low,
; direction 0 releases to the pull-up. Host pushes (byte count - 1), then
; the address byte and data bytes. On NACK the program pushes 0xFF to the
; RX FIFO and stops; the host then issues CLR to flush what is left.
.pin SDA 8
.pin SCL 9
.cfg SHIFT 0
.cfg JMPPIN 8
.cfg CLKDIV 50

init:  SETP PIN SDA, 0         ; levels stay 0 forever
       SETP PIN SCL, 0
       SETP DIR SDA, 0         ; both released
       SETP DIR SCL, 0
frame: PULL
       MOV  Y, OSR             ; Y = bytes - 1
       SETP DIR SDA, 1 [4]     ; START: SDA low while SCL high
       SETP DIR SCL, 1 [1]
byte:  PULL
       MOV  OSR, ~OSR          ; 1 -> release, 0 -> drive low
       SET  X, 7
bit:   OUT  DIR SDA, 1 [3]     ; data while SCL low
       SETP DIR SCL, 0         ; release SCL
       WAIT PIN SCL, 1 [4]     ; clock stretch: go on only when SCL is high
       SETP DIR SCL, 1         ; SCL low
       JMP  X--, bit
       SETP DIR SDA, 0 [3]     ; release SDA for ACK
       SETP DIR SCL, 0
       WAIT PIN SCL, 1 [1]
       JMP  PIN, nack [1]      ; SDA high during SCL high = NACK
       SETP DIR SCL, 1
       JMP  Y--, byte
stop:  SETP DIR SDA, 1 [3]     ; SDA low while SCL low
       SETP DIR SCL, 0
       WAIT PIN SCL, 1 [3]
       SETP DIR SDA, 0 [4]     ; SDA rises while SCL high = STOP, then bus free
       JMP  frame
nack:  SETP DIR SCL, 1
       MOV  ISR, ~NULL         ; 0xFF marker
       PUSH
       JMP  stop
