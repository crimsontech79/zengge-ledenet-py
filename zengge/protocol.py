"""Message construction and parsing. Pure functions, no I/O.

Every byte layout here was verified against real hardware; see
``docs/PROTOCOL.md``. Where a builder produces bytes that were captured verbatim
from the vendor app, the test suite asserts an exact match.
"""
from __future__ import annotations

from typing import NamedTuple, Optional, Sequence, Tuple

WRAPPER_MAGIC = bytes([0xB0, 0xB1, 0xB2, 0xB3, 0x00, 0x01])

POWER_ON = 0x23
POWER_OFF = 0x24

COLOR_MODE_RGB = 0xF0
COLOR_MODE_WHITE = 0x0F

WRITE_MODE_COLOR = 0xA1
WRITE_MODE_WHITE = 0xB1

TIMER_ENABLED = 0xF0
TIMER_DISABLED = 0x0F
TIMER_EMPTY = 0x00
EVERY_DAY = 0xFE


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def with_checksum(data: bytes) -> bytes:
    return bytes(data) + bytes([checksum(data)])


def wrap(inner: bytes, counter: int = 0, version: int = 0x02) -> bytes:
    """Wrap an inner message in the b0-b1-b2-b3 outer frame.

    The inner message carries NO checksum of its own -- the outer checksum
    covers everything. Adding one causes the device to accept the message and
    do nothing.
    """
    body = (WRAPPER_MAGIC + bytes([version, counter & 0xFF,
                                   (len(inner) >> 8) & 0xFF, len(inner) & 0xFF])
            + bytes(inner))
    return with_checksum(body)


def unwrap(data: bytes) -> bytes:
    """Strip an outer frame if present; otherwise return the input unchanged."""
    if len(data) >= 10 and data[:4] == WRAPPER_MAGIC[:4]:
        length = (data[8] << 8) | data[9]
        return data[10:10 + length]
    return data


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

class State(NamedTuple):
    """A decoded 28-byte ``EA 81`` extended state frame."""

    raw: bytes
    model: int
    version: int
    is_on: bool
    mode: int
    pattern: int          # active animation id
    speed: int
    color_mode: int
    hue: int              # 0-358; stored on the wire as hue/2
    saturation: int       # 0-100
    value: int            # 0-100

    @property
    def is_rgb(self) -> bool:
        return self.color_mode == COLOR_MODE_RGB


STATE_QUERY_BARE = with_checksum(bytes([0x81, 0x8A, 0x8B]))
STATE_QUERY_INNER = bytes([0xEA, 0x81, 0x8A, 0x8B])   # for the wrapped form


def parse_state(data: bytes) -> State:
    """Decode a state reply, unwrapping an outer frame if present.

    Do NOT decode this with a classic 14-byte LEDENET map; the offsets differ
    and produce plausible nonsense.
    """
    buf = unwrap(data)
    if len(buf) < 20 or buf[0] != 0xEA or buf[1] != 0x81:
        raise ValueError(f"not an EA 81 state frame: {buf.hex()}")
    return State(
        raw=bytes(buf),
        model=buf[4],
        version=buf[5],
        is_on=buf[6] == POWER_ON,
        mode=buf[7],
        pattern=buf[8],
        speed=buf[9],
        color_mode=buf[10],
        hue=buf[11] * 2,
        saturation=buf[12],
        value=buf[13],
    )


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def power(on: bool) -> bytes:
    """Bare message; does not need wrapping."""
    return with_checksum(bytes([0x71, POWER_ON if on else POWER_OFF, 0x0F]))


def solid_color(hue: int, saturation: int, value: int) -> bytes:
    """Inner message for a single colour across the whole strand.

    hue 0-358 (halved on the wire), saturation and value 0-100.
    Saturation 0 renders white.
    """
    return bytes([0xE0, 0x01, 0x00, WRITE_MODE_COLOR,
                  (hue // 2) & 0xFF, saturation & 0xFF, value & 0xFF,
                  0x00, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00])


def white(temperature: int, brightness: int) -> bytes:
    """Inner message for the dedicated WHITE channel.

    ``temperature`` and ``brightness`` are 0-100. Byte 3 selects white mode
    (``0xB1``) rather than colour (``0xA1``), and the value rides in the two
    bytes that a colour write leaves as white temp / white brightness.

    ⚠️ UNVERIFIED against hardware. The byte positions come from captured
    traffic, but the SCALE is an assumption: 0 is believed to be the warmest
    and 100 the coolest, and the Kelvin range those correspond to is unknown.
    Do not present a Kelvin figure to a user as if it were measured.
    """
    return bytes([0xE0, 0x01, 0x00, WRITE_MODE_WHITE,
                  0x00, 0x00, 0x00,
                  temperature & 0xFF, brightness & 0xFF,
                  0x00, 0x00, 0x14, 0x00, 0x00])


class Color(NamedTuple):
    hue: int = 0            # 0-358
    saturation: int = 100   # 0-100; 0 renders white
    value: int = 100        # 0-100
    white: int = 0          # dedicated white channel, 0-100


def scene(pattern: int, colors: Sequence[Color], speed: int = 50,
          brightness: int = 100, style: int = 0x00,
          param7: int = 0x64) -> bytes:
    """Inner message for an animated scene.

    ``colors`` is a REPEATING MOTIF, not per-pixel data: three entries repeat
    around the whole strand. Repeat an entry to lengthen its run -- four reds
    followed by four blues gives blocks of four.

    ``param7`` is byte 7, whose meaning is unknown. It reads ``0x64`` on most
    scenes but a captured 6-colour scene used ``0x4A``, so it cannot be
    hardcoded: doing so reproduces that scene incorrectly while still
    producing a message the device accepts. Pass the captured value through.

    Use :func:`per_pixel` when you need to address lights individually.
    """
    if not colors:
        raise ValueError("a scene needs at least one colour")
    head = bytes([0xE1, 0x21, 0x00, brightness & 0xFF, pattern & 0xFF,
                  style & 0xFF, 0x01, param7 & 0xFF, speed & 0xFF,
                  0, 0, 0, 0, 0, 0, len(colors)])
    body = b"".join(bytes([c.hue // 2, c.saturation, c.value, 0x00, c.white])
                    for c in colors)
    return head + body


def per_pixel(colors: Sequence[Color], brightness: int = 100,
              seq: int = 0) -> bytes:
    """Inner message setting every pixel individually.

    ``colors`` must contain exactly one entry per physical light, in strand
    order. Note the entry width here is 7 bytes, where :func:`scene` uses 5.

    Message size is ``9 + len(colors) * 7`` bytes. See the render-rate warning
    in the docs before streaming these: there is no backpressure signal, and
    the device will silently drop frames it cannot keep up with.
    """
    n = len(colors)
    if not 1 <= n <= 255:
        raise ValueError("pixel count must be 1-255")
    head = bytes([0xE1, 0x23, seq & 0xFF, 0x00, 0x01,
                  brightness & 0xFF, 0x64, 0x00, n])
    body = b"".join(bytes([0x00, c.hue // 2, c.saturation, c.value,
                           0x00, 0x00, c.white if c.white else 0x64])
                    for c in colors)
    return head + body


def music_level(level: int) -> bytes:
    """Inner message streaming one audio level, 0-100.

    The controller performs no audio analysis; it just renders the number.
    The vendor app streams these at a fixed 120 ms interval (8.33 Hz).
    """
    return bytes([0xE1, 0x07, max(0, min(100, level))])


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------

CLOCK_READ = with_checksum(bytes([0x11, 0x1A, 0x1B, 0x0F]))


def clock_write(year: int, month: int, day: int, hour: int, minute: int,
                second: int, weekday: int) -> bytes:
    """Inner message setting the device clock. ``weekday`` is Mon=1..Sun=7."""
    return bytes([0x10, 0x14, year % 100, month, day,
                  hour, minute, second, weekday, 0x00, 0x0F])


def parse_clock(data: bytes) -> Tuple[int, int, int, int, int, int, int]:
    """-> (year, month, day, hour, minute, second, weekday)."""
    b = unwrap(data)
    if len(b) < 11:
        raise ValueError(f"short clock reply: {b.hex()}")
    return (2000 + b[3], b[4], b[5], b[6], b[7], b[8], b[9])


# --------------------------------------------------------------------------
# on-device timers
# --------------------------------------------------------------------------

TIMERS_READ = bytes([0xE0, 0x06])
TIMER_COMMIT = bytes([0xE0, 0x0E, 0x01])   # app brackets writes with this

PAYLOAD_POWER_ON = bytes([0xE0, 0x01, 0x00, POWER_ON]) + bytes(10)
PAYLOAD_POWER_OFF = bytes([0xE0, 0x01, 0x00, POWER_OFF]) + bytes(10)


class Timer(NamedTuple):
    slot: int
    enabled: int
    hour: int
    minute: int
    second: int
    daymask: int
    payload: bytes

    @property
    def is_empty(self) -> bool:
        return self.enabled == TIMER_EMPTY and not self.payload


def timer_write(slot: int, hour: int, minute: int, payload: bytes,
                enabled: bool = True, daymask: int = EVERY_DAY,
                second: int = 0) -> bytes:
    """Build a timer-write message (already checksummed; still needs wrapping).

    ``payload`` is a complete command, so a timer can fire power or an entire
    scene. See ``PAYLOAD_POWER_ON`` / ``PAYLOAD_POWER_OFF``, or pass the output
    of :func:`scene`.
    """
    body = bytes([0xE0, 0x05, slot, TIMER_ENABLED if enabled else TIMER_DISABLED,
                  hour, minute, second, daymask, len(payload)]) + bytes(payload)
    return with_checksum(body)


def timer_delete(slot: int) -> bytes:
    """Clear a slot: a write with every field zeroed."""
    return with_checksum(bytes([0xE0, 0x05, slot, TIMER_EMPTY, 0, 0, 0, 0, 0]))


def parse_timers(data: bytes) -> list:
    """Walk the variable-length slot records in an ``e0 06`` reply.

    Records are NOT fixed size: an empty slot is 7 bytes, a populated one
    carries its payload inline. Assuming a fixed stride yields nothing and
    fails silently.
    """
    inner = unwrap(data)
    out, i = [], 2                       # skip the echoed e0 06
    while i + 7 <= len(inner):
        slot, enabled, hour, minute, second, daymask, length = inner[i:i + 7]
        payload = inner[i + 7:i + 7 + length]
        out.append(Timer(slot, enabled, hour, minute, second, daymask, payload))
        i += 7 + length
    return out


def describe_payload(payload: bytes) -> str:
    """Human-readable summary of a timer's action."""
    if payload[:4] == bytes([0xE0, 0x01, 0x00, POWER_ON]):
        return "power on"
    if payload[:4] == bytes([0xE0, 0x01, 0x00, POWER_OFF]):
        return "power off"
    if payload[:2] == bytes([0xE1, 0x21]):
        return f"scene pattern 0x{payload[4]:02x}"
    return f"payload {payload.hex()}"
