# zengge-ledenet-py

A Python library for **ZENGGE / LEDENET LED controllers running the newer OEM
firmware** (model `0x6E`, `ZG-BL-HONGRUI`, 2025 builds) that existing libraries
cannot talk to. Licensed **GPL-3.0**.

**`docs/PROTOCOL.md` is the authoritative reference** and the most valuable
thing in this repo. It is complete — read it before writing any protocol code.

## Status

Protocol fully reverse-engineered and verified against real hardware. The
library itself is being built; the protocol document came first deliberately, so
the knowledge is durable independent of the code.

## ⛔ This repository is PUBLIC — never commit anything identifying

The work originated on one person's home network. **None of that may appear
here.** Before every commit, check for:

- MAC addresses, IP addresses, hostnames
- The 32-hex discovery token (it is device-specific and of unknown purpose —
  treat it as a credential)
- Any specific house layout: pixel counts, zone boundaries, room names
- Anyone's saved scenes, palettes, or schedules
- Any claim that a named installer installed *this* system

  ⚠️ **Naming installer brands as compatible hardware IS allowed** — decided
  2026-08-18. `README.md` lists several installer brands as examples of who
  resells this controller. That is a factual compatibility statement, and it is
  the phrasing affected users actually search for. A list of resellers implies
  nothing about any particular household. **Do not "fix" this by deleting the
  names**, and do not add a reason here that narrows it — no region, no metro,
  no "ours is the local one".

**Everything must be generic and configurable**: pixel count, zone definitions,
device address, scene definitions. If an example needs a number, it is a
parameter with a neutral default, not someone's real value.

## Design constraints (learned the hard way — do not "fix" these)

- **There is no backpressure.** The socket accepts frames far faster than the
  device renders them, and reports total success while the lights stutter or
  freeze. Any API that streams frames **must** pace deliberately, and must not
  infer a render rate from its own send loop. See PROTOCOL.md.
- **Pace to ≤5 Hz for per-pixel writes.** 8 Hz visibly stutters.
- **One persistent connection.** Rapid reconnects stall the controller for about
  a minute, and produce false "unsupported" conclusions.
- **Use ≥5 s timeouts.** These are 2.4 GHz devices and slow to accept.
- **Inner messages carry no checksum**; the wrapper's checksum covers all.
  ⚠️ **Known exception under investigation:** the `e0 05` timer builders emit
  one, and PROTOCOL.md's timer section documents a trailing `<ck>` without
  saying whether the message is bare or wrapped. Do **not** "fix" this either
  way until a capture settles it — see the pending golden fixture.
- **`e1 21` entries are 5 bytes and tile as a repeating motif; `e1 23` entries
  are 7 bytes and are true per-pixel.** Confusing them produces output that
  parses fine and looks wrong.

## Verification rule

**A state byte moving is not proof the lights did anything**, and the reverse is
also true — a command can render visibly while moving no state bytes. During
development, three separate measurements looked clean in code and were wrong in
reality. Anything claiming to change light output needs a human to look at it
before it is documented as working.

## Tests

    python3 -m unittest discover -s tests -t .

Standard library only — no pytest, no dev dependencies. Tests must run on a
fresh clone with **no device, no network and no captures**, so anything needing
hardware belongs behind an explicit opt-in, never in the default run.

- **`tests/test_protocol.py`** — structural: message layout, field offsets,
  entry widths, parser edge cases. Guards the shape.
- **`tests/test_golden.py`** + `tests/golden/captures.json` — byte-exactness
  against frames captured from the vendor app. Guards the *facts*. Pending
  entries are marked `TODO` and skip cleanly.

### ⛔ A golden capture is evidence, never an expected value

If a golden test fails, **the builder is wrong**. Editing `capture_hex` to make
a test pass silently destroys the only durable record of what the device
actually said — and it will look like a green suite. Never do it. The same goes
for deleting a failing capture or marking it `TODO` again.

### Do not invent protocol facts

PROTOCOL.md and `DISCOVERY.md` mark what is unverified, and those markers are
load-bearing. Do not resolve an open question by guessing, by reasoning from the
classic Magic Home command set (deduction from it failed completely here), or by
inferring from `flux_led`. An unknown byte stays named as unknown until a
capture or a human looking at the lights settles it. Tests that pin unsettled
behaviour belong in the `OpenQuestions` class, which says so explicitly.

### Fixtures must be neutral

Captures embed whatever was on screen: a timer's bytes *are* someone's schedule,
a scene's entries *are* their palette. Create a throwaway timer or scene in the
app purely to capture it. Never paste in a real one, and never capture discovery
traffic — it carries the IP, MAC and the 32-hex token.

## Legal posture

- Reverse engineering for interoperability; **no protection measure was
  circumvented** — the protocol is plaintext on a local network.
- `flux_led` (LGPL-3.0-or-later) was read to decode the state frame and is
  credited. **No code was copied.** Do not vendor or paste its source.
- Do not use vendor trademarks in the project name or imply endorsement.
  Factual compatibility statements only.
- `tools/` contains a device impersonator for protocol discovery. It must stay
  framed as a research/interop tool for use on your own network with your own
  hardware.

## Layout

    zengge/          the library
    docs/PROTOCOL.md the protocol reference — authoritative
    tests/           structural tests + golden captures (stdlib unittest)
    tools/           device impersonator for capturing an unknown firmware's commands
    examples/        runnable examples, fully parameterised
