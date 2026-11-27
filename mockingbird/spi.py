"""SPI mode 0 decoder working from per-clock samples of CS, SCK, MOSI and MISO.
Like uart.py it knows nothing about model.py, so the RTL and the model are both
checked against the protocol, not only against each other."""


def decode(cs, sck, mosi, miso, mode=0):
    """-> [(mosi_bytes, miso_bytes), ...], one pair per CS-low frame, MSB first.
    mode is the SPI mode 0..3 (CPOL = mode >> 1, CPHA = mode & 1): both data
    lines are sampled at the leading SCK edge when CPHA = 0 and at the trailing
    edge when CPHA = 1. Raises on a partial byte, and when SCK does not idle at
    the level the mode requires."""
    cpol = mode >> 1
    rising = cpol == (mode & 1)                        # modes 0 and 3 sample on the rising edge
    frames, bits = [], None
    for i in range(1, len(cs)):
        if cs[i]:
            if bits is not None:                       # CS rose: the frame is over
                if len(bits) % 8:
                    raise ValueError(f"{len(bits)} bits in the frame ending at clock {i}")
                frames.append(tuple(
                    [sum(b[line] << (7 - k) for k, b in enumerate(bits[n:n + 8]))
                     for n in range(0, len(bits), 8)] for line in (0, 1)))
                bits = None
        elif cs[i - 1]:                                # CS fell: a frame starts
            if sck[i] != cpol:
                raise ValueError(f"SCK is {sck[i]} when CS falls at clock {i}; mode {mode} idles at {cpol}")
            bits = []
        elif bits is not None and sck[i] != sck[i - 1] and bool(sck[i]) == rising:
            bits.append((mosi[i], miso[i]))
    return frames
