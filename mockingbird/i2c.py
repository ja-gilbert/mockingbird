"""I2C pieces working from per-clock samples of the SDA and SCL lines: a decoder,
and an open-drain bus with an optional target device for tests. Like uart.py,
nothing here knows about model.py."""


def _byte(bits):
    return sum(b << (7 - k) for k, b in enumerate(bits))


def decode(sda, scl):
    """-> [[(byte, acked), ...], ...], one list per START..STOP transaction (a
    repeated START also ends one). SDA is sampled at each SCL rising edge, MSB
    first; every ninth bit is the ACK (low = acked). Raises on a partial byte."""
    out, bits, fresh = [], None, False

    def close(i):
        if len(bits) % 9:
            raise ValueError(f"transaction ends after {len(bits)} bits at clock {i}")
        if bits:
            out.append([(_byte(bits[n:n + 8]), not bits[n + 8]) for n in range(0, len(bits), 9)])

    for i in range(1, len(sda)):
        if not scl[i]:
            fresh = False
        elif not scl[i - 1]:                           # SCL rose: a data bit, unless...
            if bits is not None:
                bits.append(sda[i])
                fresh = True
        elif sda[i] != sda[i - 1]:                     # ...SDA moves while SCL stays high
            if fresh:
                bits.pop()                             # that rise set up this START or STOP
                fresh = False
            if bits is not None:
                close(i)
            bits = None if sda[i] else []              # rising = STOP, falling = START
    return out


class Target:
    """Minimal I2C target (the slave device) for tests. It ACKs a write to its
    7-bit address and every data byte after it, collecting those in .data. With
    stretch > 0 it also holds SCL low for that many clocks after each ACK, which
    is clock stretching."""

    def __init__(self, addr, stretch=0):
        self.addr, self.stretch, self.data = addr, stretch, []
        self._sda = self._scl = 1
        self._bits = None          # bits of the current byte; None = not addressed
        self._nbytes = 0
        self._ack = False          # pulling SDA low
        self._hold = 0             # clocks left pulling SCL low

    def step(self, sda, scl):
        """One clock: bus levels in -> (pull_sda_low, pull_scl_low) for the next clock."""
        psda, pscl, self._sda, self._scl = self._sda, self._scl, sda, scl
        if self._hold:
            self._hold -= 1
        if scl and pscl and sda != psda:               # START (SDA fell) or STOP (SDA rose)
            self._bits = None if sda else []
            self._nbytes, self._ack = 0, False
        elif self._bits is not None and scl and not pscl:
            if len(self._bits) < 8:                    # SCL rose: a data bit (not the ACK clock)
                self._bits.append(sda)
        elif self._bits is not None and pscl and not scl:
            if self._ack:                              # SCL fell after the ACK clock
                self._ack, self._bits = False, []
                self._hold = self.stretch
            elif len(self._bits) == 8:                 # SCL fell after the eighth data bit
                byte = _byte(self._bits)
                if self._nbytes == 0 and byte != self.addr << 1:
                    self._bits = None                  # another address, or a read: stay silent
                else:
                    if self._nbytes:
                        self.data.append(byte)
                    self._nbytes += 1
                    self._ack = True
        return self._ack, self._hold > 0


class Bus:
    """Open-drain SDA and SCL with pull-ups and an optional Target. Call clock()
    once per core clock with what the controller drives low; the resolved line
    levels are returned and appended to .sda and .scl."""

    def __init__(self, target=None):
        self.target, self.sda, self.scl = target, [], []
        self._pull = (False, False)

    def clock(self, sda_low, scl_low):
        sda = int(not (sda_low or self._pull[0]))
        scl = int(not (scl_low or self._pull[1]))
        self.sda.append(sda)
        self.scl.append(scl)
        if self.target:
            self._pull = self.target.step(sda, scl)
        return sda, scl
