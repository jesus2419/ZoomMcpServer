"""Read-only access to files in the pedal's flash (protocol from mungewell/zoom-zt2)."""
import binascii
from zoomdev import unpack7


def _tx(z, body, t=1.5):
    z.port.drain()
    z.port.send_sysex(z.H + bytes(body) + b"\xF7")
    return z.port.receive(t)


def list_files(z, pattern="*"):
    names = []
    r = _tx(z, [0x60, 0x25, 0x00, 0x00] + list(pattern.encode()) + [0x00])
    while r and len(r) > 15 and r[5] == 0x04:
        nm = bytes(r[15:]).split(b"\x00")[0].decode("latin1")
        if not nm or nm in names:
            break
        names.append(nm)
        r = _tx(z, [0x60, 0x26, 0x00, 0x00] + list(pattern.encode()) + [0x00])
    _tx(z, [0x60, 0x27])
    return names


def read_file(z, name, max_chunks=None):
    _tx(z, [0x60, 0x20, 0x02] + [0x00] * 9 + list(name.encode()) + [0x00])
    data = b""
    try:
        is_data = lambda m: len(m) > 12 and m[5] == 0x04 and m[6] == 0x22 and m[7] == 0x01
        while True:
            _tx(z, [0x60, 0x05, 0x00])
            z.port.drain()
            z.port.send_sysex(z.H + bytes([0x60, 0x22, 0x14, 0x2F, 0x60, 0x00, 0x0C, 0x00, 0x04, 0x00, 0x00, 0x00]) + b"\xF7")
            z.port.receive(1.0)  # short ack
            z.port.send_sysex(z.H + bytes([0x60, 0x05, 0x00]) + b"\xF7")
            pk = z.port.receive(2.0, match=is_data)
            if pk is None:
                raise RuntimeError("sin respuesta leyendo " + name)
            d = pk[1:-1]  # strip F0/F7 -> same indexing as mido .data
            length = d[9] * 128 + d[8]
            if length == 0:
                break
            block = unpack7(d[10:10 + length + length // 7 + 1])[:length]
            c = d[-5:]
            crc = c[0] | (c[1] << 7) | (c[2] << 14) | (c[3] << 21) | (c[4] << 28)
            if (crc ^ 0xFFFFFFFF) != binascii.crc32(block):
                raise RuntimeError("checksum error en " + name)
            data += block
            if length < 512 or (max_chunks and len(data) >= 512 * max_chunks):
                break
    finally:
        _tx(z, [0x60, 0x21, 0x40, 0x00, 0x00, 0x00, 0x00])
        _tx(z, [0x60, 0x09])
    return data
