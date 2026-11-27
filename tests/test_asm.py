from pathlib import Path

import pytest

from mockingbird import asm, isa

PROGS = Path(__file__).resolve().parents[1] / "programs"


@pytest.mark.parametrize("name,length", [
    ("uart_tx", 8), ("uart_rx", 9), ("spi_master", 16), ("i2c_master", 31),
    ("spi_master_mode1", 16), ("spi_master_mode2", 16), ("spi_master_mode3", 16),
    ("jtag", 10), ("ps2_rx", 13),
])
def test_programs_assemble(name, length):
    prog = asm.assemble((PROGS / f"{name}.s").read_text())
    assert len(prog.words) == length
    assert all(0 <= w < 1 << 16 for w in prog.words)


def test_encodings():
    p = asm.assemble(
        ".pin TX 3\n"
        "l: SETP PIN TX, 1 [6]\n"
        "   JMP X--, l\n"
        "   OUT DIR 9, 1\n"
        "   MOV OSR, ~OSR\n"
        "   PULL NOBLOCK\n"
        "   IN NULL, 8\n"
        "   WAIT PIN 9, 1\n"
        "   SET Y, 0x7f\n"
        "   NOP [15]\n"
        "   JMP X!=Y, l\n"
        "   JMP !PIN, 0\n"
    )
    assert p.words == [
        isa.encode(isa.SETP, 6, (1 << 6) | 3),
        isa.encode(isa.JMP, 0, (isa.COND["X--"] << 5) | 0),
        isa.encode(isa.OUT, 0, (1 << 7) | (9 << 3) | 1),
        isa.encode(isa.MOV, 0, (3 << 5) | (1 << 3) | 3),
        isa.encode(isa.PULL, 0, 0),
        isa.encode(isa.IN, 0, 0x80),
        isa.encode(isa.WAIT, 0, (1 << 7) | 9),
        isa.encode(isa.SET, 0, (1 << 7) | 0x7F),
        isa.encode(isa.MOV, 15, (1 << 5) | 1),
        isa.encode(isa.JMP, 0, (isa.COND["X!=Y"] << 5) | 0),
        isa.encode(isa.JMP, 0, (isa.COND["!PIN"] << 5) | 0),
    ]
    assert p.pins == {"TX": 3}


@pytest.mark.parametrize("src", [
    "JMP nowhere", "SET X, 200", "SETP DIR 3, 1", "FOO", "SETP PIN 1, 1 [16]",
    "MOV PC, X", "IN PIN 1, 9", "WAIT DIR 9, 1", "PUSH X", ".cfg BOGUS 1",
    "l: NOP\nl: NOP", "\n".join(["NOP"] * 33),
])
def test_errors(src):
    with pytest.raises(asm.AsmError):
        asm.assemble(src)
