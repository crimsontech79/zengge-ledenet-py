# zengge-ledenet-py

Python control for **ZENGGE / LEDENET LED controllers running newer OEM firmware**
that existing libraries cannot talk to — in particular **model `0x6E`**,
firmware string **`ZG-BL-HONGRUI`**, discovery model **`AK001-ZJ21413`**.

If you landed here after seeing this from `flux_led`:

```
Exception: Cannot determine protocol
```

…this is why, and this library is the fix. **[Read `docs/PROTOCOL.md`](docs/PROTOCOL.md)** —
it is a complete, verified reference for the protocol, useful even if you never
run this code.

> **Status:** protocol fully reverse-engineered and verified against real
> hardware. Library implementation in progress. The protocol document is
> complete and is the point of the project.

---

## Why this exists

These controllers are widely sold for **permanent outdoor lighting** — the
year-round eave lights installed by companies like Firefly, Trimlight, Gemstone,
EverLights, Jellyfish and many regional installers. The hardware inside is
usually a generic ZENGGE / Magic Home controller.

Newer units (2025 firmware) **replaced the classic Magic Home command set**.
Every documented LEDENET opcode — `0x61` presets, `0x51` custom patterns, `0x59`
zones, `0x38` — is either ignored or actively breaks the connection. Nothing
public described the replacement.

So this is written down now, so nobody else has to spend a night finding it.

## What works

| Capability | Notes |
|---|---|
| Power on / off | |
| Read full state | 28-byte `EA 81` frame, fully decoded |
| **Scenes / animations** | palette, speed, brightness, animation style |
| **Per-pixel control** | every pixel individually addressable |
| **Independent zones** | animate part of a run while the rest stays static |
| **Music / reactive** | stream an audio level; the device renders it |
| Device clock | read and write |
| **On-device timers** | schedules that run with no computer involved |

The last one matters most: schedules live **on the controller**, so they fire
whether or not the machine that wrote them is awake.

## Install

```
pip install zengge-ledenet          # (not yet published)
```

Pure standard library. No dependencies.

## Quick start

```python
from zengge import Controller

with Controller("192.168.1.50", pixels=100) as c:
    print(c.state())
    c.on()
    c.solid(hue=30, saturation=36, value=100)   # warm white
```

Zones are yours to define — the library has no built-in idea of "front" or
"back", because that depends entirely on how your run is installed:

```python
zones = {"near": range(0, 40), "far": range(40, 100)}
```

## ⚠️ Read this before streaming frames

**The device gives no backpressure.** Sockets accept frames far faster than the
controller renders them, and report complete success while the lights stutter or
freeze. During development, pushing 27 fps rendered about **0.1 fps** — with
zero errors reported.

**Pace to ≤5 Hz for per-pixel writes.** See
[the render-rate section](docs/PROTOCOL.md#render-rate--the-socket-lies).

Also: **use one persistent connection.** Rapid reconnects stall the controller
for about a minute — and that produces convincing false negatives.

## Discovering an unsupported controller

`tools/` contains a device impersonator: it answers discovery on your LAN and
logs everything the vendor app sends. That is how this protocol was mapped —
deduction from the classic protocol failed completely; the app simply told us.

> **Use only on your own network, with your own hardware.** It is a research and
> interoperability tool.

## Credits

[`flux_led`](https://github.com/Danielhiversen/flux_led) (LGPL-3.0-or-later) is
the established library for Magic Home / LEDENET devices and is excellent for
the hardware it supports. Reading its source made decoding the state frame far
quicker. **No code was copied from it**; this is an independent implementation
for a firmware it does not cover.

## Licence

GPL-3.0. See [LICENSE](LICENSE).

---

<details>
<summary>Keywords (for search)</summary>

ZENGGE, Zengge controller, LEDENET, Magic Home, MagicHome, magichome protocol,
flux_led, flux led, "Cannot determine protocol", AK001-ZJ21413, AK001-ZJ2145,
ZG-BL-HONGRUI, model 0x6E, model 6E, firmware 20250709, HF-A11ASSISTHREAD,
port 5577, UDP 48899, AT+LVER, EA 81 state frame, 28 byte state, b0b1b2b3
wrapper, e1 21 scene, e1 23 per pixel, e1 07 music mode, e0 05 timer,
e0 06 timers, addressable LED controller, permanent Christmas lights,
permanent holiday lights, permanent outdoor lighting, eave lights,
Firefly lights, Trimlight, Gemstone Lights, EverLights, Jellyfish Lighting,
Everlight, pixel LED controller, WS2811, WS2812, SPI LED controller,
Home Assistant ZENGGE unsupported, Python LED control, reverse engineering,
local control, no cloud, cloud free, LAN control

</details>
