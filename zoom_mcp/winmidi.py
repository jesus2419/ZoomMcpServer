"""Minimal Windows MIDI (winmm.dll) access via ctypes - no native dependencies.

Supports short messages and SysEx in both directions.
"""
import ctypes
import ctypes.wintypes as wt
import queue
import threading
import time

winmm = ctypes.WinDLL("winmm")

MAXPNAMELEN = 32
CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
MHDR_DONE = 0x00000001


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
        ("szPname", wt.WCHAR * MAXPNAMELEN), ("wTechnology", wt.WORD),
        ("wVoices", wt.WORD), ("wNotes", wt.WORD), ("wChannelMask", wt.WORD),
        ("dwSupport", wt.DWORD),
    ]


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
        ("szPname", wt.WCHAR * MAXPNAMELEN), ("dwSupport", wt.DWORD),
    ]


class MIDIHDR(ctypes.Structure):
    pass


MIDIHDR._fields_ = [
    ("lpData", ctypes.c_void_p), ("dwBufferLength", wt.DWORD),
    ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.c_size_t),
    ("dwFlags", wt.DWORD), ("lpNext", ctypes.POINTER(MIDIHDR)),
    ("reserved", ctypes.c_size_t), ("dwOffset", wt.DWORD),
    ("dwReserved", ctypes.c_size_t * 8),
]

MIDIINPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.UINT, ctypes.c_size_t,
                                ctypes.c_size_t, ctypes.c_size_t)

HMIDI = wt.HANDLE
for fn, args in {
    "midiOutGetNumDevs": [], "midiInGetNumDevs": [],
    "midiOutGetDevCapsW": [ctypes.c_size_t, ctypes.c_void_p, wt.UINT],
    "midiInGetDevCapsW": [ctypes.c_size_t, ctypes.c_void_p, wt.UINT],
    "midiOutOpen": [ctypes.POINTER(HMIDI), wt.UINT, ctypes.c_size_t, ctypes.c_size_t, wt.DWORD],
    "midiInOpen": [ctypes.POINTER(HMIDI), wt.UINT, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD],
    "midiOutClose": [HMIDI], "midiInClose": [HMIDI],
    "midiOutShortMsg": [HMIDI, wt.DWORD],
    "midiOutPrepareHeader": [HMIDI, ctypes.POINTER(MIDIHDR), wt.UINT],
    "midiOutUnprepareHeader": [HMIDI, ctypes.POINTER(MIDIHDR), wt.UINT],
    "midiOutLongMsg": [HMIDI, ctypes.POINTER(MIDIHDR), wt.UINT],
    "midiInPrepareHeader": [HMIDI, ctypes.POINTER(MIDIHDR), wt.UINT],
    "midiInUnprepareHeader": [HMIDI, ctypes.POINTER(MIDIHDR), wt.UINT],
    "midiInAddBuffer": [HMIDI, ctypes.POINTER(MIDIHDR), wt.UINT],
    "midiInStart": [HMIDI], "midiInStop": [HMIDI], "midiInReset": [HMIDI],
}.items():
    f = getattr(winmm, fn)
    f.argtypes = args
    f.restype = wt.UINT


class MidiError(RuntimeError):
    pass


def _check(rc, what):
    if rc != 0:
        raise MidiError(f"{what} failed (MMRESULT={rc})")


def list_outputs():
    out = []
    for i in range(winmm.midiOutGetNumDevs()):
        caps = MIDIOUTCAPSW()
        if winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            out.append((i, caps.szPname))
    return out


def list_inputs():
    out = []
    for i in range(winmm.midiInGetNumDevs()):
        caps = MIDIINCAPSW()
        if winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            out.append((i, caps.szPname))
    return out


class MidiPort:
    """Paired input+output port. Incoming SysEx messages are queued."""

    NBUF = 32
    BUFSIZE = 65536

    def __init__(self, in_id, out_id):
        self.rx = queue.Queue()
        self._lock = threading.Lock()
        self._hout = HMIDI()
        self._hin = HMIDI()
        self._done = queue.Queue()
        self._cb = MIDIINPROC(self._callback)
        _check(winmm.midiOutOpen(ctypes.byref(self._hout), out_id, 0, 0, 0), "midiOutOpen")
        try:
            _check(winmm.midiInOpen(ctypes.byref(self._hin), in_id,
                                    ctypes.cast(self._cb, ctypes.c_void_p).value,
                                    0, CALLBACK_FUNCTION), "midiInOpen")
        except Exception:
            winmm.midiOutClose(self._hout)
            raise
        self._bufs = []
        self._hdrs = []
        for _ in range(self.NBUF):
            buf = ctypes.create_string_buffer(self.BUFSIZE)
            hdr = MIDIHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = self.BUFSIZE
            _check(winmm.midiInPrepareHeader(self._hin, ctypes.byref(hdr), ctypes.sizeof(hdr)), "midiInPrepareHeader")
            _check(winmm.midiInAddBuffer(self._hin, ctypes.byref(hdr), ctypes.sizeof(hdr)), "midiInAddBuffer")
            self._bufs.append(buf)
            self._hdrs.append(hdr)
        self._partial = bytearray()
        self._running = True
        self._worker = threading.Thread(target=self._recycle, daemon=True)
        self._worker.start()
        _check(winmm.midiInStart(self._hin), "midiInStart")

    # Called on a winmm thread: do as little as possible.
    def _callback(self, hin, msg, inst, p1, p2):
        if msg == MIM_LONGDATA:
            self._done.put(p1)

    def _recycle(self):
        while self._running:
            try:
                addr = self._done.get(timeout=0.2)
            except queue.Empty:
                continue
            hdr = MIDIHDR.from_address(addr)
            n = hdr.dwBytesRecorded
            if n:
                data = ctypes.string_at(hdr.lpData, n)
                self._partial += data
                if self._partial and self._partial[-1] == 0xF7:
                    self.rx.put(bytes(self._partial))
                    self._partial = bytearray()
            if self._running:
                hdr.dwFlags &= ~MHDR_DONE
                winmm.midiInAddBuffer(self._hin, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def send_sysex(self, data: bytes):
        data = bytes(data)
        with self._lock:
            buf = ctypes.create_string_buffer(data, len(data))
            hdr = MIDIHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = len(data)
            hdr.dwBytesRecorded = len(data)
            _check(winmm.midiOutPrepareHeader(self._hout, ctypes.byref(hdr), ctypes.sizeof(hdr)), "midiOutPrepareHeader")
            _check(winmm.midiOutLongMsg(self._hout, ctypes.byref(hdr), ctypes.sizeof(hdr)), "midiOutLongMsg")
            t0 = time.time()
            while not (hdr.dwFlags & MHDR_DONE):
                if time.time() - t0 > 5:
                    raise MidiError("SysEx send timeout")
                time.sleep(0.001)
            winmm.midiOutUnprepareHeader(self._hout, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def send_short(self, status, d1=0, d2=0):
        with self._lock:
            _check(winmm.midiOutShortMsg(self._hout, status | (d1 << 8) | (d2 << 16)), "midiOutShortMsg")

    def drain(self):
        while True:
            try:
                self.rx.get_nowait()
            except queue.Empty:
                return

    def receive(self, timeout=1.0, match=None):
        """Return next SysEx (optionally where match(msg) is True) or None."""
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
        self._running = False
        winmm.midiInStop(self._hin)
        winmm.midiInReset(self._hin)
        self._worker.join(timeout=1)
        for hdr in self._hdrs:
            winmm.midiInUnprepareHeader(self._hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.midiInClose(self._hin)
        winmm.midiOutClose(self._hout)
