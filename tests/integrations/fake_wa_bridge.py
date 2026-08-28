# -*- coding: utf-8 -*-
"""Controllable stand-in for bridge.js — speaks the stdio JSON-line
protocol so ``WhatsAppBridge`` lifecycle tests can drive a REAL subprocess
(start / stop ladder / force-kill / crash) without Node or Chromium.

argv: fake_wa_bridge.py <mode> <auth_dir>
modes:
  ready             emit a ready event, then serve commands
  qr                emit a qr event, then serve commands
  crash             exit(3) immediately (before any event)
  hang-on-shutdown  ack shutdown/logout but never exit (Python must force-kill)
"""

import json
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    mode = sys.argv[1] if len(sys.argv) > 2 else "ready"

    if mode == "crash":
        sys.exit(3)
    if mode == "qr":
        emit(
            {
                "type": "event",
                "event": "qr",
                "data": {
                    "qr_string": "FAKE",
                    "qr_data_url": "data:image/png;base64,QUFBQQ==",
                },
            }
        )
    else:
        emit(
            {
                "type": "event",
                "event": "ready",
                "data": {
                    "owner_phone": "14155552671",
                    "owner_name": "Ada",
                    "wid": "14155552671:1@c.us",
                },
            }
        )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except ValueError:
            continue
        cid, name = cmd.get("id"), cmd.get("cmd")
        if name == "ping":
            emit(
                {
                    "type": "response",
                    "id": cid,
                    "data": {"success": True, "ready": True},
                }
            )
        elif name in ("shutdown", "logout"):
            emit({"type": "response", "id": cid, "data": {"success": True}})
            if mode == "hang-on-shutdown":
                time.sleep(600)  # force-kill target
            sys.exit(0)
        elif name == "get_status":
            emit(
                {
                    "type": "response",
                    "id": cid,
                    "data": {"success": True, "ready": True},
                }
            )
        else:
            emit(
                {
                    "type": "response",
                    "id": cid,
                    "data": {"success": False, "error": f"unknown: {name}"},
                }
            )
    sys.exit(0)


if __name__ == "__main__":
    main()
