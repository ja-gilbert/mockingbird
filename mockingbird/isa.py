"""ISA v0 encoding tables: the single source of truth for the assembler, the
reference model and the tests. Field layouts are in docs/isa-v0.md."""

WIDTH = 8
DEPTH = 32
FIFO_DEPTH = 4
NPINS = 16

# Opcodes, instr[15:12]
JMP, WAIT, IN, OUT, PUSH, PULL, MOV, SET, SETP = range(9)
OPNAME = ["JMP", "WAIT", "IN", "OUT", "PUSH", "PULL", "MOV", "SET", "SETP"]

# JMP conditions, arg[7:5]
COND = {"": 0, "!X": 1, "X--": 2, "!Y": 3, "Y--": 4, "X!=Y": 5, "PIN": 6, "!PIN": 7}

# MOV register codes (arg[7:5] dst, arg[2:0] src) and operations (arg[4:3])
REG = {"X": 0, "Y": 1, "ISR": 2, "OSR": 3, "NULL": 4, "PC": 5}
MOVOP = {"": 0, "~": 1, "::": 2}

# Config registers, host CFG command reg field
CFG = {"CLKDIV": 0, "CTRL": 1, "START": 2, "SHIFT": 3, "JMPPIN": 4, "PTR": 5}
CTRL_RUN = 1
CTRL_CLR = 2
SHIFT_OUT_RIGHT = 1
SHIFT_IN_RIGHT = 2

# Status byte bits
(ST_RX_VALID, ST_TX_FULL, ST_RUNNING, ST_STALLED,
 ST_TX_EMPTY, ST_RX_FULL, ST_RX_OVF) = [1 << i for i in range(7)]

# Host port
CMD_STATUS, CMD_PROG, CMD_CFG, CMD_PUSH, CMD_POP, CMD_PEEK = range(6)
HOST_ID = 0x4D
HOST_CS, HOST_SCK, HOST_MOSI = 5, 6, 7  # input-space indices
HOST_MISO = 7                           # output-space index


def encode(op, delay, arg):
    assert 0 <= op < 16 and 0 <= delay < 16 and 0 <= arg < 256
    return (op << 12) | (delay << 8) | arg


def decode(word):
    """-> (op, delay, arg)"""
    return word >> 12, (word >> 8) & 0xF, word & 0xFF


def cnt_field(n):
    """Shift count 1..8 -> 3-bit field; 8 encodes as 0."""
    assert 1 <= n <= 8
    return n & 7


def cnt_value(f):
    return 8 if f == 0 else f


def host_frame(cmd, eng, reg, data):
    """24-bit MOSI word for one host transaction."""
    return (cmd << 21) | (eng << 19) | (reg << 16) | (data & 0xFFFF)


def clkdiv_for(clock_hz, bit_rate, ticks_per_bit):
    """-> (CLKDIV, actual bit rate, error in percent) for the nearest integer
    divider, when a program spends ticks_per_bit engine ticks on each bit."""
    div = max(1, round(clock_hz / (bit_rate * ticks_per_bit)))
    actual = clock_hz / (div * ticks_per_bit)
    return div, actual, 100 * (actual / bit_rate - 1)
