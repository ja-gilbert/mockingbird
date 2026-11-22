"""8N1 UART decoder working from a per-clock sampled waveform. Deliberately
independent of model.py so the RTL and the model are both checked against
the protocol, not only against each other."""


def decode(samples, clocks_per_bit):
    """-> list of bytes found in samples (0/1 per clock). Raises on a bad stop bit."""
    out, i, n = [], 1, len(samples)
    while True:
        while i < n and not (samples[i - 1] and not samples[i]):   # falling edge = start
            i += 1
        mid = i + clocks_per_bit // 2
        if mid + 9 * clocks_per_bit >= n:
            return out
        if samples[mid]:
            raise ValueError(f"start bit vanished at clock {i}")
        val = 0
        for b in range(8):
            val |= samples[mid + (b + 1) * clocks_per_bit] << b
        if not samples[mid + 9 * clocks_per_bit]:
            raise ValueError(f"framing error for frame starting at clock {i}")
        out.append(val)
        i = mid + 9 * clocks_per_bit


def waveform(byte, clocks_per_bit, idle_before=0, idle_after=0, stop=1):
    """Per-clock samples of one 8N1 frame, LSB first. stop=0 forges a framing error."""
    bits = [0] + [(byte >> b) & 1 for b in range(8)] + [stop]
    body = [b for bit in bits for b in [bit] * clocks_per_bit]
    return [1] * idle_before + body + [1] * idle_after
