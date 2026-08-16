# ZENGGE / LEDENET protocol — model `0x6E`, firmware `ZG-BL-HONGRUI`

Everything here was established empirically against a real controller on
2026-08-15, by observing the vendor app's own traffic and by testing against the
device with a human watching the lights. Where something is inferred rather than
confirmed, it says so.

**This is a different command set from the classic Magic Home / LEDENET
protocol.** If you have arrived here because an existing library cannot talk to
your controller, that is why — see "Why `flux_led` fails" below.

---

## Identifying the device

    UDP 48899, send the literal:  HF-A11ASSISTHREAD
    reply:  <ip>,<mac>,<model>,<token>

The classic reply has **three** fields. This firmware returns **four** — the
extra 32-hex-character value is stable across queries and its purpose is
**unknown**. No command documented here requires it, and control works fully
without it. Existing libraries parse only the first three fields and silently
discard it.

    AT+LVER\r   ->   +ok=6E_40_20250709_ZG-BL-HONGRUI
                         |  |  |        |
                         |  |  |        OEM variant string
                         |  |  firmware build date (YYYYMMDD)
                         |  firmware version (hex)
                         model number (hex)

> ⛔ **Only send `AT+LVER`.** The same UDP interface accepts `AT+RELD` (factory
> reset) and `AT+Z` (reboot). A factory reset unbinds the controller from the
> vendor app and loses any configured scenes.

Control is **TCP 5577**. On the unit examined, a full 65535-port scan found
*no other open port* — everything below goes over 5577.

---

## Framing

Two framings coexist, and **which one a message needs varies per command**.

### Bare

    <bytes...> <checksum>          checksum = sum(bytes) & 0xFF

### Wrapped

    b0 b1 b2 b3 00 01 <ver> <ctr> <len_hi> <len_lo> <inner...> <checksum>

* `ver` — `0x01` or `0x02`. **The commands in this document need `0x02`.**
* `ctr` — a counter that increments per message. Not validated by the device;
  a wrong value is not the reason a command fails.
* `len` — length of `inner`, big-endian.
* `checksum` — sum of every preceding byte in the wrapper, `& 0xFF`.

> ⚠️ **Inner messages carry NO checksum of their own.** The outer checksum
> covers everything. Adding an inner checksum causes silent failure — the device
> accepts the message and does nothing.

---

## State query

    send (bare):     81 8a 8b 96
    send (wrapped):  inner = ea 81 8a 8b        <- note the EA prefix

Both work. The vendor app uses the wrapped `ea 81 8a 8b` form.

The reply is a **28-byte `EA 81` frame**, not the classic 14-byte state:

| Byte | Meaning |
|---|---|
| 0–1 | `EA 81` header |
| 2 | varies between wrapped/unwrapped replies — **not** a power flag |
| 4 | model number |
| 5 | firmware/protocol version |
| **6** | **power — `0x23` ON, `0x24` OFF** |
| 7 | mode |
| **8** | **active pattern / animation id** |
| 9 | speed |
| 10 | colour mode — `0xF0` rgb, `0x0F` white |
| 11 | hue / 2 (so `0xB1` = 354°) |
| 12 | saturation 0–100 |
| 13 | value 0–100 |
| 14, 15 | pattern parameters — **not** white temp/brightness |
| 27 | mirrors the power byte; **not** a checksum |

> ⚠️ Do not decode this with a classic 14-byte map. The offsets are wrong and
> produce plausible nonsense. Byte 2 in particular looks like a state flag and
> is not — it was observed as both `0x01` and `0x02` with the lights off.

---

## Commands

### Power — bare

    71 23 0f <ck>    ON
    71 24 0f <ck>    OFF

### Solid colour — wrapped, version `0x02`

    e0 01 00 a1 <hue/2> <sat> <val> <wtemp> <wbri> 00 00 14 00 00

`a1` = colour write mode, `b1` = white. Saturation `0` renders white.

### Scene / animation — wrapped, version `0x02`

    e1 21 00 <bri> <id> <style> 01 <?> <speed> 00*6 <n> then n x 5-byte entries

    entry: <hue/2> <sat> <val> <?> <white>

* `id` — animation type.
* `style` — animation style variant (e.g. `0x02` is a random fade-in/out
  "firefly" style on the unit examined; `0x00` otherwise).
* `n` — number of colour entries.

> ⚠️ **The colour entries are a REPEATING MOTIF, not per-pixel data.** Three
> entries repeat around the whole strand. A 3-entry `on, off, off` motif lights
> every third pixel; a 12-entry motif of 4+4+4 gives blocks of four.
> **Sending one entry per physical pixel does not work** — it is accepted and
> renders as garbage.

> ⚠️ **The same `id` can serve different-looking scenes.** Two scenes may share
> an animation type and differ only in palette and speed. The id alone does not
> identify a scene.

### Per-pixel — wrapped, version `0x02`

The vendor app calls this a "doodle".

    e1 23 <seq> 00 01 <bri> 64 00 <N> then N x 7-byte entries

    entry: 00 <hue/2> <sat> <val> 00 00 <white>      <- 7 bytes, NOT 5

* `N` — the pixel count, and exactly that many entries must follow.
* Entry order maps directly to physical light index, so arbitrary per-pixel
  patterns and independent zones are possible.
* Message size is `9 + N*7` bytes.
* The app sends it **twice**, with `seq` incrementing.

> ⚠️ **The entry width differs between `e1 21` (5 bytes) and `e1 23` (7 bytes).**
> Mixing them up produces output that still parses and looks wrong.

### Music / reactive — wrapped, version `0x02`

    setup:   e1 25
             e1 24 00 <bri> 07 00 01 <bri> 00*n <n> <n colour entries>
    stream:  e1 07 <level>          <- 3 bytes, level 0-100

**The controller performs no audio analysis.** The app computes a single scalar
and streams it. Anything that can produce a 0–100 number can drive this.

The vendor app streams at a **fixed 120 ms interval (8.33 Hz)**.

### Clock

    read:   11 1a 1b 0f <ck>      (bare)
    reply:  0f 11 14 <yy> <mm> <dd> <hh> <mi> <ss> <weekday> 00 <ck>
    write:  10 14 <yy> <mm> <dd> <hh> <mi> <ss> <weekday> 00 0f

`weekday` is Mon=1 … Sun=7. The controller has a working real-time clock.

### Timers — on-device schedules

**Read** — `e0 06`. The reply is **variable length**: an empty slot is 7 bytes,
a populated one carries its payload inline.

    empty     : <slot> 00 00 00 00 00 00
    populated : <slot> f0 <hh> <mm> <ss> <daymask> <len> <payload...>

**Write** — `e0 05`:

    e0 05 <slot> <en> <hh> <mm> <ss> <daymask> <len> <payload...> <ck>

    en       0xF0 enabled, 0x0F disabled, 0x00 empty/delete
    daymask  0xFE = every day (bits 1-7)
    ck       sum of all preceding bytes & 0xFF

**Delete** — write a zeroed record:

    e0 05 <slot> 00 00 00 00 00 00 <ck>

The payload is a complete command, so a timer can fire power *or* a whole scene:

| Payload | Effect |
|---|---|
| `e0 01 00 23` + zero padding to 14 bytes | lights ON |
| `e0 01 00 24` + zero padding to 14 bytes | lights OFF |
| a full `e1 21 …` message | apply that scene |

The vendor app brackets timer writes with `e0 0e 01` before and after.

> ⚠️ **Assuming fixed-size slots in the read reply is wrong**, and it fails
> silently — the app simply shows no schedules.

> ⚠️ **The controller has no idea when sunset is.** The vendor app offers only
> fixed clock times. Sunset/sunrise scheduling must be pushed by something that
> knows, and refreshed as the seasons shift (~1 minute per day).

---

## Render rate — the socket lies

Measured by eye with red/blue alternation (a deliberately harsh test):

| Rate | What actually renders |
|---|---|
| ≤5 Hz | flawless |
| 6 Hz | ~1–2 drops per 48 frames |
| 8 Hz | **visibly stutters** |
| 9–11 Hz | unreliable |
| 12 Hz | many frames never appear |
| 27 Hz sent | renders **~0.1 fps** — total collapse |

> ⛔ **There is no backpressure signal of any kind.** `sendall()` succeeds, error
> counts stay zero, and the device keeps answering state queries — identically at
> 4 Hz and at 27 Hz. **Send success tells you nothing about whether the LEDs
> moved.** Pace your output; you cannot measure the render rate from your own
> send loop.

Numbers above are for a ~180-pixel strand (frames of roughly 1.3 kB). **The ceiling is
expected to scale with frame size**, so shorter strands should sustain more —
but that is *inferred, not measured*, and is a good first contribution if you
have a different pixel count.

Music-mode frames (`e1 07`, 3 bytes) are far cheaper than per-pixel frames and
the vendor app runs them at 8.33 Hz, so the per-pixel ceiling does **not** apply
to them.

### Rapid reconnects stall the device

Ten quick connect/query/close cycles left the controller answering nothing for
over a minute. It recovers on its own. **Use one persistent connection.**

This also produces false negatives: a sweep of ten queries showed the first
three replying and the rest silent, which reads exactly like "unsupported" when
it was really the device having stopped talking. **Re-test any negative result
with ~15 s spacing before believing it.**

Separately, the controller **closes an idle connection about every 3 minutes**.
That is normal; reconnect and carry on.

### Poll, do not wait for pushes

The controller has been seen sending state frames unprompted, but **it does not
do so dependably**. A purely passive listener received nothing across 18 minutes
and several connections (2026-08-16, real hardware) — long enough for a client
built on that assumption to look permanently broken, reporting whatever defaults
it started with.

**Query it.** Send the bare state query on the connection you already hold, at
whatever interval you need. Reads are free; it is reconnecting that hurts, and
the two are easy to conflate:

    one connection, polled every 30 s      ✅ fine
    a new connection per query             ⛔ stalls the device for a minute

Both framings of the query work, but the bare `81 8a 8b 96` form is the one with
the most mileage on real hardware.

---

## Why `flux_led` fails

[`flux_led`](https://github.com/Danielhiversen/flux_led) is the established
library for Magic Home / LEDENET devices and is excellent for the hardware it
covers. It cannot talk to this firmware:

* Model `0x6E` is **not in its device database**.
* The device **only ever** replies with the 28-byte `EA 81` extended frame and
  never a classic 14-byte state, so protocol auto-detection fails outright with:

      Exception: Cannot determine protocol

  …for both the sync and async devices.
* Forcing `ProtocolLEDENET25Byte` gets the state parsing working, but the
  library then falls back to an **unknown-model profile whose reported
  capabilities are wrong** — it claims RGB-only, no pixel configuration, and a
  generic 21-effect list, none of which reflects the hardware.
* Its command constructors (`0x61` preset, `0x59` zone, `0x38`, `0x51` custom)
  are **all rejected or silently ignored** by this firmware. `0x61` makes the
  controller stop responding for about a minute.

`flux_led`'s source was invaluable for decoding the `EA 81` frame layout, and it
is credited accordingly. **No code was copied from it.**

---

## Method

The command set was not deduced. Every attempt to derive it from the documented
Magic Home protocol failed — the opcodes are simply different.

What worked was **impersonating a controller on the local network** so the
vendor app sent its commands to a machine that logged them. See `tools/`. Each
feature exercised in the app yielded its command verbatim, including palettes
and timing that could not have been guessed.

If your controller is a model this library does not cover, that is the method to
extend it.
