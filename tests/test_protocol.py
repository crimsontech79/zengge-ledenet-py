"""Structural tests for zengge.protocol.

Pure functions only -- no device, no network, no dependencies. Run with:

    python3 -m unittest discover -s tests -v

Every assertion here is traceable to docs/PROTOCOL.md. Where a test pins
behaviour the protocol document does NOT settle, it says so explicitly and is
grouped under OpenQuestions at the bottom. Those tests guard against silent
drift; they are not claims that the current behaviour is correct.
"""
import unittest

from zengge import protocol as p
from zengge.protocol import Color


class Checksum(unittest.TestCase):
    """PROTOCOL.md: checksum = sum(bytes) & 0xFF."""

    def test_sum_and_mask(self):
        self.assertEqual(p.checksum(b"\x01\x02\x03"), 6)
        self.assertEqual(p.checksum(b"\xff\xff"), 0xFE)
        self.assertEqual(p.checksum(b""), 0)

    def test_with_checksum_appends_one_byte(self):
        out = p.with_checksum(b"\x10\x20")
        self.assertEqual(out, b"\x10\x20\x30")

    def test_published_state_query_checksum(self):
        """PROTOCOL.md documents the bare query verbatim as `81 8a 8b 96`.

        This is the one builder output the protocol document states as a
        complete literal, so it is a true golden value and not a derivation.
        """
        self.assertEqual(p.STATE_QUERY_BARE.hex(), "818a8b96")

    def test_published_clock_read_checksum(self):
        """`11 1a 1b 0f <ck>` -- 0x11+0x1a+0x1b+0x0f = 0x55."""
        self.assertEqual(p.CLOCK_READ.hex(), "111a1b0f55")


class Wrapper(unittest.TestCase):
    """PROTOCOL.md: b0 b1 b2 b3 00 01 <ver> <ctr> <len_hi> <len_lo> <inner> <ck>."""

    def test_layout(self):
        out = p.wrap(b"\xaa\xbb", counter=0x07, version=0x02)
        self.assertEqual(out[:6], bytes([0xB0, 0xB1, 0xB2, 0xB3, 0x00, 0x01]))
        self.assertEqual(out[6], 0x02)          # version
        self.assertEqual(out[7], 0x07)          # counter
        self.assertEqual(out[8:10], b"\x00\x02")  # length, big-endian
        self.assertEqual(out[10:12], b"\xaa\xbb")
        self.assertEqual(out[-1], p.checksum(out[:-1]))

    def test_length_is_big_endian(self):
        """A 256-byte inner message must split as 01 00, not 00 01."""
        out = p.wrap(b"\x00" * 256)
        self.assertEqual(out[8:10], b"\x01\x00")

    def test_counter_is_masked(self):
        self.assertEqual(p.wrap(b"\x00", counter=0x1FF)[7], 0xFF)

    def test_unwrap_roundtrip(self):
        for inner in (b"\x01", b"\xe1\x23" + bytes(700)):
            self.assertEqual(p.unwrap(p.wrap(inner)), inner)

    def test_unwrap_passes_through_bare_data(self):
        bare = bytes([0xEA, 0x81, 0x00, 0x01])
        self.assertEqual(p.unwrap(bare), bare)

    def test_inner_message_carries_no_checksum(self):
        """PROTOCOL.md: adding an inner checksum causes SILENT failure.

        The builders for wrapped messages must therefore emit no trailing
        checksum of their own. Timers are deliberately excluded here -- see
        OpenQuestions.
        """
        for name, msg in (
            ("solid_color", p.solid_color(30, 36, 100)),
            ("scene", p.scene(0x03, [Color(0, 100, 100)])),
            ("per_pixel", p.per_pixel([Color(0, 100, 100)])),
            ("music_level", p.music_level(50)),
            ("clock_write", p.clock_write(26, 8, 15, 19, 30, 0, 6)),
        ):
            with self.subTest(builder=name):
                self.assertNotEqual(
                    msg[-1], p.checksum(msg[:-1]),
                    f"{name} looks like it ends in its own checksum",
                )


class StateFrame(unittest.TestCase):
    """PROTOCOL.md: 28-byte EA 81 frame. Byte offsets are load-bearing."""

    def frame(self, **over):
        buf = bytearray(28)
        buf[0], buf[1] = 0xEA, 0x81
        buf[4] = 0x6E          # model
        buf[5] = 0x11          # firmware
        buf[6] = p.POWER_ON
        buf[7] = 0x25          # mode
        buf[8] = 0x66          # pattern
        buf[9] = 50            # speed
        buf[10] = p.COLOR_MODE_RGB
        buf[11] = 0xB1         # hue/2
        buf[12] = 100          # saturation
        buf[13] = 78           # value
        buf[27] = buf[6]
        for k, v in over.items():
            buf[int(k[1:])] = v
        return bytes(buf)

    def test_field_offsets(self):
        s = p.parse_state(self.frame())
        self.assertEqual(s.model, 0x6E)
        self.assertEqual(s.version, 0x11)
        self.assertTrue(s.is_on)
        self.assertEqual(s.mode, 0x25)
        self.assertEqual(s.pattern, 0x66)
        self.assertEqual(s.speed, 50)
        self.assertEqual(s.saturation, 100)
        self.assertEqual(s.value, 78)
        self.assertTrue(s.is_rgb)

    def test_hue_is_doubled(self):
        """PROTOCOL.md states 0xB1 = 354 degrees."""
        self.assertEqual(p.parse_state(self.frame()).hue, 354)

    def test_power_byte_is_6_not_2(self):
        """Byte 2 looks like a power flag and is not -- it was seen as both
        0x01 and 0x02 with the lights OFF."""
        off = p.parse_state(self.frame(b6=p.POWER_OFF, b2=0x01))
        self.assertFalse(off.is_on)
        self.assertFalse(p.parse_state(self.frame(b6=p.POWER_OFF, b2=0x02)).is_on)
        self.assertTrue(p.parse_state(self.frame(b6=p.POWER_ON, b2=0x01)).is_on)

    def test_accepts_wrapped_reply(self):
        s = p.parse_state(p.wrap(self.frame()))
        self.assertEqual(s.model, 0x6E)

    def test_raw_is_preserved_for_undecoded_bytes(self):
        """Bytes 14/15 are pattern parameters and stay unparsed; callers
        investigating them need the raw frame."""
        f = self.frame(b14=0xFF, b15=0x00)
        self.assertEqual(p.parse_state(f).raw[14:16], b"\xff\x00")

    def test_rejects_non_ea81(self):
        with self.assertRaises(ValueError):
            p.parse_state(bytes([0x81, 0x00] + [0] * 20))

    def test_rejects_short_frame(self):
        with self.assertRaises(ValueError):
            p.parse_state(bytes([0xEA, 0x81, 0x00]))


class Power(unittest.TestCase):
    """PROTOCOL.md: bare, `71 23 0f <ck>` / `71 24 0f <ck>`."""

    def test_on_off_bytes(self):
        self.assertEqual(p.power(True)[:3], bytes([0x71, 0x23, 0x0F]))
        self.assertEqual(p.power(False)[:3], bytes([0x71, 0x24, 0x0F]))

    def test_bare_messages_do_carry_a_checksum(self):
        for msg in (p.power(True), p.power(False)):
            self.assertEqual(msg[-1], p.checksum(msg[:-1]))


class SolidColor(unittest.TestCase):
    """PROTOCOL.md: e0 01 00 a1 <hue/2> <sat> <val> <wtemp> <wbri> 00 00 14 00 00."""

    def test_layout_and_length(self):
        msg = p.solid_color(30, 36, 100)
        self.assertEqual(len(msg), 14)
        self.assertEqual(msg[:4], bytes([0xE0, 0x01, 0x00, 0xA1]))
        self.assertEqual(msg[4], 15)    # 30 / 2
        self.assertEqual(msg[5], 36)
        self.assertEqual(msg[6], 100)
        self.assertEqual(msg[11], 0x14)

    def test_hue_halving_matches_state_decode(self):
        """Encode and decode must agree on the hue/2 convention."""
        for hue in (0, 30, 120, 354):
            self.assertEqual(p.solid_color(hue, 100, 100)[4] * 2, hue)


class Scene(unittest.TestCase):
    """PROTOCOL.md: e1 21, 16-byte header, 5-byte entries, repeating motif."""

    def test_header_length_and_entry_width(self):
        msg = p.scene(0x03, [Color(0, 100, 100), Color(120, 100, 100)])
        self.assertEqual(msg[:2], bytes([0xE1, 0x21]))
        self.assertEqual(len(msg), 16 + 2 * 5)

    def test_count_byte_matches_entries(self):
        for n in (1, 3, 12):
            msg = p.scene(0x03, [Color()] * n)
            self.assertEqual(msg[15], n)
            self.assertEqual(len(msg), 16 + n * 5)

    def test_header_fields(self):
        msg = p.scene(pattern=0x42, colors=[Color()], speed=17,
                      brightness=90, style=0x02)
        self.assertEqual(msg[3], 90)     # brightness
        self.assertEqual(msg[4], 0x42)   # pattern id
        self.assertEqual(msg[5], 0x02)   # style
        self.assertEqual(msg[6], 0x01)
        self.assertEqual(msg[8], 17)     # speed

    def test_entry_encoding(self):
        msg = p.scene(0x03, [Color(hue=30, saturation=36, value=100, white=0)])
        self.assertEqual(msg[16:21], bytes([15, 36, 100, 0x00, 0x00]))

    def test_empty_palette_rejected(self):
        with self.assertRaises(ValueError):
            p.scene(0x03, [])


class PerPixel(unittest.TestCase):
    """PROTOCOL.md: e1 23, 9-byte header, 7-byte entries, size 9 + N*7."""

    def test_documented_size_formula(self):
        for n in (1, 50, 200, 255):
            self.assertEqual(len(p.per_pixel([Color()] * n)), 9 + n * 7)

    def test_header(self):
        msg = p.per_pixel([Color()] * 3, brightness=90, seq=2)
        self.assertEqual(msg[:2], bytes([0xE1, 0x23]))
        self.assertEqual(msg[2], 2)      # seq
        self.assertEqual(msg[5], 90)     # brightness
        self.assertEqual(msg[6], 0x64)
        self.assertEqual(msg[8], 3)      # N

    def test_entry_order_maps_to_pixel_index(self):
        """Entry order is physical light order -- this is what makes zones work."""
        msg = p.per_pixel([Color(hue=0), Color(hue=120), Color(hue=240)])
        hues = [msg[9 + i * 7 + 1] * 2 for i in range(3)]
        self.assertEqual(hues, [0, 120, 240])

    def test_entry_leading_byte_is_zero(self):
        msg = p.per_pixel([Color()])
        self.assertEqual(msg[9], 0x00)

    def test_count_out_of_range_rejected(self):
        for bad in ([], [Color()] * 256):
            with self.assertRaises(ValueError):
                p.per_pixel(bad)

    def test_entry_widths_differ_from_scene(self):
        """The documented footgun: 5 bytes for e1 21, 7 for e1 23. Mixing them
        produces output that still parses and looks wrong."""
        n = 4
        scene_body = len(p.scene(0x03, [Color()] * n)) - 16
        pixel_body = len(p.per_pixel([Color()] * n)) - 9
        self.assertEqual(scene_body, n * 5)
        self.assertEqual(pixel_body, n * 7)
        self.assertNotEqual(scene_body, pixel_body)


class MusicLevel(unittest.TestCase):
    """PROTOCOL.md: e1 07 <level>, 3 bytes, level 0-100."""

    def test_three_bytes(self):
        self.assertEqual(p.music_level(50), bytes([0xE1, 0x07, 50]))

    def test_clamped_not_wrapped(self):
        """A level over 100 must clamp, never wrap into an unrelated byte."""
        self.assertEqual(p.music_level(255)[2], 100)
        self.assertEqual(p.music_level(-5)[2], 0)


class Clock(unittest.TestCase):
    """PROTOCOL.md reply: 0f 11 14 <yy> <mm> <dd> <hh> <mi> <ss> <weekday> 00 <ck>."""

    def test_parse_documented_reply_layout(self):
        reply = bytes([0x0F, 0x11, 0x14, 26, 8, 15, 19, 30, 45, 6, 0x00])
        self.assertEqual(p.parse_clock(reply), (2026, 8, 15, 19, 30, 45, 6))

    def test_parse_accepts_wrapped(self):
        reply = bytes([0x0F, 0x11, 0x14, 26, 8, 15, 19, 30, 45, 6, 0x00])
        self.assertEqual(p.parse_clock(p.wrap(reply))[0], 2026)

    def test_write_layout(self):
        msg = p.clock_write(26, 8, 15, 19, 30, 45, 6)
        self.assertEqual(msg[:2], bytes([0x10, 0x14]))
        self.assertEqual(list(msg[2:9]), [26, 8, 15, 19, 30, 45, 6])
        self.assertEqual(msg[-1], 0x0F)

    def test_rejects_short_reply(self):
        with self.assertRaises(ValueError):
            p.parse_clock(bytes([0x0F, 0x11]))


class TimerParsing(unittest.TestCase):
    """PROTOCOL.md: records are VARIABLE length. A fixed stride fails silently."""

    def test_empty_slot_is_seven_bytes(self):
        reply = bytes([0xE0, 0x06]) + bytes([1, 0, 0, 0, 0, 0, 0])
        timers = p.parse_timers(reply)
        self.assertEqual(len(timers), 1)
        self.assertTrue(timers[0].is_empty)

    def test_populated_slot_carries_payload_inline(self):
        payload = p.PAYLOAD_POWER_ON
        reply = (bytes([0xE0, 0x06])
                 + bytes([1, 0xF0, 19, 30, 0, 0xFE, len(payload)]) + payload)
        t, = p.parse_timers(reply)
        self.assertEqual((t.slot, t.hour, t.minute), (1, 19, 30))
        self.assertEqual(t.daymask, p.EVERY_DAY)
        self.assertEqual(t.payload, payload)
        self.assertFalse(t.is_empty)

    def test_mixed_lengths_walk_correctly(self):
        """The trap: an empty slot AFTER a populated one is only found if the
        walker advances by 7 + len, not by a constant."""
        payload = p.PAYLOAD_POWER_OFF
        reply = (bytes([0xE0, 0x06])
                 + bytes([1, 0xF0, 6, 15, 0, 0xFE, len(payload)]) + payload
                 + bytes([2, 0, 0, 0, 0, 0, 0])
                 + bytes([3, 0xF0, 22, 0, 0, 0xFE, len(payload)]) + payload)
        timers = p.parse_timers(reply)
        self.assertEqual([t.slot for t in timers], [1, 2, 3])
        self.assertEqual([t.hour for t in timers], [6, 0, 22])
        self.assertTrue(timers[1].is_empty)

    def test_truncated_trailing_record_is_dropped_not_crashed(self):
        reply = bytes([0xE0, 0x06]) + bytes([1, 0, 0])
        self.assertEqual(p.parse_timers(reply), [])


class TimerBuilding(unittest.TestCase):
    """PROTOCOL.md: e0 05 <slot> <en> <hh> <mm> <ss> <daymask> <len> <payload> <ck>."""

    def test_write_layout(self):
        payload = p.PAYLOAD_POWER_ON
        msg = p.timer_write(1, 19, 30, payload)
        self.assertEqual(msg[:2], bytes([0xE0, 0x05]))
        self.assertEqual(msg[2], 1)
        self.assertEqual(msg[3], p.TIMER_ENABLED)
        self.assertEqual((msg[4], msg[5], msg[6]), (19, 30, 0))
        self.assertEqual(msg[7], p.EVERY_DAY)
        self.assertEqual(msg[8], len(payload))
        self.assertEqual(msg[9:9 + len(payload)], payload)

    def test_enabled_flag_is_the_only_difference_when_disabling(self):
        on = p.timer_write(1, 19, 30, p.PAYLOAD_POWER_ON, enabled=True)
        off = p.timer_write(1, 19, 30, p.PAYLOAD_POWER_ON, enabled=False)
        self.assertEqual(on[3], 0xF0)
        self.assertEqual(off[3], 0x0F)
        self.assertEqual(on[:3], off[:3])
        self.assertEqual(on[4:-1], off[4:-1])   # everything but flag and checksum

    def test_delete_matches_documented_zeroed_record(self):
        """PROTOCOL.md: e0 05 <slot> 00 00 00 00 00 00 <ck>."""
        msg = p.timer_delete(1)
        self.assertEqual(len(msg), 10)
        self.assertEqual(msg[:9], bytes([0xE0, 0x05, 1, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(msg[-1], p.checksum(msg[:-1]))

    def test_payloads_are_fourteen_bytes(self):
        """PROTOCOL.md: `e0 01 00 23` + zero padding TO 14 BYTES."""
        for payload in (p.PAYLOAD_POWER_ON, p.PAYLOAD_POWER_OFF):
            self.assertEqual(len(payload), 14)
        self.assertEqual(p.PAYLOAD_POWER_ON[:4],
                         bytes([0xE0, 0x01, 0x00, p.POWER_ON]))
        self.assertEqual(p.PAYLOAD_POWER_OFF[:4],
                         bytes([0xE0, 0x01, 0x00, p.POWER_OFF]))

    def test_a_scene_can_be_a_timer_payload(self):
        """PROTOCOL.md: the payload is a complete command."""
        scene = p.scene(0x66, [Color(30, 36, 100)])
        msg = p.timer_write(2, 6, 15, scene)
        self.assertEqual(msg[8], len(scene))
        self.assertEqual(msg[9:9 + len(scene)], scene)


class DescribePayload(unittest.TestCase):

    def test_power(self):
        self.assertEqual(p.describe_payload(p.PAYLOAD_POWER_ON), "power on")
        self.assertEqual(p.describe_payload(p.PAYLOAD_POWER_OFF), "power off")

    def test_scene_reports_pattern_id_in_hex(self):
        """Ids must be read in hex: 0x66 and 66 decimal are different scenes
        and transpose easily."""
        out = p.describe_payload(p.scene(0x66, [Color()]))
        self.assertIn("0x66", out)

    def test_unknown_payload_falls_back_to_hex(self):
        self.assertIn("abcd", p.describe_payload(bytes([0xAB, 0xCD])))

    def test_empty_payload_does_not_raise(self):
        p.describe_payload(b"")


class OpenQuestions(unittest.TestCase):
    """Behaviour the protocol document does NOT settle.

    These tests pin what the code does today so a change is deliberate rather
    than accidental. Each one names the question it is standing in for. When a
    capture settles the question, replace the test with a golden assertion.
    """

    def test_timer_builders_emit_an_inner_checksum(self):
        """UNSETTLED: PROTOCOL.md says inner messages carry NO checksum, but the
        timer section documents a trailing <ck> and does not state whether the
        message is bare or wrapped. The builders currently checksum, and
        Controller.set_timer then wraps -- so the device would see a checksum
        inside a wrapper, which the framing rule says fails silently.

        Resolve with a capture: if it starts b0 b1 b2 b3, it is wrapped.
        """
        for msg in (p.timer_write(1, 19, 30, p.PAYLOAD_POWER_ON),
                    p.timer_delete(1)):
            self.assertEqual(msg[-1], p.checksum(msg[:-1]))

    def test_per_pixel_white_byte_defaults_to_0x64(self):
        """UNSETTLED: PROTOCOL.md labels the 7th entry byte <white>, but
        per_pixel() substitutes 0x64 (=100) whenever Color.white is 0, so a
        caller can never send 0 there.

        If it truly is a white channel, every default colour is washed with
        full white -- yet the captured doodle rendered saturated red/green/blue
        correctly. That suggests the byte is a per-entry brightness, not white,
        and that the document's label is wrong.
        """
        entry = p.per_pixel([Color(hue=0, saturation=100, value=100, white=0)])[9:]
        self.assertEqual(entry[6], 0x64)
        explicit = p.per_pixel([Color(0, 100, 100, white=50)])[9:]
        self.assertEqual(explicit[6], 50)

    def test_scene_byte_7_defaults_to_0x64_but_is_settable(self):
        """SETTLED 2026-08-15 against six captured scene frames: five carried
        0x64 at byte 7 and one carried 0x4A. Hardcoding 0x64 reproduced that
        scene incorrectly while still producing a message the device accepts --
        exactly the silent-wrongness this suite exists to catch.

        Its MEANING is still unknown; only the fact that it varies is settled.
        """
        self.assertEqual(p.scene(0x03, [Color()])[7], 0x64)
        self.assertEqual(p.scene(0x42, [Color()], param7=0x4A)[7], 0x4A)


if __name__ == "__main__":
    unittest.main()
