"""Byte-exactness tests against frames captured from the vendor app.

These are the tests that actually protect the reverse-engineering. A builder
that still passes tests/test_protocol.py can be structurally perfect and
factually wrong; only a verbatim capture settles it.

    python3 -m unittest discover -s tests -t . -v

Entries in golden/captures.json marked TODO are skipped, so this file is green
on a fresh clone and turns meaningful as captures land.

⛔ If a test here fails, the BUILDER is wrong. Never edit a capture to make a
   test pass -- the capture is the evidence.
"""
import json
import os
import re
import unittest

from zengge import protocol as p
from zengge.protocol import Color

CAPTURES = os.path.join(os.path.dirname(__file__), "golden", "captures.json")
TODO = "TODO"


def _load():
    with open(CAPTURES) as fh:
        return json.load(fh)["captures"]


def _is_pending(value):
    """True if a field is still an unfilled placeholder."""
    if isinstance(value, str):
        return value.strip().upper().startswith(TODO)
    if isinstance(value, dict):
        return any(_is_pending(v) for v in value.values())
    if isinstance(value, list):
        return any(_is_pending(v) for v in value)
    return False


def _colors(raw):
    return [Color(c.get("hue", 0), c.get("saturation", 100),
                  c.get("value", 100), c.get("white", 0)) for c in raw]


def _build(name, args):
    """Call the builder named in the fixture with its recorded arguments."""
    if name == "timer_write":
        return p.timer_write(args["slot"], args["hour"], args["minute"],
                             bytes.fromhex(args["payload_hex"]),
                             enabled=args.get("enabled", True),
                             daymask=args.get("daymask", p.EVERY_DAY),
                             second=args.get("second", 0))
    if name == "timer_delete":
        return p.timer_delete(args["slot"])
    if name == "scene":
        return p.scene(args["pattern"], _colors(args["colors"]),
                       speed=args.get("speed", 50),
                       brightness=args.get("brightness", 100),
                       style=args.get("style", 0))
    if name == "per_pixel":
        return p.per_pixel(_colors(args["colors"]),
                           brightness=args.get("brightness", 100),
                           seq=args.get("seq", 0))
    if name == "solid_color":
        return p.solid_color(args["hue"], args["saturation"], args["value"])
    if name == "power":
        return p.power(args["on"])
    if name == "music_level":
        return p.music_level(args["level"])
    raise AssertionError(f"no builder mapping for {name!r}")


class GoldenFrames(unittest.TestCase):

    def test_fixture_file_is_valid(self):
        """The fixture must always parse, even while every entry is pending."""
        for entry in _load():
            self.assertIn("name", entry)
            self.assertIn("capture_hex", entry)

    def test_captures_match_builders(self):
        pending, checked = [], 0
        for entry in _load():
            name = entry["name"]
            if _is_pending(entry.get("capture_hex")):
                pending.append(name)
                continue
            checked += 1

            with self.subTest(capture=name):
                captured = bytes.fromhex(entry["capture_hex"].replace(" ", ""))
                framing = entry.get("framing", "")
                wrapped = captured[:4] == p.WRAPPER_MAGIC[:4]

                if not _is_pending(framing):
                    self.assertEqual(
                        "wrapped" if wrapped else "bare", framing,
                        f"{name}: recorded framing does not match the bytes",
                    )

                if entry.get("builder") is None:
                    self._check_parsed(name, captured, entry.get("expect", {}))
                else:
                    self.assertFalse(
                        _is_pending(entry.get("args", {})),
                        f"{name}: capture is filled in but args are still TODO",
                    )
                    expected = p.unwrap(captured)
                    actual = _build(entry["builder"], entry["args"])
                    self.assertEqual(
                        actual.hex(), expected.hex(),
                        f"\n{name}: builder output does not match the capture."
                        f"\n  captured: {expected.hex()}"
                        f"\n  built:    {actual.hex()}"
                        f"\nThe CAPTURE is the evidence. Fix the builder.",
                    )

        if pending and not checked:
            raise unittest.SkipTest(
                f"no captures recorded yet ({len(pending)} pending: "
                f"{', '.join(pending)})"
            )

    def _check_parsed(self, name, captured, expect):
        """Entries with builder=null are reply frames: parse, do not build."""
        state = p.parse_state(captured)
        for field, want in expect.items():
            self.assertEqual(getattr(state, field), want,
                             f"{name}: state.{field}")


class FixtureHygiene(unittest.TestCase):
    """This repository is public. Captures must not carry personal detail."""

    def test_no_capture_embeds_an_ip_or_mac(self):
        """Discovery replies carry an IP, a MAC and the 32-hex token. None of
        those belong in a fixture -- capture command frames, not discovery."""
        blob = json.dumps(_load())
        self.assertIsNone(
            re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", blob),
            "a fixture contains an IP address",
        )
        self.assertIsNone(
            re.search(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", blob),
            "a fixture contains a MAC address",
        )
        for entry in _load():
            hexstr = entry.get("capture_hex", "")
            if not _is_pending(hexstr):
                self.assertNotIn(
                    "hf-a11assistthread", hexstr.lower(),
                    f"{entry['name']}: discovery traffic must not be captured",
                )

    def test_timer_captures_use_neutral_times(self):
        """A captured timer's time bytes ARE somebody's schedule. Fixtures must
        use a throwaway time created for the test, not a real one."""
        for entry in _load():
            if entry.get("builder") not in ("timer_write",):
                continue
            args = entry.get("args", {})
            if _is_pending(args):
                continue
            self.assertEqual(
                args.get("second", 0), 0,
                f"{entry['name']}: odd seconds value suggests a real schedule",
            )


if __name__ == "__main__":
    unittest.main()
