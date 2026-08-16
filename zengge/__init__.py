"""Local control for ZENGGE / LEDENET controllers running newer OEM firmware.

Targets model 0x6E / ZG-BL-HONGRUI, whose command set differs from the classic
Magic Home protocol. See docs/PROTOCOL.md.
"""
from .client import Controller, ZenggeError, discover, SAFE_PIXEL_HZ
from .protocol import (
    Color, State, Timer,
    PAYLOAD_POWER_ON, PAYLOAD_POWER_OFF, EVERY_DAY,
)

__all__ = [
    "Controller", "ZenggeError", "discover", "SAFE_PIXEL_HZ",
    "Color", "State", "Timer",
    "PAYLOAD_POWER_ON", "PAYLOAD_POWER_OFF", "EVERY_DAY",
]
__version__ = "0.1.0.dev0"
