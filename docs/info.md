<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

Mockingbird is a small reprogrammable protocol engine. A host loads a short
program over SPI, and the engine then drives and samples the pins with
clock-exact timing. A new protocol is a new program, not new hardware. The
programs in `programs/` make the same chip a UART transmitter, a UART
receiver, an SPI master and an I2C master with clock stretching.

**Blocks**

- **Host port.** A fixed SPI slave (mode 0, 24-bit frames) on `ui[5..7]` and
  `uo[7]`. It loads programs, writes configuration, pushes bytes for the
  engine to send, pops bytes the engine received, and returns a status byte
  in every frame.
- **Engine.** Executes one 16-bit instruction per tick. A tick is the clock
  divided by a 16-bit CLKDIV. State: a 5-bit program counter, two 8-bit
  scratch registers X and Y, an output shift register OSR and an input shift
  register ISR.
- **Program memory.** 32 words of 16 bits, written by the host.
- **FIFOs.** Four bytes each way between host and engine.
- **Pin registers.** The engine reads all 16 inputs through two-flop
  synchronizers. It writes output levels on `uo[0..6]` and `uio[0..7]`, and
  the direction of each `uio` pin. Open-drain signalling, as I2C needs, is
  level 0 with the direction bit toggled.

**Instructions.** Every instruction is `op[4] delay[4] arg[8]`. The delay
field adds 0 to 15 idle ticks after the instruction, which is how a program
sets bit times without spending extra words.

| Instruction | What it does |
|---|---|
| `JMP cond, label` | Jump always, on X or Y zero, on X or Y nonzero with decrement, on X != Y, or on an input pin |
| `WAIT PIN p, level` | Stall until an input pin has that level |
| `IN PIN p, n` | Shift n pins into ISR |
| `OUT PIN/DIR p, n` | Shift n bits of OSR onto pin levels or pin directions |
| `PUSH` | ISR to the RX FIFO for the host |
| `PULL` | Next host byte from the TX FIFO into OSR |
| `MOV dst, src` | Copy between X, Y, ISR and OSR, optionally inverted or bit-reversed |
| `SET X/Y, n` | Load a constant |
| `SETP PIN/DIR p, v` | Set one pin level or direction |

Only three things stall the engine: a WAIT whose pin is not there yet, a
PULL with nothing to send, and a PUSH with the RX FIFO full. Everything else
takes exactly one tick, so a program's timing can be counted by hand. The
full specification is `docs/isa-v0.md` in the repository.

## How to test

Give the chip a 50 MHz clock and pulse `rst_n` low. Connect an SPI master as
the host: CS on `ui[5]`, SCK on `ui[6]`, MOSI on `ui[7]`, MISO on `uo[7]`.
Use mode 0, MSB first, with an SCK period of at least 8 chip clocks.

Each frame is 24 bits: `cmd[3] engine[2] reg[3] data[16]`. The reply is the
ID byte `0x4D`, a status byte and the byte at the head of the RX FIFO.

**Check the link.** Send `000000`. The reply is `4D 10 00`: the ID, a status
of "TX FIFO empty", and no received data.

**Send a UART byte.** These frames load `programs/uart_tx.s`, queue the byte
`0x55` and start the engine. The byte leaves on `uo[0]` as 8N1 at 115200
baud.

| Frame | Meaning |
|---|---|
| `450000` | load pointer = 0 |
| `208040 205080 208600 207007 203001 200644 208540 200001` | the eight program words |
| `430001` | shift direction: LSB first |
| `400036` | CLKDIV = 54, eight ticks per bit |
| `410002` | clear the engine |
| `600055` | push the byte `0x55` |
| `410001` | run |

A later `000000` frame replies `4D 1C 00`: running, waiting for the next
byte, TX FIFO empty. Push more bytes at any time. A push is accepted when
the status byte in its own reply has bit 1 (TX full) clear.

**Other protocols.** Assemble any program in `programs/` with
`python -m mockingbird.asm --hex programs/<name>.s` and load its words the
same way. `uart_rx.s` receives on `ui[1]`; pop received bytes with frame
`800000`, valid when status bit 0 is set. `spi_master.s` uses `uo[2..4]` for
CS, SCK and MOSI and `ui[0]` for MISO. `i2c_master.s` uses `uio[0]` for SDA
and `uio[1]` for SCL.

**Simulation.** `cd test && make` runs every protocol above through the host
port in cocotb and checks the pins against a clock-accurate Python model and
against independent protocol decoders.

## External hardware

- An SPI master to act as the host: a microcontroller or a USB to SPI adapter.
- For I2C: pull-up resistors on SDA and SCL, as on any I2C bus.
- Optional, to see the protocols work: a USB to UART adapter, an SPI or I2C
  device, a logic analyzer.
