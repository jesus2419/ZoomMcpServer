"""Parameter definitions verified by hand (against pedal data and the effect binaries)
for effects whose entry in the official FX list does not parse cleanly."""


def R(name, lo, hi, prefix=None, suffix=None, step=None):
    d = {"name": name, "min": lo, "max": hi}
    if prefix:
        d["prefix"] = prefix
    if suffix:
        d["suffix"] = suffix
    if step:
        d["step"] = step
    return d


def E(name, *vals):
    return {"name": name, "enum": list(vals)}


def HALF_DB(name):  # -12..12 dB in 0.5 dB steps (GetString_offset_minus12_05 in the effect code)
    return R(name, -12, 12, step=0.5)


FREQS = ["20", "25", "32", "40", "50", "63", "80", "100", "125", "160", "200", "250", "320", "400", "500", "630",
         "800", "1.0k", "1.2k", "1.6k", "2.0k", "2.5k", "3.2k", "4.0k", "5.0k", "6.3k", "8.0k", "10k", "12k", "16k", "20k"]
QS = [f"{x / 10:.1f}" for x in range(5, 51)] + [f"{x / 2:.1f}" for x in range(11, 33)]

CABINET_PARAMS = [E("MIC", "OFF", "ON"), R("D57:D421", 0, 100), R("Hi", 0, 100), R("Lo", 0, 100)]

SKIP_EFFECTS = {"Output VP"}  # global output level, not a patch effect

OVERRIDES = {
    "ParaEQ": [E("FREQ", *FREQS), E("Q", *QS), HALF_DB("Gain"), R("VOL", 0, 100)],
    "Gt GEQ 7": [HALF_DB(n) for n in ("100", "200", "400", "800", "1.6k", "3.2k", "6.4k")] + [R("VOL", 0, 100)],
    "Gt GEQ": [HALF_DB(n) for n in ("160", "400", "800", "3.2k", "6.4k", "12k")] + [R("VOL", 0, 100)],
    "Phaser": [E("Color", "4 STG", "8 STG", "INV 4", "INV 8"), R("Depth", 0, 100), R("Rate", 1, 50), R("RESO", 0, 100)],
    "Resonance": [E("Mode", "DOWN", "UP"), R("Sense", 1, 10), R("RESO", 0, 10), R("VOL", 0, 100)],
    "CloneCho": [E("Depth", "1", "2"), R("Rate", 0, 100), R("Tone", 0, 100), R("Mix", 0, 100)],
    "HPS": [E("Scale", "-6", "-5", "-4", "-3", "-m", "m", "3", "4", "5", "6"),
            E("Key", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"),
            R("Tone", 0, 10), R("Mix", 0, 100)],
    "PDL Pitch": [R("Bend", 0, 100), R("Color", 1, 9), R("Tone", 0, 10), E("Mode", "UP", "DOWN")],
    "MATCH30": [R("Gain1", 0, 100, prefix=["OFF"]), R("Bass1", 0, 100), R("TRBL1", 0, 100),
                R("Gain2", 0, 100, prefix=["OFF"]), R("Tone2", 0, 5), R("Cut", 0, 100), R("VOL", 0, 100, suffix=["OFF"])],
    "PitchSHFT": [R("Shift", -12, 12, suffix=["24"]), R("Fine", -25, 25), R("Tone", 0, 10), R("BAL", 0, 100)],
    "MonoPitch": [R("Shift", -12, 12, suffix=["24"]), R("Fine", -25, 25), R("Tone", 0, 10), R("BAL", 0, 100)],
    "ZNR": [E("DETCT", "GTRIN", "EFXIN"), R("Depth", 0, 100), R("THRSH", 0, 100), R("Decay", 0, 100)],
    "MS 1959": [R("Bass", 0, 100), R("MID", 0, 100), R("Treble", 0, 100), R("PRSNC", 0, 100),
                R("Input1", 0, 100, prefix=["OFF"]), R("Input2", 0, 100, prefix=["OFF"]), R("VOL", 0, 100)],
    "BG MK1": [R("Bass", 0, 100), R("MID", 0, 100), R("Treble", 0, 100), R("PRSNC", 0, 100),
               R("Gain1", 0, 100), R("Gain2", 0, 100), R("VOL", 0, 100)],
}
