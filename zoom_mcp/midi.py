"""Pick a MIDI backend: native winmm on Windows (no dependencies), python-rtmidi elsewhere.

Set ZOOM_MIDI_BACKEND=rtmidi to force python-rtmidi on Windows.
"""
import os
import sys

if sys.platform == "win32" and os.environ.get("ZOOM_MIDI_BACKEND", "").lower() != "rtmidi":
    from winmidi import list_inputs, list_outputs, MidiPort, MidiError  # noqa: F401
    BACKEND = "winmm"
else:
    from rtmidi_port import list_inputs, list_outputs, MidiPort, MidiError  # noqa: F401
    BACKEND = "rtmidi"

PORT_HINT = os.environ.get("ZOOM_MIDI_PORT", "ZOOM")


def find_zoom_ports():
    """Return (in_id, out_id, name) of the first port whose name contains PORT_HINT."""
    hint = PORT_HINT.upper()
    ins = [(i, n) for i, n in list_inputs() if hint in n.upper()]
    outs = [(i, n) for i, n in list_outputs() if hint in n.upper()]
    if not ins or not outs:
        all_ports = [n for _, n in list_inputs()]
        raise MidiError(
            "No se encontró la pedalera Zoom. Revisa el cable USB y cierra Zoom Guitar Lab "
            f"(solo un programa puede usar el puerto). Puertos MIDI vistos: {all_ports or 'ninguno'}")
    return ins[0][0], outs[0][0], ins[0][1]
