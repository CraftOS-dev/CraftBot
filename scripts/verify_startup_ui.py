#!/usr/bin/env python3
"""Check the installed browser bundle connects and receives backend state.

Run with the installed environment's Python after verifying OS startup. This
opens a browser only; it never starts CraftBot or its startup registration.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:7925")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    frames = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        def record_frame(payload):
            try:
                message = json.loads(payload)
                # Record types only: never save session tokens or app state.
                frames.append(message.get("type"))
            except (ValueError, AttributeError):
                pass

        page.on("websocket", lambda socket: socket.on("framereceived", record_frame))
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            for _ in range(120):
                if "init" in frames:
                    break
                page.wait_for_timeout(1000)
            assert "init" in frames, (
                f"Browser never received backend init; frames={frames}; errors={errors}"
            )
            page.locator(".cb-splash").wait_for(state="detached", timeout=30000)
            page.screenshot(path=str(args.output / "browser-ready.png"))
            (args.output / "browser-result.json").write_text(
                json.dumps(
                    {
                        "url": page.url,
                        "backend_init_received": True,
                        "startup_splash_removed": True,
                        "page_errors": errors,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                "PASS: installed frontend received backend state and left the startup splash"
            )
        except Exception:
            page.screenshot(path=str(args.output / "browser-failure.png"))
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
