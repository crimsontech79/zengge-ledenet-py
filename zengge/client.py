"""Controller client: connection handling and the operations layered on it."""
from __future__ import annotations

import socket
import time
from typing import Iterable, List, Optional, Sequence

from . import protocol as p
from .protocol import Color, State, Timer

DEFAULT_PORT = 5577

# These controllers are 2.4 GHz and slow to accept; a 1 s timeout reports a
# perfectly healthy device as closed.
DEFAULT_TIMEOUT = 8.0

#: Per-pixel frames render cleanly up to about this rate on a ~180-pixel strand.
#: There is NO backpressure signal -- see docs/PROTOCOL.md. Faster senders are
#: silently dropped while every send reports success.
SAFE_PIXEL_HZ = 5.0


class ZenggeError(Exception):
    pass


class Controller:
    """A single LED controller.

    ``pixels`` is the number of lights on the strand. There is no way to read
    it from the device, so it must be supplied for per-pixel work.

    Uses ONE persistent connection: reconnecting per command stalls these
    controllers for about a minute.
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT,
                 pixels: Optional[int] = None,
                 timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.pixels = pixels
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._counter = -1

    # -- connection --------------------------------------------------------

    def connect(self) -> socket.socket:
        if self._sock is None:
            s = socket.socket()
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self._sock = s
        return self._sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "Controller":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _next_counter(self) -> int:
        self._counter = (self._counter + 1) % 255
        return self._counter

    # -- transport ---------------------------------------------------------

    def send_raw(self, payload: bytes) -> None:
        """Send bytes exactly as given.

        Note this returning cleanly means only that the socket accepted the
        bytes. It is NOT evidence the device acted on them.
        """
        self.connect().sendall(payload)

    def send(self, inner: bytes, version: int = 0x02) -> None:
        """Wrap an inner message and send it."""
        self.send_raw(p.wrap(inner, counter=self._next_counter(), version=version))

    def read(self, settle: float = 2.0) -> bytes:
        s = self.connect()
        time.sleep(settle)
        s.settimeout(2.0)
        buf = b""
        try:
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        finally:
            s.settimeout(self.timeout)
        return buf

    def _request(self, inner: bytes, settle: float = 2.0) -> bytes:
        self.send(inner)
        buf = self.read(settle)
        if not buf:
            raise ZenggeError(f"{self.host}: no reply")
        return buf

    # -- reads -------------------------------------------------------------

    def state(self) -> State:
        return p.parse_state(self._request(p.STATE_QUERY_INNER))

    def clock(self):
        """-> (year, month, day, hour, minute, second, weekday)."""
        self.send_raw(p.CLOCK_READ)
        return p.parse_clock(self.read())

    def timers(self) -> List[Timer]:
        return p.parse_timers(self._request(p.TIMERS_READ))

    # -- writes ------------------------------------------------------------

    def on(self) -> None:
        self.send_raw(p.power(True))
        self.read(settle=1.0)

    def off(self) -> None:
        self.send_raw(p.power(False))
        self.read(settle=1.0)

    def solid(self, hue: int = 0, saturation: int = 100, value: int = 100) -> None:
        """A single colour across the whole strand. Saturation 0 is white."""
        self.send(p.solid_color(hue, saturation, value))
        self.read(settle=1.0)

    def scene(self, pattern: int, colors: Sequence[Color], speed: int = 50,
              brightness: int = 100, style: int = 0x00) -> None:
        """Run an animated scene. ``colors`` is a repeating motif, not per-pixel."""
        self.send(p.scene(pattern, colors, speed, brightness, style))
        self.read(settle=1.0)

    def set_pixels(self, colors: Sequence[Color], brightness: int = 100,
                   seq: int = 0) -> None:
        """Set every light individually. ``colors`` must be one per light.

        For animation, drive this from :meth:`stream_pixels` rather than a bare
        loop, so the rate is paced.
        """
        if self.pixels is not None and len(colors) != self.pixels:
            raise ValueError(f"expected {self.pixels} colours, got {len(colors)}")
        self.send(p.per_pixel(colors, brightness, seq))
        self.read(settle=0.5)

    def stream_pixels(self, frames: Iterable[Sequence[Color]],
                      hz: float = SAFE_PIXEL_HZ, brightness: int = 100) -> int:
        """Push per-pixel frames at a paced rate. Returns frames sent.

        Pacing is not optional. The device offers no backpressure: it will
        accept frames far faster than it renders them and drop the excess
        silently, while every send reports success. Above ~5 Hz on a
        ~180-pixel strand the output visibly stutters; far above it, almost
        nothing renders at all.
        """
        interval = 1.0 / hz
        start = time.time()
        sent = 0
        for i, frame in enumerate(frames):
            self.send(p.per_pixel(frame, brightness, seq=i & 0xFF))
            sent += 1
            delay = start + (i + 1) * interval - time.time()
            if delay > 0:
                time.sleep(delay)
        return sent

    def stream_music(self, levels: Iterable[int], hz: float = 8.33) -> int:
        """Stream audio levels (0-100). Returns frames sent.

        The controller does no audio analysis -- supply the numbers from
        wherever you like. The vendor app uses a fixed 120 ms interval.
        These frames are 3 bytes, far cheaper than per-pixel ones, so the
        per-pixel rate ceiling does not apply.
        """
        interval = 1.0 / hz
        start = time.time()
        sent = 0
        for i, level in enumerate(levels):
            self.send(p.music_level(level))
            sent += 1
            delay = start + (i + 1) * interval - time.time()
            if delay > 0:
                time.sleep(delay)
        return sent

    # -- on-device timers --------------------------------------------------

    def set_timer(self, slot: int, hour: int, minute: int, payload: bytes,
                  enabled: bool = True, daymask: int = p.EVERY_DAY) -> None:
        """Write one of the controller's own timer slots (typically 1-6).

        These run on the device, so they fire whether or not this machine is
        awake. The payload is a full command -- see ``PAYLOAD_POWER_ON`` /
        ``PAYLOAD_POWER_OFF`` in :mod:`zengge.protocol`, or pass a scene.
        """
        self._commit_bracket()
        self.send(p.timer_write(slot, hour, minute, payload, enabled, daymask))
        self.read(settle=1.0)
        self._commit_bracket()

    def clear_timer(self, slot: int) -> None:
        self._commit_bracket()
        self.send(p.timer_delete(slot))
        self.read(settle=1.0)
        self._commit_bracket()

    def _commit_bracket(self) -> None:
        """The vendor app brackets timer writes with e0 0e 01; mirror it."""
        self.send(p.TIMER_COMMIT)
        self.read(settle=0.4)


def discover(broadcast: str = "255.255.255.255", timeout: float = 3.0) -> List[dict]:
    """Find controllers by UDP broadcast on port 48899.

    Returns dicts with ip, mac, model and (on newer firmware) a fourth
    ``token`` field whose purpose is unknown -- no command needs it.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    found: List[dict] = []
    try:
        s.sendto(b"HF-A11ASSISTHREAD", (broadcast, 48899))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = s.recvfrom(1024)
            except socket.timeout:
                break
            parts = data.decode(errors="replace").strip().split(",")
            if len(parts) >= 3:
                entry = {"ip": parts[0], "mac": parts[1], "model": parts[2]}
                if len(parts) >= 4:
                    entry["token"] = parts[3]
                if entry not in found:
                    found.append(entry)
    finally:
        s.close()
    return found
