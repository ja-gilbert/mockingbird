"""WS2812B addressable LED decoder working from per-clock samples of the data
line. It enforces the datasheet's pulse widths, so it is also the timing check
for a program. Like uart.py, nothing here knows about model.py."""

T0H, T1H = (250, 550), (650, 950)      # ns high for a 0 and for a 1: 0.40 and 0.80 us, +-0.15
T0L, T1L = (700, 1000), (300, 600)     # ns low after a 0 and after a 1: 0.85 and 0.45 us, +-0.15
RESET = 50_000                         # ns: a low at least this long ends the frame


def decode(samples, clock_hz):
    """-> [[byte, ...], ...], one list per frame; frames are separated by a reset
    gap. Bits arrive MSB first. Raises ValueError for a pulse or a gap outside
    the datasheet limits and for a frame that is not a whole number of bytes."""
    ns = 1e9 / clock_hz
    runs = []                                          # [level, clocks] run lengths
    for level in samples:
        if runs and runs[-1][0] == level:
            runs[-1][1] += 1
        else:
            runs.append([level, 1])
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
