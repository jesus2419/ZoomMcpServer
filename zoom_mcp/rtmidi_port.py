"""MIDI port backed by python-rtmidi (macOS / Linux, optional on Windows).

Same interface as winmidi.MidiPort: send_sysex, send_short, receive, drain, close.
"""
import queue
import threading
import time

try:
    import rtmidi
except ImportError as e:  # pragma: no cover
    raise ImportError("Falta python-rtmidi: pip install python-rtmidi") from e


class MidiError(RuntimeError):
    pass


def list_inputs():
    m = rtmidi.MidiIn()
    try:
        return list(enumerate(m.get_ports()))
    finally:
        del m


def list_outputs():
    m = rtmidi.MidiOut()
    try:
        return list(enumerate(m.get_ports()))
    finally:
        del m


class MidiPort:
    def __init__(self, in_id, out_id):
        self.rx = queue.Queue()
        self._lock = threading.Lock()
        self._partial = bytearray()
        self._in = rtmidi.MidiIn(queue_size_limit=4096)
        self._out = rtmidi.MidiOut()
        try:
            self._in.open_port(in_id)
            self._out.open_port(out_id)
        except Exception as e:
            self.close()
            raise MidiError(f"No se pudo abrir el puerto MIDI: {e}") from e
        self._in.ignore_types(sysex=False, timing=True, active_sense=True)
        self._in.set_callback(self._callback)

    def _callback(self, event, data=None):
        msg, _delta = event
        if not msg:
            return
        # Some backends deliver long SysEx in several pieces.
        if msg[0] == 0xF0 or self._partial:
            self._partial += bytes(msg)
            if self._partial[-1] == 0xF7:
                self.rx.put(bytes(self._partial))
                self._partial = bytearray()

    def send_sysex(self, data: bytes):
        with self._lock:
            self._out.send_message(list(bytes(data)))
        time.sleep(0.002)

    def send_short(self, status, d1=0, d2=0):
        with self._lock:
            if 0xC0 <= status < 0xE0:
                self._out.send_message([status, d1])
            else:
                self._out.send_message([status, d1, d2])

    def drain(self):
        while True:
            try:
                self.rx.get_nowait()
            except queue.Empty:
                return

    def receive(self, timeout=1.0, match=None):
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                return None
            try:
                msg = self.rx.get(timeout=left)
            except queue.Empty:
                return None
            if match is None or match(msg):
                return msg

    def close(self):
        for p in (getattr(self, "_in", None), getattr(self, "_out", None)):
            if p is not None:
                try:
                    p.close_port()
                except Exception:
                    pass
