"""Two-pass assembler for ISA v0. Syntax: docs/isa-v0.md, "Assembler syntax".

    python -m mockingbird.asm programs/uart_tx.s        # listing
    python -m mockingbird.asm --hex programs/uart_tx.s  # one word per line
"""
import re
import sys
from dataclasses import dataclass, field

from . import isa


class AsmError(Exception):
    pass


@dataclass
class Program:
    words: list
    cfg: dict = field(default_factory=dict)     # register name -> value, from .cfg
    pins: dict = field(default_factory=dict)    # pin name -> index, from .pin
    labels: dict = field(default_factory=dict)
    listing: list = field(default_factory=list)  # (addr, word, source line)


_LABEL = re.compile(r"^(\w+):\s*(.*)$")
_INSTR = re.compile(r"^(\w+)\s*(.*?)\s*(?:\[\s*(\d+)\s*\])?$")


def _num(s):
    try:
        return int(s, 0)
    except ValueError:
        raise AsmError(f"bad number {s!r}") from None


def _need(ok, msg):
    if not ok:
        raise AsmError(msg)


def assemble(text, depth=isa.DEPTH):
    pins, cfg, labels, items = {}, {}, {}, []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = _LABEL.match(line)
        if m:
            _need(m.group(1) not in labels, f"line {lineno}: duplicate label {m.group(1)}")
            labels[m.group(1)] = len(items)
            line = m.group(2).strip()
            if not line:
                continue
        if line.startswith("."):
            d, *rest = line.split()
            if d == ".pin" and len(rest) == 2:
                pins[rest[0]] = _num(rest[1])
            elif d == ".cfg" and len(rest) == 2 and rest[0].upper() in isa.CFG:
                cfg[rest[0].upper()] = _num(rest[1])
            elif d == ".word" and len(rest) == 1:      # raw word, for testing encodings
                items.append((lineno, raw.strip(), ".word", [rest[0]], 0))
            else:
                raise AsmError(f"line {lineno}: bad directive {line!r}")
            continue
        m = _INSTR.match(line)
        _need(m is not None, f"line {lineno}: cannot parse {line!r}")
        ops = [o.strip() for o in m.group(2).split(",")] if m.group(2) else []
        delay = int(m.group(3) or 0)
        _need(delay <= 15, f"line {lineno}: delay {delay} > 15")
        items.append((lineno, raw.strip(), m.group(1).upper(), ops, delay))
    _need(len(items) <= depth, f"program has {len(items)} words, memory holds {depth}")

    words, listing = [], []
    for addr, (lineno, src, mnem, ops, delay) in enumerate(items):
        try:
            if mnem == ".word":
                w = _num(ops[0])
                _need(0 <= w < 1 << 16, f"word {w:#x} does not fit 16 bits")
            else:
                op, arg = _encode(mnem, ops, addr, labels, pins)
                w = isa.encode(op, delay, arg)
        except AsmError as e:
            raise AsmError(f"line {lineno}: {e}") from None
        words.append(w)
        listing.append((addr, w, src))
    return Program(words, cfg, pins, labels, listing)


def _pin(tok, pins, allow_dir=True):
    """'PIN name' or 'DIR name' -> (is_dir, index)."""
    parts = tok.split()
    _need(len(parts) == 2 and parts[0].upper() in ("PIN", "DIR"),
          f"expected 'PIN name' or 'DIR name', got {tok!r}")
    is_dir = parts[0].upper() == "DIR"
    idx = pins[parts[1]] if parts[1] in pins else _num(parts[1])
    _need(0 <= idx < isa.NPINS, f"pin index {idx} out of range")
    _need(allow_dir or not is_dir, "DIR is not valid here")
    _need(not is_dir or idx >= 8, f"pin {idx} has no direction (only 8..15 do)")
    return is_dir, idx


def _count(s):
    n = _num(s)
    _need(1 <= n <= 8, f"bit count {n} not in 1..8")
    return isa.cnt_field(n)


def _encode(mnem, ops, addr, labels, pins):
    n = len(ops)
    if mnem == "NOP":
        mnem, ops, n = "MOV", ["Y", "Y"], 2
    if mnem == "JMP":
        _need(n in (1, 2), "JMP takes [cond,] target")
        cond = ops[0].upper().replace(" ", "") if n == 2 else ""
        _need(cond in isa.COND and (n == 1 or cond), f"bad condition {ops[0]!r}")
        tgt = ops[-1]
        target = labels[tgt] if tgt in labels else _num(tgt)
        _need(target >> 5 == addr >> 5, f"target {tgt!r} is outside this 32-word page")
        return isa.JMP, (isa.COND[cond] << 5) | (target & 31)
    if mnem == "WAIT":
        _need(n == 2, "WAIT takes PIN name, polarity")
        _, idx = _pin(ops[0], pins, allow_dir=False)
        pol = _num(ops[1])
        _need(pol in (0, 1), "polarity must be 0 or 1")
        return isa.WAIT, (pol << 7) | idx
    if mnem == "IN":
        _need(n == 2, "IN takes PIN name|NULL, count")
        if ops[0].upper() == "NULL":
            return isa.IN, 0x80 | _count(ops[1])
        _, idx = _pin(ops[0], pins, allow_dir=False)
        return isa.IN, (idx << 3) | _count(ops[1])
    if mnem == "OUT":
        _need(n == 2, "OUT takes PIN|DIR name, count")
        is_dir, idx = _pin(ops[0], pins)
        return isa.OUT, (is_dir << 7) | (idx << 3) | _count(ops[1])
    if mnem in ("PUSH", "PULL"):
        _need(n == 0 or (n == 1 and ops[0].upper() == "NOBLOCK"), f"{mnem} takes nothing or NOBLOCK")
        return (isa.PUSH if mnem == "PUSH" else isa.PULL), (0 if n else 1) << 7
    if mnem == "MOV":
        _need(n == 2, "MOV takes dst, [~|::]src")
        dst, src, mop = ops[0].upper(), ops[1].upper().replace(" ", ""), ""
        for p in ("::", "~"):
            if src.startswith(p):
                mop, src = p, src[len(p):]
        _need(dst in isa.REG and src in isa.REG, f"bad MOV register in {ops}")
        _need("PC" not in (dst, src), "MOV PC is reserved for v1")
        return isa.MOV, (isa.REG[dst] << 5) | (isa.MOVOP[mop] << 3) | isa.REG[src]
    if mnem == "SET":
        _need(n == 2 and ops[0].upper() in ("X", "Y"), "SET takes X|Y, imm")
        imm = _num(ops[1])
        _need(0 <= imm <= 127, f"immediate {imm} not in 0..127")
        return isa.SET, ((ops[0].upper() == "Y") << 7) | imm
    if mnem == "SETP":
        _need(n == 2, "SETP takes PIN|DIR name, 0|1")
        is_dir, idx = _pin(ops[0], pins)
        v = _num(ops[1])
        _need(v in (0, 1), "value must be 0 or 1")
        return isa.SETP, (is_dir << 7) | (v << 6) | idx
    raise AsmError(f"unknown mnemonic {mnem}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    hexonly = "--hex" in argv
    for path in [a for a in argv if not a.startswith("--")]:
        with open(path) as f:
            prog = assemble(f.read())
        for addr, w, src in prog.listing:
            print(f"{w:04x}" if hexonly else f"{addr:2d}: {w:04x}  {src}")
        if not hexonly and prog.cfg:
            print("cfg:", prog.cfg)


if __name__ == "__main__":
    main()
