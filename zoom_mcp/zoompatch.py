"""Decode / encode G1X FOUR patches (PTCF format) and map raw values <-> human values."""
import json, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ZOOM_MCP_DATA", os.path.join(HERE, "data"))
NUM_PARAMS = 9          # max parameter fields stored per effect
WIDE_PARAMS = 5         # first fields are 12 bits, the rest 8 bits
PARAM_START = 30        # bit 0 = on/off, bits 1..28 = effect id, bit 29 = unused


def _widths():
    return [12 if i < WIDE_PARAMS else 8 for i in range(NUM_PARAMS)]


def load_catalog():
    """{effect id: entry} from data/effects.json, or {} if setup has not been run yet."""
    path = os.path.join(DATA_DIR, "effects.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cat = json.load(f)
    return {e["id"]: e for e in cat}


def load_templates():
    path = os.path.join(DATA_DIR, "templates.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {int(k): v for k, v in json.load(f).items()}


# ---------- value mapping ----------
def raw_to_value(p, raw):
    if "enum" in p:
        return p["enum"][raw] if raw < len(p["enum"]) else raw
    pre = p.get("prefix", [])
    if raw < len(pre):
        return pre[raw]
    step = p.get("step", 1)
    n = round((p["max"] - p["min"]) / step) + 1          # numeric positions
    k = raw - len(pre)
    if k >= n:
        suf = p.get("suffix", [])
        j = k - n
        return suf[j] if j < len(suf) else f"SYNC{j - len(suf)}"
    v = p["min"] + k * step
    return v if step != 1 else int(v)


def value_to_raw(p, value):
    if "enum" in p:
        opts = [str(o).upper() for o in p["enum"]]
        s = str(value).upper()
        if s in opts:
            return opts.index(s)
        raise ValueError(f"{p['name']}: '{value}' no es válido; opciones: {p['enum']}")
    pre = [str(x).upper() for x in p.get("prefix", [])]
    suf = [str(x).upper() for x in p.get("suffix", [])]
    s = str(value).upper().strip()
    step = p.get("step", 1)
    n = round((p["max"] - p["min"]) / step) + 1
    if s in pre:
        return pre.index(s)
    if s in suf and not (s.lstrip("-").isdigit() and p["min"] <= int(s) <= p["max"]):
        return len(pre) + n + suf.index(s)
    if s.startswith("SYNC") and s[4:].isdigit():
        return len(pre) + n + len(suf) + int(s[4:])
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{p['name']}: '{value}' no es válido (rango {describe_param(p)})")
    if not p["min"] <= v <= p["max"]:
        raise ValueError(f"{p['name']}: {value} fuera de rango {describe_param(p)}")
    return len(pre) + int(round((v - p["min"]) / step))


def describe_param(p):
    if "enum" in p:
        return " / ".join(map(str, p["enum"]))
    s = f"{p['min']}..{p['max']}" + (f" (pasos de {p['step']})" if p.get("step") else "")
    if p.get("prefix"):
        s = ", ".join(p["prefix"]) + ", " + s
    if p.get("suffix"):
        s += ", " + ", ".join(p["suffix"])
    return s


# ---------- binary patch ----------
class Patch:
    """Holds the raw PTCF bytes and edits them in place (keeps unknown fields intact)."""

    def __init__(self, data: bytes):
        if data[:4] != b"PTCF":
            raise ValueError("datos de patch inválidos (falta PTCF)")
        self.raw = bytearray(data)
        self.total_len = struct.unpack_from("<I", data, 4)[0]

    # PTCF header
    @property
    def num_effects(self):
        return struct.unpack_from("<I", self.raw, 12)[0]

    @property
    def name(self):
        return self.raw[0x1A:0x24].decode("latin1").rstrip(" \x00")

    @name.setter
    def name(self, s):
        s = "".join(c for c in s if 32 <= ord(c) < 127)[:10].ljust(10)
        self.raw[0x1A:0x24] = s.encode("latin1")

    def _chunk(self, tag):
        i = self.raw.find(tag, 0, self.total_len)
        if i < 0:
            raise ValueError(f"chunk {tag} no encontrado")
        ln = struct.unpack_from("<I", self.raw, i + 4)[0]
        return i + 8, ln

    def _edtb_entry(self, slot):
        off, ln = self._chunk(b"EDTB")
        if not 0 <= slot < ln // 24:
            raise IndexError("slot de efecto fuera de rango")
        return off + 24 * slot

    def _get_bits(self, slot):
        o = self._edtb_entry(slot)
        return int.from_bytes(self.raw[o:o + 24], "little")

    def _set_bits(self, slot, v):
        o = self._edtb_entry(slot)
        self.raw[o:o + 24] = v.to_bytes(24, "little")

    def effect(self, slot):
        v = self._get_bits(slot)
        params, pos = [], PARAM_START
        for w in _widths():
            params.append((v >> pos) & ((1 << w) - 1))
            pos += w
        return {"on": bool(v & 1), "id": (v >> 1) & 0xFFFFFFF, "raw_params": params}

    def set_effect(self, slot, eid, on, raw_params):
        v = (1 if on else 0) | ((eid & 0xFFFFFFF) << 1)
        pos = PARAM_START
        for w, val in zip(_widths(), list(raw_params) + [0] * NUM_PARAMS):
            if val >= (1 << w):
                raise ValueError(f"valor {val} no cabe en {w} bits")
            v |= val << pos
            pos += w
        self._set_bits(slot, v)
        # PTCF keeps a copy of the effect ids right after the name
        struct.pack_into("<I", self.raw, 0x24 + 4 * slot, eid)

    def set_on(self, slot, on):
        v = self._get_bits(slot)
        self._set_bits(slot, (v & ~1) | (1 if on else 0))

    def _resize_chunk(self, tag, payload):
        off, ln = self._chunk(tag)
        size = len(self.raw)
        new = self.raw[:off - 4] + struct.pack("<I", len(payload)) + payload + self.raw[off + ln:self.total_len]
        if len(new) > size:
            raise ValueError("descripción demasiado larga para el patch")
        self.total_len = len(new)
        struct.pack_into("<I", new, 4, self.total_len)
        self.raw = bytearray(new) + bytearray(size - len(new))

    def set_description(self, text, max_len=120):
        """Set the description shown in Guitar Lab (English and Japanese chunks, ASCII)."""
        b = text.encode("ascii", "replace")[:max_len]
        payload = b + b"\x00" * (4 - len(b) % 4)    # NUL-terminated, 4-byte aligned like factory patches
        self._resize_chunk(b"TXJ1", payload)
        self._resize_chunk(b"TXE1", payload)

    def bytes(self):
        return bytes(self.raw)

    # ---------- human readable ----------
    def to_dict(self, catalog):
        fx = []
        for s in range(self.num_effects):
            e = self.effect(s)
            info = catalog.get(e["id"])
            d = {"slot": s + 1, "on": e["on"], "id": f"{e['id']:#010x}"}
            if e["id"] == 0:
                d["effect"] = "(vacío)"
            elif info:
                d["effect"] = info["name"]
                d["category"] = info["category"]
                d["params"] = {p["name"]: raw_to_value(p, r) for p, r in zip(info["params"], e["raw_params"])}
            else:
                d["effect"] = "(desconocido)"
                d["raw_params"] = e["raw_params"]
            fx.append(d)
        return {"name": self.name, "effects": fx}
