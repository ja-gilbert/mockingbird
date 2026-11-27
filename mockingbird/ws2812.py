"""WS2812B addressable LED decoder working from per-clock samples of the data
line. It enforces the datasheet's pulse widths, so it is also the timing check
for a program. Like uart.py, nothing here knows about model.py."""

T0H, T1H = (250, 550), (650, 950)      # ns high for a 0 and for a 1: 0.40 and 0.80 us, +-0.15
T0L, T1L = (700, 1000), (300, 600)     # ns low after a 0 and after a 1: 0.85 and 0.45 us, +-0.15
RESET = 50_000                         # ns: a low at least this long ends the frame


def _runs(samples):
    """Run lengths of a per-clock trace: [[level, clocks], ...]."""
    out = []
    for level in samples:
        if out and out[-1][0] == level:
            out[-1][1] += 1
        else:
            out.append([level, 1])
    return out


def margins(samples, clock_hz):
    """-> {"T0H": ns, "T1H": ns, "T0L": ns, "T1L": ns}: how far the least
    comfortable pulse or gap of each kind sits inside its datasheet window.
    Zero is exactly on a limit and negative is outside it. A kind that never
    occurs is left out. The low that ends a frame is not a gap and is not
    counted. decode() says whether a trace is legal; this says by how much."""
    ns = 1e9 / clock_hz
    runs, worst, bit = _runs(samples), {}, None
    for k, (level, n) in enumerate(runs):
        t = n * ns
        if level:
            bit = int(t >= (T0H[1] + T1H[0]) / 2)      # the nearer window says which bit it was
            kind, limit = f"T{bit}H", T1H if bit else T0H
        elif bit is None or t >= RESET or k == len(runs) - 1:
            continue                                   # idle, a reset, or the end of the trace
        else:
            kind, limit = f"T{bit}L", T1L if bit else T0L
        worst[kind] = min(worst.get(kind, float("inf")), t - limit[0], limit[1] - t)
    return worst


def decode(samples, clock_hz):
    """-> [[byte, ...], ...], one list per frame; frames are separated by a reset
    gap. Bits arrive MSB first. Raises ValueError for a pulse or a gap outside
    the datasheet limits and for a frame that is not a whole number of bytes."""
    ns = 1e9 / clock_hz
    runs = _runs(samples)
    if runs and runs[0][0]:
        raise ValueError("the line must idle low before the first bit")
    frames, bits, at = [], [], 0

    def within(t, lo_hi):
        return lo_hi[0] - 1e-6 <= t <= lo_hi[1] + 1e-6

    for k, (level, n) in enumerate(runs):
        t = n * ns
        if level:
            if within(t, T0H):
                bits.append(0)
            elif within(t, T1H):
                bits.append(1)
            else:
                raise ValueError(f"high for {t:.0f} ns at clock {at}: neither a 0 {T0H} nor a 1 {T1H}")
        elif bits:
            last = k == len(runs) - 1                  # the trace ended while the line was low
            if t >= RESET or last:
                if len(bits) % 8:
                    raise ValueError(f"frame of {len(bits)} bits ends at clock {at}")
                frames.append([sum(b << (7 - j) for j, b in enumerate(bits[i:i + 8]))
                               for i in range(0, len(bits), 8)])
                bits = []
            else:
                limit = T1L if bits[-1] else T0L
                if not within(t, limit):
                    raise ValueError(f"low for {t:.0f} ns after a {bits[-1]} at clock {at}: allowed {limit}")
        at += n
    if bits:
        raise ValueError("the trace ends in the middle of a bit")
    return frames
