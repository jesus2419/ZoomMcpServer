"""Low-level SysEx access to Zoom G1 FOUR family pedals.

Model id, number of patches, patch size and bank size are read from the pedal itself.
"""
import binascii
import time

from midi import MidiPort, MidiError, find_zoom_ports, BACKEND  # noqa: F401

# Model ids whose protocol has been verified on real hardware.
VERIFIED_MODELS = {0x6E: "G1 FOUR / G1X FOUR"}


def unpack7(b):
    """Zoom 8-to-7 decoding: each group = 1 MSB byte (bit6 -> first byte) + 7 data bytes."""
    out = bytearray()
    for i in range(0, len(b), 8):
        g = b[i:i + 8]
        for j, x in enumerate(g[1:]):
            out.append(x | (0x80 if g[0] & (1 << (6 - j)) else 0))
    return bytes(out)


def pack7(b):
    out = bytearray()
    for i in range(0, len(b), 7):
        g = b[i:i + 7]
        hi = 0
        for j, x in enumerate(g):
            if x & 0x80:
                hi |= 1 << (6 - j)
        out.append(hi)
        out.extend(x & 0x7F for x in g)
    return bytes(out)


def _crc7(data):
    crc = binascii.crc32(data) ^ 0xFFFFFFFF
    return bytes([(crc >> (7 * i)) & 0x7F for i in range(5)])


class ZoomDevice:
    def __init__(self):
        in_id, out_id, self.port_name = find_zoom_ports()
        self.port = MidiPort(in_id, out_id)
        self.editing = False
        try:
            self._identify()
            self._query_layout()
        except Exception:
            self.port.close()
            raise

    # ---------------------------------------------------------- discovery
    def _identify(self):
        r = None
        for attempt in range(4):  # the first request after reopening the port is sometimes lost
            self.port.drain()
            self.port.send_sysex(bytes([0xF0, 0x7E, 0x00, 0x06, 0x01, 0xF7]))
            r = self.port.receive(1.0, match=lambda m: len(m) >= 14 and m[3:5] == b"\x06\x02")
            if r is not None:
                break
            time.sleep(0.2 * (attempt + 1))
        if r is None or r[5] != 0x52:
            raise MidiError("El dispositivo no respondió como una pedalera Zoom")
        self.model_id = r[6]
        self.firmware = bytes(r[10:14]).decode("ascii", "replace")
        self.model_name = VERIFIED_MODELS.get(self.model_id, f"Zoom modelo 0x{self.model_id:02X}")
        self.verified = self.model_id in VERIFIED_MODELS
        self.H = bytes([0xF0, 0x52, 0x00, self.model_id])

    def _query_layout(self):
        r = self.send([0x44], wait_cmd=0x43)
        if r is None or len(r) < 14:
            raise MidiError("La pedalera no informó su número de patches (comando 0x44)")
        w = lambda i: r[i] | (r[i + 1] << 7)
        self.num_patches = w(5)
        self.patch_size = w(7)
        self.bank_size = w(11) or 10

    def info(self):
        return {"model": self.model_name, "model_id": f"0x{self.model_id:02X}", "firmware": self.firmware,
                "verified_model": self.verified, "patches": self.num_patches, "bank_size": self.bank_size,
                "patch_size": self.patch_size, "midi_port": self.port_name, "midi_backend": BACKEND}

    # ---------------------------------------------------------- plumbing
    def close(self):
        try:
            if self.editing:
                self.edit_mode(False)
        finally:
            self.port.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def send(self, body, wait_cmd=None, timeout=2.0):
        self.port.drain()
        self.port.send_sysex(self.H + bytes(body) + b"\xF7")
        if wait_cmd is None:
            return None
        return self.port.receive(timeout, match=lambda m: len(m) > 5 and m[:4] == self.H and m[4] == wait_cmd)

    def ack(self, body, timeout=1.0):
        r = self.send(body, wait_cmd=0x00, timeout=timeout)
        return r[5:-1] if r else None

    def edit_mode(self, on=True):
        self.ack([0x50 if on else 0x51])
        self.editing = on

    def _addr(self, slot):
        if not 0 <= slot < self.num_patches:
            raise ValueError(f"slot debe estar entre 0 y {self.num_patches - 1}")
        return divmod(slot, self.bank_size)

    # ---------------------------------------------------------- edit buffer
    def read_current(self):
        if not self.editing:
            self.edit_mode(True)  # 0x29 is only answered in edit mode
        r = self.send([0x29], wait_cmd=0x28)
        if r is None:
            raise MidiError("La pedalera no respondió a la lectura del patch actual")
        return unpack7(r[5:-1])[:self.patch_size]

    def write_current(self, data):
        if not self.editing:
            self.edit_mode(True)
        self.port.send_sysex(self.H + b"\x28" + pack7(data) + b"\xF7")

    # ---------------------------------------------------------- memory
    def read_slot(self, slot):
        """Return (patch bytes, raw sysex message)."""
        bank, prog = self._addr(slot)
        r = self.send([0x09, 0x00, bank, prog, 0x00], wait_cmd=0x08)
        if r is None:
            raise MidiError(f"Sin respuesta al leer el slot {slot}")
        n = r[8] | (r[9] << 7)
        return unpack7(r[10:-6])[:n], r

    def write_slot(self, slot, data):
        bank, prog = self._addr(slot)
        n = len(data)
        msg = (self.H + bytes([0x08, 0x00, bank, prog, n & 0x7F, n >> 7]) + pack7(data) + _crc7(data) + b"\xF7")
        self.port.drain()
        self.port.send_sysex(msg)
        r = self.port.receive(3.0, match=lambda m: len(m) >= 7 and m[:4] == self.H and m[4] == 0x00)
        if r is None or r[5] != 0x00:
            raise MidiError(f"La pedalera rechazó la escritura (respuesta: {r.hex(' ') if r else 'ninguna'})")

    def program_change(self, slot):
        bank, prog = self._addr(slot)
        self.port.send_short(0xB0, 0x00, 0)      # bank MSB
        self.port.send_short(0xB0, 0x20, bank)   # bank LSB
        self.port.send_short(0xC0, prog)
