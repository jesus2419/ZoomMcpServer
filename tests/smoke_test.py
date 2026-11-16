"""Device test of the server functions.

    python tests/smoke_test.py            # read-only checks
    python tests/smoke_test.py --write 49 # also create/edit a patch in slot 49, then restore it
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "zoom_mcp"))
import server as S  # noqa: E402
from zoomdev import ZoomDevice  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--write", type=int, metavar="SLOT", help="slot donde probar la escritura (se restaura)")
args = ap.parse_args()

print(S.device_info())
print(S.read_patch(0)[:300], "...")

spec = [
    {"effect": "ZNR", "params": {"DETCT": "GTRIN", "Depth": 100, "THRSH": 25}},
    {"effect": "TS Drive", "params": {"Gain": 35, "Tone": 60, "VOL": 70, "Boost": "OFF"}},
    {"effect": "MS 800", "params": {"Input": "HI", "Bass": 55, "MID": 60, "Treble": 65, "Gain": 70, "VOL": 60}},
    {"effect": "MS4x12", "params": {"MIC": "ON"}},
    {"effect": "Delay", "params": {"Time": 380, "F.B": 25, "Mix": 20}},
]
with ZoomDevice() as z:
    cur = z.read_current()
p = S._build(cur, "Test", spec, "Smoke test")  # offline encode
v = p.to_dict(S.CATALOG)
assert v["effects"][1]["params"]["Gain"] == 35 and v["effects"][4]["params"]["Time"] == 380, v
print("encode/decode OK")

if args.write is not None:
    slot = args.write
    with ZoomDevice() as z:
        z.edit_mode(True)
        orig, _ = z.read_slot(slot)
    try:
        S.create_patch(slot, "MCP Test", spec, "Smoke test")
        S.update_patch(slot, effect_slot=2, params={"Gain": 50})
        r = json.loads(S.read_patch(slot))
        assert r["name"] == "MCP Test" and r["effects"][1]["params"]["Gain"] == 50, r
        print("write/read OK")
    finally:
        with ZoomDevice() as z:
            z.edit_mode(True)
            z.write_slot(slot, orig)
        print(f"slot {slot} restaurado")
