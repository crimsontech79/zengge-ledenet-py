#!/usr/bin/env python3
"""Impersonate a controller so the vendor app sends its commands to you.

This is how the protocol in ../docs/PROTOCOL.md was mapped. Deducing the
command set from the classic Magic Home protocol did not work; letting the app
speak did.

    ./fakedevice.py --ip 192.168.1.20

Then exercise features in the vendor app. Every command it sends is logged
verbatim, including palettes and timings you could not have guessed.

⚠️  USE ONLY ON YOUR OWN NETWORK WITH YOUR OWN HARDWARE.
    This is a research and interoperability tool. It answers discovery
    broadcasts on your LAN; run it deliberately, not as a background service.

Tips that save hours:

* **Answer the reads the app depends on**, or its screens stall and never load.
  Copy the exact reply bytes off your real controller (query it, paste them in
  below) rather than inventing them.
* **Reply in the same framing as the request.** A bare reply to a wrapped query
  makes the app ignore the device entirely.
* **To learn a destructive operation** -- deleting a schedule, say -- have this
  tool *report* one that exists only here, then delete it in the app and
  capture the command. Nothing real is touched, and you learn how to undo
  something before you do it for real.
* Claiming the same MAC as your real controller can persuade the app to talk to
  you instead of it. That is application-level identity only -- it does not
  touch your machine's actual MAC -- but do it knowingly.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

# --- what we claim to be. Override from the command line. -----------------
DEFAULT_MAC = "AABBCCDDEEFF"
DEFAULT_MODEL = "AK001-ZJ21413"
DEFAULT_TOKEN = "0" * 32          # newer firmware sends a 4th discovery field

# --- canned replies -------------------------------------------------------
# Best practice: replace these with bytes read from YOUR real controller.
#
# The scene id at [8] and the pixel count at [18] are deliberately NEUTRAL
# placeholders (0x01 and 100), not values read off a real installation — a
# scene id plus a pixel count together describe somebody's actual lighting.
# Keep them generic if you edit this frame.
STATE = bytes.fromhex("ea8101006e0b23250132f0b1644e0064050064ffffffff0100000324")

EMPTY_SLOTS = ["01000000000000", "02000000000000", "03000000000000",
               "04000000000000", "05000000000000", "06000000000000"]

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def build_timers(mock_slot1: str | None) -> bytes:
    slots = list(EMPTY_SLOTS)
    if mock_slot1:
        slots[0] = mock_slot1
    return bytes.fromhex("e006" + "".join(slots))


class Fake:
    def __init__(self, ip: str, mac: str, model: str, token: str,
                 timers: bytes):
        self.ip, self.mac, self.model, self.token = ip, mac, model, token
        self.timers = timers

    # -- UDP discovery ----------------------------------------------------

    def udp_loop(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", 48899))
        reply = f"{self.ip},{self.mac},{self.model},{self.token}".encode()
        log(f"UDP 48899 up, announcing {reply!r}")
        while True:
            try:
                data, addr = s.recvfrom(1024)
            except OSError:
                break
            log(f"UDP <- {addr[0]}: {data!r}")
            if b"HF-A11ASSISTHREAD" in data:
                s.sendto(reply, addr)
            elif data.startswith(b"AT+LVER"):
                s.sendto(b"+ok=6E_40_20250709_ZG-BL-HONGRUI\r", addr)
            elif data.startswith(b"AT+"):
                s.sendto(b"+ok\r", addr)

    # -- TCP control ------------------------------------------------------

    def handle(self, conn: socket.socket, addr) -> None:
        log(f"TCP ++ {addr[0]}:{addr[1]} connected")
        conn.settimeout(300)
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                log(f"TCP <- {addr[0]}  {len(data):4d}B  {data.hex()}")

                wrapped = (len(data) >= 10
                           and data[:4] == bytes([0xB0, 0xB1, 0xB2, 0xB3]))
                inner = (data[10:10 + ((data[8] << 8) | data[9])]
                         if wrapped else data)

                def reply(payload: bytes, what: str) -> None:
                    # Answer in the SAME framing as the request, or the app
                    # ignores the device.
                    if wrapped:
                        ver, ctr = data[6], data[7]
                        body = (bytes([0xB0, 0xB1, 0xB2, 0xB3, 0x00, 0x01, ver, ctr])
                                + bytes([len(payload) >> 8, len(payload) & 0xFF])
                                + payload)
                        out = body + bytes([sum(body) & 0xFF])
                    else:
                        out = payload
                    conn.sendall(out)
                    log(f"TCP -> {addr[0]}  {len(out):4d}B  {out.hex()}  ({what})")

                if inner[:4] == bytes([0xEA, 0x81, 0x8A, 0x8B]) or \
                        inner[:3] == bytes([0x81, 0x8A, 0x8B]):
                    reply(STATE, "state")
                elif inner[:2] == bytes([0xE0, 0x06]):
                    reply(self.timers, "timers")
                elif inner[:3] == bytes([0x11, 0x1A, 0x1B]):
                    n = time.localtime()
                    body = bytes([0x0F, 0x11, 0x14, n.tm_year - 2000, n.tm_mon,
                                  n.tm_mday, n.tm_hour, n.tm_min, n.tm_sec,
                                  n.tm_wday + 1, 0x00])
                    reply(body + bytes([sum(body) & 0xFF]), "clock")
                elif inner[:2] == bytes([0x10, 0x14]):
                    log(f"TCP == {addr[0]}  set-clock accepted (no reply)")
                else:
                    # THIS is the interesting line -- an unanswered command is
                    # usually the thing you are trying to learn.
                    log(f"TCP !! {addr[0]}  UNRECOGNISED -- inner: {inner.hex()}")
        except (socket.timeout, OSError) as e:
            log(f"TCP -- {addr[0]} {e}")
        finally:
            conn.close()
            log(f"TCP -- {addr[0]} closed")

    def tcp_loop(self) -> None:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 5577))
        s.listen(8)
        log("TCP 5577 up, waiting for the app")
        while True:
            try:
                conn, addr = s.accept()
            except OSError:
                break
            threading.Thread(target=self.handle, args=(conn, addr),
                             daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", required=True, help="this machine's LAN address")
    ap.add_argument("--mac", default=DEFAULT_MAC,
                    help="MAC to advertise; matching your real controller's "
                         "may persuade the app to talk to this instead")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--token", default=DEFAULT_TOKEN)
    ap.add_argument("--mock-timer", default=None, metavar="HEX",
                    help="report a timer in slot 1, e.g. "
                         "01f0131e00fe0ee001002300000000000000000000 "
                         "(19:30 daily, lights on) so you can delete it in the "
                         "app and capture the delete command")
    args = ap.parse_args()

    log("⚠️  research tool -- your own network and hardware only")
    log(f"pretending to be {args.model} at {args.ip} (MAC {args.mac})")
    fake = Fake(args.ip, args.mac, args.model, args.token,
                build_timers(args.mock_timer))
    threading.Thread(target=fake.udp_loop, daemon=True).start()
    threading.Thread(target=fake.tcp_loop, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
