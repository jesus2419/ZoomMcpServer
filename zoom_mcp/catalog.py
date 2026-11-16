"""Build the effect catalog for the connected pedal.

1. Read the header of every .ZD2 effect file on the pedal  -> effect id, name, category
2. Read parameter names/ranges from Zoom's official FX-list PDF (downloaded, never redistributed)
3. Apply hand-verified corrections (overrides.py)
4. Harvest real raw values per effect from the user's own patches (defaults + hidden fields)
"""
import io
import json
import os
import re
import struct
import urllib.request

from zfiles import list_files, read_file, _tx
from zoompatch import Patch, raw_to_value, DATA_DIR
from overrides import OVERRIDES, CABINET_PARAMS, SKIP_EFFECTS

FXLIST_URL = "https://zoomcorp.com/documents/44/E_G1FOUR_FX-list.pdf"
CATS = {1: "DYNAMICS", 2: "FILTER", 3: "DRIVE", 4: "AMP", 5: "CABINET", 6: "MODULATION",
        7: "SFX", 8: "DELAY", 9: "REVERB", 0xB: "PEDAL"}


def data_path(name):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


# ------------------------------------------------------------------ 1. pedal effect files
def read_effect_headers(z, progress=print):
    _tx(z, [0x52])  # PC mode
    out = []
    try:
        files = [f for f in list_files(z) if f.upper().endswith(".ZD2")]
        for k, fn in enumerate(files, 1):
            d = read_file(z, fn, max_chunks=1)
            eid = struct.unpack_from("<I", d, 0x60)[0]
            name = d[0x64:0x70].split(b"\x00")[0].decode("latin1").strip()
            out.append({"file": fn, "id": eid, "name": name})
            progress(f"  [{k}/{len(files)}] {eid:#010x} {name}")
    finally:
        _tx(z, [0x53])
    return out


# ------------------------------------------------------------------ 2. official FX list
def download_fxlist_text(url=FXLIST_URL):
    try:
        import pypdf  # needs 'cryptography' too: the PDF is AES-encrypted (no password)
    except ImportError as e:
        raise RuntimeError("Falta pypdf: pip install pypdf cryptography") from e
    req = urllib.request.Request(url, headers={"User-Agent": "zoom-mcp-setup"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pdf = r.read()
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def _parse_range(s):
    s = s.strip().rstrip("P♪ ").strip()
    m = re.search(r"((?:[A-Za-z0-9.:+#/-]+,\s*)*)(-?\d+)\s*-\s*(-?\d+)$", s)
    if m:
        pre = [x.strip() for x in m.group(1).split(",") if x.strip()]
        rng = {"min": int(m.group(2)), "max": int(m.group(3))}
        if pre:
            rng["prefix"] = pre
        return rng, s[:m.start()].strip()
    m = re.search(r"((?:[A-Za-z0-9.:+#/'-]+,\s*)+[A-Za-z0-9.:+#/'-]+)$", s)
    if m:
        return {"enum": [x.strip() for x in m.group(1).split(",")]}, s[:m.start()].strip()
    return None, s


def parse_fxlist(text, names):
    """Return {effect name: {"desc": str, "params": [...]}} for the given effect names."""
    text = text.replace("–", "-").replace("—", "-")
    lines = [l.replace("★", "").strip() for l in text.splitlines()]
    lines = [l for l in lines if l and not l.startswith("Effect Types and Parameters")
             and not re.fullmatch(r"\d+ \d+", l) and not l.startswith("[ ")]
    names = sorted(names, key=len, reverse=True)

    def header(l):
        return next((n for n in names if l == n or l.startswith(n + " ")), None)

    found, cur, i = {}, None, 0
    while i < len(lines):
        l = lines[i]
        h = header(l)
        if h and h not in found:
            cur = {"desc": l[len(h):].strip(), "params": []}
            found[h] = cur
        elif cur is not None:
            while l.endswith(",") and i + 1 < len(lines):  # enum lists that wrap
                i += 1
                l = l + " " + lines[i]
            rng, rest = _parse_range(l)
            if not rng and cur["params"]:
                cur = None  # header of an effect that is not installed
            elif rng:
                pname = "F.B" if rest.startswith("F. B") else (rest.split(" ")[0] if rest else "?")
                cur["params"].append({"name": pname, **rng})
        i += 1
    return found


# ------------------------------------------------------------------ 3. catalog
def build_catalog(headers, parsed, templates):
    out = []
    for h in headers:
        if h["name"] in SKIP_EFFECTS:
            continue
        cat = CATS.get(h["id"] >> 24, "OTHER")
        info = parsed.get(h["name"], {})
        params, source = info.get("params"), "manual"
        if cat == "CABINET":
            params, source = CABINET_PARAMS, "verificado"
        if h["name"] in OVERRIDES:
            params, source = OVERRIDES[h["name"]], "verificado"
        if not params:
            # Unknown effect: expose raw fields so it can still be edited.
            n = max(1, sum(1 for v in templates.get(str(h["id"]), []) if v)) if str(h["id"]) in templates else 4
            params = [{"name": f"P{k + 1}", "min": 0, "max": 255} for k in range(n)]
            source = "desconocido"
        out.append({"id": h["id"], "id_hex": f"{h['id']:#010x}", "name": h["name"], "category": cat,
                    "file": h["file"], "description": info.get("desc", ""), "params": params,
                    "params_source": source})
    return out


# ------------------------------------------------------------------ 4. templates + validation
def iter_backup_patches(backup):
    from zoomdev import unpack7
    for k in sorted(backup["patches"], key=int):
        raw = bytes.fromhex(backup["patches"][k])
        yield int(k), Patch(unpack7(raw[10:-6])[:raw[8] | raw[9] << 7])


def build_templates(backup):
    tpl = {}
    for _, p in iter_backup_patches(backup):
        for s in range(p.num_effects):
            e = p.effect(s)
            if e["id"] and str(e["id"]) not in tpl:
                tpl[str(e["id"])] = e["raw_params"]
    return tpl


def validate(backup, catalog_list):
    """Decode every patch; return (fields checked, problems list, unknown ids)."""
    cat = {e["id"]: e for e in catalog_list}
    problems, unknown, total = [], set(), 0
    for slot, p in iter_backup_patches(backup):
        for s in range(p.num_effects):
            e = p.effect(s)
            if not e["id"]:
                continue
            info = cat.get(e["id"])
            if not info:
                unknown.add(f"{e['id']:#010x}")
                continue
            for i, r in enumerate(e["raw_params"]):
                total += 1
                if i < len(info["params"]):
                    pr = info["params"][i]
                    v = raw_to_value(pr, r)
                    if ("enum" in pr and isinstance(v, int)) or (isinstance(v, str) and v.startswith("SYNC") and int(v[4:]) > 30):
                        problems.append(f"patch {slot} {p.name}: {info['name']}.{pr['name']} raw={r}")
                elif r and not (info["category"] == "AMP" and i == 7):
                    problems.append(f"patch {slot} {p.name}: {info['name']} campo extra {i}={r}")
    return total, problems, sorted(unknown)


def full_backups(backup_dir):
    """Full-pedal backup files, oldest first ('all-<stamp>.json'; 'g1xfour-' is the legacy name)."""
    if not os.path.isdir(backup_dir):
        return []
    fs = [f for f in os.listdir(backup_dir) if f.startswith(("all-", "g1xfour-")) and f.endswith(".json")]
    return [os.path.join(backup_dir, f) for f in sorted(fs, key=lambda f: f.split("-", 1)[1])]


def save_json(name, obj):
    with open(data_path(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
