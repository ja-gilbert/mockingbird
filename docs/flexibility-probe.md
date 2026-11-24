# Flexibility probe of the version 0 chip

Started 2026-11-23. The question: which protocols on the competition page fit
the chip as it is, and where does it fall short? Nothing under `src/` changed
for this probe and it proposes no version 1 design. It only records what fits,
what does not, and why.

Rows come from the competition page: the three required protocols at the
settings it suggests (common UART baud rates, SPI modes 0 to 3, I2C at 100
and 400 kHz), its stretch goals (low-speed USB, 10 Mbit Ethernet) and the
others it names (JTAG, SWD, PS/2, CAN). Four more rows were already planned:
WS2812, 1-Wire, SPI target and I2C read. The planned Manchester row became
the 10 Mbit Ethernet row.

Each row is judged against the whole chip, not only the instruction set.
"Program and paced test" means a program in `programs/` and a test in
`tests/test_probe.py` that runs it in the Python model with the host limited
to the real port's rate. "Paper" means an assessment with reasons, not run.

## What the chip gives

| Resource | Version 0 |
|---|---|
| Clock | 50 MHz, the rate the design was hardened at. The page says the demo board can supply 60 MHz; that has not been hardened. |
| Engines | 1. Nothing runs concurrently. |
| Program | 32 words, 9 instructions, no subroutines |
| Data path | 8-bit X, Y, ISR, OSR |
| Timing | one instruction per tick, tick = CLKDIV clocks, 0 to 15 extra ticks per instruction |
| Inputs | seen 2 clocks late (synchronizer) |
| FIFOs | 4 bytes each way |
| Host port | one byte per 24-bit frame, one direction per frame. A frame is 196 clocks at the fastest timing the spec allows (4 CS setup + 23 x 8 SCK + 4 CS hold + 4 CS high). |
| Host byte rate | 255 kB/s one way at 50 MHz, 128 kB/s each way when both directions are busy. 306 and 153 kB/s at 60 MHz. |

`model.Host` enforces the host numbers in the tests: a byte moves only every
196 clocks, accepted or refused at the same point in the frame as in
`src/host_port.v`.

## Results

| # | Protocol and setting | Verdict | Evidence |
|---|---|---|---|
| 1 | UART, 9600 to 230400 baud | Fits | program and paced test |
| 2 | UART, 460800 and 921600 baud | Fits after the delay fields are retimed | paced test at 921600 |
| 3 | SPI controller, modes 0 to 3 | Fits | four programs, paced loopback test per mode |
| 4 | I2C controller write, 100 and 400 kHz | Fits | bus-timing test against the specification minimums |
| 5 | I2C read with repeated START | Does not fit in one program | paper |
| 6 | SPI target | Fits awkwardly | paper |
| 7 | JTAG | Fits, as a host-driven bit pump | program and paced test |
| 8 | SWD | Fits awkwardly, as a host-driven bit pump | paper |
| 9 | PS/2, device to host | Fits, without the parity check | program and paced test |
| 10 | PS/2, host to device | Expected to fit | paper |
| 11 | CAN | Does not fit as a bus node | paper |
| 12 | Low-speed USB | Does not fit | paper |
| 13 | 10 Mbit Ethernet | Does not fit | paper |
| 14 | WS2812 LEDs | Pending | decoder and paced test ready; the program is being written by hand |
| 15 | 1-Wire | Expected to fit, tight on program memory | paper |

What each row needs from the chip:

| # | Bytes per second, TX / RX | Empty TX FIFO | Full RX FIFO | Integer divider at 50 MHz | At 60 MHz |
|---|---|---|---|---|---|
| 1 | up to 23 k / 23 k | any length: the line idles | not tolerated: the sender does not wait. 4 bytes of slack, then drop with RX_OVF | yes, within 0.47 % | yes, within 1.36 % |
| 2 | 46 k and 92 k each way | as row 1 | as row 1 | no at the shipped 8 ticks per bit (-3.1 %); yes at 9 ticks (+0.47 %) | yes at 8 ticks, but +1.73 % |
| 3 | host-limited: 128 k each way | any length: the controller owns the clock | any length: a blocking PUSH pauses the clock | no fixed rate. SCK up to clock / 6 = 8.33 MHz | 10 MHz; 153 k each way |
| 4 | 11 k at 100 kHz, 44 k at 400 kHz, TX only | any length: SCL is held low | not used | CLKDIV 46 gives 98.8 kHz, CLKDIV 12 gives 378.8 kHz | CLKDIV 55 gives 99.2 kHz, CLKDIV 14 gives 389.6 kHz |
| 5 | as row 4, both ways | any length | any length | as row 4 | as row 4 |
| 6 | SCK / 8 each way: 125 k at 1 MHz | not tolerated: the controller does not wait | not tolerated | no divider: it follows SCK. Sustained SCK up to about 1 MHz (host rate); bursts of 4 bytes faster | about 1.2 MHz sustained |
| 7 | host-limited: 64 k each way (510 kbit/s) | any length: TCK stops | any length | no fixed rate. TCK up to 10 MHz | 12 MHz; 612 kbit/s |
| 8 | as row 7 | any length | any length | no fixed rate | same |
| 9 | 0 / up to 1.5 k | not used | 4 bytes of slack, then drop with RX_OVF. The program does not hold the device off | not needed: the device clocks | same |
| 10 | up to 1.5 k / 0 | any length before a frame | not used | not needed | same |
| 11 | up to 125 k each way at 1 Mbit/s | not tolerated inside a frame | not tolerated | exact: 50 clocks per bit at 1 Mbit/s, 400 at 125 kbit/s | exact: 60 and 480 |
| 12 | 188 k per line; 375 k if the host encodes both lines | not tolerated inside a packet | not tolerated | 33 clocks per bit is +1.0 %, inside the 1.5 % device tolerance | 40 clocks per bit, exact |
| 13 | 1.25 M / 1.25 M | not tolerated inside a frame of 72 to 1526 bytes | not tolerated | no: half a bit is 2.5 clocks | yes: 3 clocks per half bit |
| 14 | 100 k / 0 | not tolerated inside a frame by the datasheet: low time at most 1.0 us, and 50 us latches the LEDs | not used | yes: 40 or 60 ns ticks fit the 150 ns windows | yes: 50 ns ticks give the nominal times exactly |
| 15 | about 2 k / 2 k | any length between bits | any length: the master sets the pace | yes: 1 us ticks, exact | yes |

## Notes per row

**1 and 2, UART.** The shipped programs spend 8 ticks on a bit, so the baud
rate is clock / (8 x CLKDIV). At 50 MHz that lands within 0.47 % up to
230400 baud and misses 460800 and 921600 by 3.1 %, more than the roughly 2 %
a UART link tolerates on each side. Changing three delay fields in the
transmitter and two in the receiver gives 9 ticks per bit, and CLKDIV 6 then
gives 925926 baud, +0.47 %. The test sends and receives 32 bytes back to
back that way with the host paced; nothing is lost at 92 kB/s. So the rate
is a property of the program and CLKDIV together, not one host setting. At
60 MHz the 8-tick programs stay inside 2 % at every rate, but only just at
the top two. Sustained reception is bounded by the host: one pop per 196
clocks is 2.55 Mbaud at 50 MHz.

**3, SPI controller.** One program per mode, 16 words each. The programs
differ only in the idle level of SCK and the order of four instructions.
Each mode passes a loopback test whose decoder checks the idle level and the
sampling edge for that mode. The pins can run at 8.33 MHz, about 1 MB/s. The
host cannot: a byte out and a byte back cost two frames, 392 clocks, so a
full-duplex transfer runs at 128 kB/s and the engine waits with SCK idle in
between. The test measures that. A device with a clock timeout would object.

**4, I2C controller write.** The SCL cycle is 12 ticks for a data bit and 11
for the ACK bit, so the divider has to be chosen for 11. With CLKDIV 46 the
fastest cycle is 98.8 kHz and with CLKDIV 12 it is 378.8 kHz. The test
measures tLOW, tHIGH, START hold, STOP setup and data setup on the bus and
compares each with the I2C specification minimum for that mode. All pass at
both clocks. The first divider choice assumed 12 ticks everywhere and ran the
ACK clock at 108 kHz; the test caught it. The bus in the model has ideal
edges. A real rise time makes the bus slower, never faster, because the
program waits to see SCL high.

**5, I2C read with repeated START.** The write program is 31 of 32 words. A
read needs its own bit loop, an ACK it drives itself and a second START.
That does not fit beside the write in one program. One thing might rescue
it: pins keep their state while the engine is stopped and cleared, so the
host could hold the bus, load a read program and continue. Loading 31 words
takes about 6,100 clocks, 122 us, and I2C has no timeout. Not tried.

**6, SPI target.** A program can wait for SCK edges, shift MOSI in and shift
MISO out. Three limits. The controller never waits, so sustained traffic is
capped by the host at about 128 kB/s each way, roughly 1 MHz SCK; faster
bursts fit only while they are 4 bytes or less. The engine reacts to a
falling SCK edge about four clocks later (2 synchronizer, 1 tick, 1 output
register), which limits SCK to roughly 5 MHz before MISO misses its setup
time. And WAIT watches one pin, so the program cannot notice the controller
releasing CS in the middle of a byte.

**7, JTAG.** `programs/jtag.s`, 10 words. OUT writes two pins at once, so
each host byte carries four TDI and TMS pairs and each byte back carries
four TDO samples. The test shifts 16 bits through a one-bit BYPASS register
model and gets them back one TCK late. The host runs the TAP state machine.
TCK can reach 10 MHz; the host limits the average to 510 kbit/s.

**8, SWD.** The same pump idea should work: the clock is the host's and can
stop at any time. The data pin changes direction inside a packet, parity has
to be computed by the host, and the 3-bit acknowledge is checked by the host
between packets. Expected to need 15 to 20 words. Not tried.

**9 and 10, PS/2.** `programs/ps2_rx.s`, 13 words, waits for each falling
clock edge from the device and reads a bit. The test sends three scan codes
at 12.5 kHz and receives them. Two shortfalls: the parity bit is skipped,
because the engine cannot compute parity, and a lost clock edge leaves the
program out of step with no timeout to recover. Host to device needs both
lines as open-drain outputs and about 20 words. Not tried.

**11, CAN.** The bit rates divide exactly and the byte rate is within the
host's reach. The protocol is what does not fit. A node must stuff bits,
compute a 15-bit CRC, stop within one bit when it loses arbitration, and
acknowledge a frame one bit after its CRC, before the host could even have
read the last byte. None of that can be done by the engine today, and the
host is too slow to do the acknowledge. Listen-only capture of the raw bit
stream, with the host unstuffing and checking afterwards, looks possible at
low bit rates.

**12, Low-speed USB.** The bit rate works (33 clocks per bit, +1.0 %; exact
at 60 MHz). The rest does not. NRZI coding, bit stuffing and CRC cannot be
done in the engine, and the page asks for exactly that work to be on the
chip. If the host encodes both data lines instead, it must deliver 375 kB/s
without a gap, more than the port's 255 kB/s. A device must answer a token
within a few bit times and the host gives up after 18, which is 600 clocks:
too short for the host to read the token and push a reply. And receiving
needs clock recovery on every edge.

**13, 10 Mbit Ethernet.** At 50 MHz a half bit is 2.5 clocks, so the
Manchester waveform cannot be made at all. At 60 MHz it is 3 clocks and the
pins could do it. The data cannot get there: a frame is at least 72 bytes
with no gap at 1.25 MB/s, against 4-byte FIFOs and a 0.3 MB/s host port. The
engine also cannot Manchester-encode, having no operation on a data bit.
What does fit on paper is the link pulse: 100 ns every 16 ms is 5 clocks and
a counted wait.

**14, WS2812.** The test and decoder are in place and skip until
`programs/ws2812.s` exists. The decoder enforces the datasheet windows on
every pulse and every gap, including the gap at a byte boundary. The host
supplies a byte per 196 clocks against a need of one per 500, so the FIFO
does not run dry inside a frame.

**15, 1-Wire.** Open-drain through the direction bit, as in the I2C program.
A reset is 480 us low, 30 passes of a 16-tick loop at 1 us ticks. Reset with
presence detect, write byte, read byte and a dispatch on a command byte come
to an estimated 26 to 30 words. Not tried.

## Gap list

Ranked by how many rows each one blocks or hurts.

| Gap | What the probe saw | Rows |
|---|---|---|
| A. Host throughput and FIFO depth | One byte per 196 clocks, one direction per frame, 4 bytes of buffer | blocks 13 and 12; caps 3, 6 and 7 well below what the pins can do |
| B. No operation on a data bit | OUT can only put OSR bits on pins or directions. No test, invert or XOR, so no line coding, stuffing, parity or CRC in the engine | 11, 12, 13; parity in 8 and 9 |
| C. 32 words, no subroutines | The I2C write alone is 31 words | blocks 5; 15 is tight; 11 and 12 are far over |
| D. WAIT watches one pin and never times out | A missing or misbehaving device parks the engine until the host clears it | 6, 9, 10, 15; a stuck clock stretch in 4 |
| E. One engine | UART transmit and receive cannot run together | every row; the page counts concurrency as a plus |
| F. Bit rate is CLKDIV times ticks per bit | A new rate can mean editing the program's delay fields, not just CLKDIV | 2; 13 at 50 MHz |
| G. Reaction time of about four clocks | 2 synchronizer, 1 tick, 1 output register | 6, 12 |
| H. RX_OVF clears only with a full engine clear | Found while fixing the UART receiver: clearing restarts the program and empties both FIFOs | 1, 2, 9 |
| I. 8-bit data path | Frames that are not a multiple of 8 bits are packed and unpacked by the host | 7, 8, 9 |

What worked in the chip's favour: the delay field made retiming a bit rate a
matter of editing numbers; OUT to a pin group made JTAG's two outputs one
instruction; OUT to a direction bit made open-drain buses natural; pins that
keep their state across a clear leave room for swapping programs mid-task.

## Also on the competition page

The page says running protocols concurrently and supporting both controller
and target roles are a plus. Concurrency is gap E. For roles: UART is
symmetric, the SPI target is row 6, and an I2C target was not assessed.

## Limits of this probe

- Model only. The model matches the RTL clock for clock in the engine unit
  tests, but pads are not modelled. Tiny Tapeout estimates about 10 ns round
  trip through pads and mux, unmeasured.
- The I2C bus has ideal edges and the SPI and JTAG loopbacks have no wire
  delay.
- Every 60 MHz figure assumes the design closes timing at 60 MHz. Only 50 MHz
  has been hardened.
- Paper rows are estimates. A row is not settled until a program runs.

## Rerun

```
.venv/bin/python -m pytest tests/test_probe.py tests/test_ws2812.py -q
```
