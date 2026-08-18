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

| Capability | Verified? | Notes |
|---|---|---|
| Power on / off | ✅ watched | |
| Read full state | ✅ watched | 28-byte `EA 81` frame, fully decoded; reported scene matched reality |
| **Solid colour** | ✅ watched | driven from a HomeKit colour picker |
| **Scenes / animations** | ✅ watched | palette, speed, brightness, animation style; replay is byte-exact |
| **Per-pixel control** | ✅ watched | every pixel individually addressable |
| **Independent zones** | ✅ watched | animate part of a run while the rest stays static |
| White / colour temp | ⚠️ partly | the lights respond, but the scale direction and Kelvin range are assumptions |
| Device clock — read | ✅ | the controller has a working RTC |
| Device clock — write | ⚠️ decoded | format captured, never sent |
| **Music / reactive** | ⚠️ decoded | captured from the app; never driven from this library |
| **On-device timers** | ⛔ decoded | **not verified, and persistent** — see below |

"✅ watched" means a human looked at the lights, not that a byte moved. That
distinction has been wrong in both directions here, so it is the only standard
this project trusts.

⛔ **Timers are the one thing here that can leave a mess.** Timer slots are the
only *persistent* configuration this library writes: a colour or scene lasts
until the next command, a timer slot survives power cycles and keeps firing.
There is also an unresolved contradiction in the format — `PROTOCOL.md` says
inner messages carry no checksum and that adding one makes the device silently
ignore the message, yet the captured timer format carries one. Nobody has
settled which is right on real hardware, because doing so means writing to a
real slot.

If you use them, learn the format against `tools/` first, know how to clear a
slot before you write one, and check the result in the vendor app.

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

## A note on security

These controllers have **no authentication of any kind**. TCP 5577 accepts
commands from anything that can reach it: no pairing, no key, no challenge, no
rate limit. That is why this library needs no credentials and works with the
internet down — and it is worth being clear that the same property is what makes
it possible at all.

The practical consequence: **anything on your local network can control these
lights**, including anything a guest, a compromised device, or an untrusted IoT
gadget brings onto it. For most people that is an acceptable risk for outdoor
lighting. It is worth knowing rather than discovering.

Two things follow, and both are already true of this code:

- **Reads are free, writes are not.** Querying state changes nothing. The one
  genuinely persistent write is a timer slot — see the warning above.
- **The discovery reply's fourth field is treated as a secret.** Newer firmware
  returns 32 stable hex characters whose purpose is unknown and which no command
  here uses. It is never logged or stored, on the grounds that if it turns out
  to be a device key, publishing yours would matter, and if it is meaningless,
  redacting it costs nothing.

Nothing here circumvents a protection measure, because there is no protection
measure to circumvent. The protocol is plaintext on a local network, and this is
documented for interoperability.

## Credits

[`flux_led`](https://github.com/lightinglibs/flux_led) (LGPL-3.0-or-later) is
the established library for Magic Home / LEDENET devices and is excellent for
the hardware it supports. Reading its source made decoding the state frame far
quicker. **No code was copied from it**; this is an independent implementation
for a firmware it does not cover.

## Licence

GPL-3.0. See [LICENSE](LICENSE).

## Not affiliated

This is an independent, unofficial project. It is **not affiliated with,
endorsed by, or supported by** ZENGGE, Magic Home, or any lighting installer or
manufacturer. Product and company names are used only to describe which hardware
this library is compatible with. All trademarks belong to their respective
owners.

Use at your own risk. Writing to a device's timer slots or configuration changes
persistent state on your hardware.

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
