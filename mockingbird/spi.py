"""SPI mode 0 decoder working from per-clock samples of CS, SCK, MOSI and MISO.
Like uart.py it knows nothing about model.py, so the RTL and the model are both
checked against the protocol, not only against each other."""


def decode(cs, sck, mosi, miso):
    """-> [(mosi_bytes, miso_bytes), ...], one pair per CS-low frame. Both data
    lines are sampled at each SCK rising edge, MSB first. Raises on a partial byte."""
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
            bits = []
        elif bits is not None and sck[i] and not sck[i - 1]:
            bits.append((mosi[i], miso[i]))
    return frames
