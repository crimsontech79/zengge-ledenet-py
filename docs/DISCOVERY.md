# How this protocol was mapped, and what is still unknown

## The method: let the app tell you

**Deduction from the classic Magic Home protocol failed completely.** Every
opcode tried from the documented LEDENET command set — `0x61` presets, `0x59`
zones, `0x38`, `0x51` custom patterns, and EA-prefixed variants of each — was
either ignored or made the controller stop responding. That is roughly two
hours of dead ends, and none of it converged.

What worked was **impersonating a controller** so the vendor app sent its
commands to a machine that logged them. `tools/fakedevice.py` does this:

1. Answer `HF-A11ASSISTHREAD` on UDP 48899 with your own address.
2. Accept TCP on 5577 and log every byte received.
3. **Answer the reads the app depends on**, or it stalls and its screens never
   load.

Then exercise each feature in the app. Every capture is a command, verbatim,
including palettes and timings that could not have been guessed.

### The reads you must answer

Discovered by watching the app hang, one screen at a time:

| Query | Without a reply |
|---|---|
| state (`ea 81 8a 8b`) | app rejects the device and retries every ~5 s |
| get time (`11 1a 1b`) | schedule screen shows "Device current time / Load failed" |
| get timers (`e0 06`) | schedule list never loads at all |

**Reply in the same framing as the request.** Answering a wrapped query with a
bare reply makes the app ignore the device — that alone cost a round of
confusion.

Best source for these replies is your **real** controller: query it, then have
the impersonator echo those exact bytes.

### Learn destructive operations against the mock first

To capture how the app *deletes* a schedule, have the impersonator report a
schedule that exists only in its replies. Then delete it in the app and capture
the command. Nothing on real hardware is touched, and you learn the delete
command before you need it.

That ordering matters: timer slots are persistent configuration, unlike a
colour or a scene. Do not write one to real hardware until you know how to
clear it.

---

## Traps that cost real time

**A state byte moving is not proof the lights did anything.** Both directions
of that mistake happened here: power was written up as "working" on byte
evidence alone before anyone had watched the lights, and separately a per-pixel
write that moved *no* state bytes was rendering perfectly.

**There is no backpressure.** Three separate frame-rate figures were reported as
measured and were wrong, each corrected only by someone looking at the lights:
27 fps (the device was rendering ~0.1), "8.6 fps, animation viable" (that was
Python's socket-fill speed), and "8 Hz, zero errors" (it stuttered).

**Random content does not mask dropped frames.** Assumed; tested; false. A
four-effect show at 8 Hz stuttered visibly on all four, including smooth
gradients.

**Rapid reconnects produce false negatives.** A sweep of ten queries showed the
first three replying and the last seven silent. That reads exactly like "those
seven are unsupported"; it was really the device having stopped talking.
Re-test negatives with ~15 s spacing.

**One scene being already active hides everything.** Switching the lights on
into a scene the controller already held moved only the power byte, which
briefly looked like proof that scenes were not representable in the state frame
at all. Always compare two *different* scenes.

**The vendor app may have more than one schedule screen.** One writes to the
device; another is cloud-only and produces no LAN traffic whatsoever. Testing
only the cloud one would lead you to conclude device-side scheduling does not
exist.

---

## Open questions

Contributions very welcome, especially from anyone with different hardware.

### Unidentified bytes

| Where | Byte | Notes |
|---|---|---|
| state frame | `[2]` | seen as `0x01` and `0x02` with the lights off both times; differs between wrapped and unwrapped replies |
| state frame | `[14]`, `[15]` | pattern parameters; correlate with static vs animated but only one static sample was available |
| `e1 21` | byte 7 | meaning unknown, but it VARIES: `0x64` on five captured scenes, `0x4A` on a sixth. Must be carried through from the capture -- hardcoding `0x64` reproduces that scene wrongly while still being accepted |
| colour entry | 4th byte | always `0x00` in every capture |
| colour entry | 5th byte | looks like a white channel; `0x64` on a warm-white scene, `0x00` on colour scenes |
| discovery | 4th field | 32 hex chars, stable, purpose unknown. No command needs it |
| saturation | high bit | values like `0xE4` (= 100 + 128) appear on some violet hues but not consistently — 270° was seen both with and without it |

### Unidentified commands

`e1 26`, `e0 0e 01`, `e1 25` (returns the active scene in `e1 21` shape) — seen
in app traffic, partially understood at best.

### Unmeasured

- **Does the render-rate ceiling scale with pixel count?** Frame size is
  `9 + N*7`, so a shorter strand should sustain a higher rate. Untested — all
  measurements come from a single ~180-pixel strand. **This is the most useful
  thing a contributor with different hardware could measure.**
- **Animation type and style ids.** The `e1 21` format is understood but there
  is no id → name map. Building one means tapping through the app's animation
  list against the impersonator and recording which id each name produces.
- **Whether music mode tolerates dropped frames better than per-pixel does.**
  Plausible, since audio-driven brightness is more forgiving than hard colour
  alternation, but untested.
- **Maximum entry counts** for `e1 21` motifs and `e1 23` per-pixel writes.
  A full ~180-pixel strand works; the upper bound is unknown.
