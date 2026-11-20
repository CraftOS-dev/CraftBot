#!/usr/bin/env python3
"""Container entrypoint: check the install when needed, then run CraftBot.

The image is fully provisioned at build time (see the Dockerfile), and a new
named volume is seeded from the image's /data, stamped with the image id, so
a normal first start has nothing to install. `install.py` runs only when the
stamp in the state directory does not match this image: a bind-mounted host
directory, or a volume created by an older image. It is idempotent, fetches
what that state directory lacks (the embedding model lives there), and fails
loudly instead of letting the app start half-installed. Then `run.py` runs in
the foreground and serves the browser UI on port 7925.

Written in Python rather than shell so a Windows checkout's CRLF line endings
cannot break it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("CRAFTBOT_HOME") or "/data")
IMAGE_ID_FILE = APP_DIR / ".craftbot-image-id"
STAMP_FILE = STATE_DIR / ".craftbot-image-id"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _prepare_state_dir() -> bool:
    home = Path(os.environ.get("HOME") or STATE_DIR / "home")
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        home.mkdir(parents=True, exist_ok=True)
        probe = STATE_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        print(
            f"CraftBot cannot write to {STATE_DIR}: {exc}\n"
            f"The container runs as UID {os.getuid()}. If {STATE_DIR} is a host "
            "directory, give it to that user, for example:\n"
            f"  sudo chown -R {os.getuid()}:{os.getgid()} /path/on/host",
            file=sys.stderr,
        )
        return False
    return True


def _check_install() -> int:
    image_id = _read(IMAGE_ID_FILE)
    if image_id and _read(STAMP_FILE) == image_id:
        return 0

    print(f"Checking the CraftBot installation for {STATE_DIR}...", flush=True)
    code = subprocess.call(
        [sys.executable, str(APP_DIR / "install.py"), "--no-launch"],
        cwd=str(APP_DIR),
        stdin=subprocess.DEVNULL,
    )
    if code != 0:
        print(
            "CraftBot setup did not complete; the messages above name the step "
            "that failed.",
            file=sys.stderr,
        )
        return code
    if image_id:
        STAMP_FILE.write_text(image_id + "\n", encoding="utf-8")
    return 0


def main() -> int:
    if not _prepare_state_dir():
        return 1
    code = _check_install()
    if code != 0:
        return code

    # Replace this process, so the init process (tini) signals run.py directly.
    os.chdir(APP_DIR)
    argv = [sys.executable, str(APP_DIR / "run.py"), "--no-open-browser", *sys.argv[1:]]
    os.execv(sys.executable, argv)
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
