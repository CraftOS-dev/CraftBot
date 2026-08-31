"""Open the setup window against a fake backend, for design work.

    python -m installer.ui.preview            # starts "not installed"
    python -m installer.ui.preview running    # starts installed + running

Nothing here touches the machine: no download, no install directory, no
Task Scheduler entry. Pressing Install runs a scripted fake that streams
plausible log output and download progress for a few seconds, so the busy
state, the progress bar, the activity line and the button transitions can
all be seen without a real 2.5 GB provision.

This exists because the alternative is testing UI changes by performing a
full install, which takes long enough that in practice the UI stops being
tested at all.
"""

from __future__ import annotations

import sys
import threading
import time

_SCRIPT = [
    (0.3, "\n=== Install ===\n"),
    (0.4, "[1/9] disk-space        OK   42.1 GB free\n"),
    (0.6, "[2/9] python            ..   fetching CPython 3.10.14\n"),
    (0.8, "  extracting python-build-standalone\n"),
    (0.6, "[3/9] python-deps       ..   installing 214 locked packages\n"),
    (0.5, "  Collecting chromadb==0.5.3\n"),
    (0.5, "  Collecting sentence-transformers==3.0.1\n"),
    (0.6, "[4/9] native-runtime    OK   VC++ runtime present\n"),
    (0.5, "[5/9] smoke             OK   imports resolve\n"),
    (0.6, "[6/9] node              ..   fetching Node 24\n"),
    (0.6, "[7/9] frontend          ..   npm install\n"),
    (0.5, "[8/9] whatsapp-bridge   OK\n"),
    (0.5, "[9/9] playwright        OK   chromium ready\n"),
    (0.4, "\nSTARTING FRONTEND SERVER [OK]\nSTARTING AGENT BACKEND [OK]\n"),
]


class FakeAPI:
    """Same surface as WizardAPI, none of the consequences."""

    def __init__(self, state: str = "not_installed") -> None:
        self.state = state
        self.busy = False
        self._lines: list = []
        self._progress = None
        self._lock = threading.Lock()

    # ── queries ────────────────────────────────────────────────────────
    def get_state(self) -> dict:
        return {
            "state": self.state,
            "pid": 12345 if "running" in self.state else None,
            "worker_busy": self.busy,
            "browser_url": "http://localhost:3000",
        }

    def get_default_install_location(self) -> str:
        import craftbot

        return craftbot.default_install_location()

    def drain_output(self) -> dict:
        with self._lock:
            lines, self._lines = self._lines, []
            progress, self._progress = self._progress, None
        return {"lines": lines, "progress": progress}

    def view_log(self) -> str:
        return "(preview mode - no real log)"

    def open_in_browser(self) -> None:
        self._emit("\n[preview] would open the browser here\n")

    # ── actions ────────────────────────────────────────────────────────
    def install(self, target_dir: str) -> dict:
        self._emit(f"\n[preview] pretending to install into {target_dir}\n")
        return self._run(lambda: setattr(self, "state", "installed_running"))

    def start(self) -> dict:
        return self._run(lambda: setattr(self, "state", "installed_running"))

    def stop(self) -> dict:
        return self._run(lambda: setattr(self, "state", "installed_stopped"))

    def repair(self) -> dict:
        return self._run(lambda: None)

    def uninstall(self) -> dict:
        return self._run(lambda: setattr(self, "state", "not_installed"))

    # ── internals ──────────────────────────────────────────────────────
    def _emit(self, text: str) -> None:
        with self._lock:
            self._lines.append(text)

    def _run(self, finish) -> dict:
        if self.busy:
            return {"started": False}
        self.busy = True

        def worker() -> None:
            total = 96 * 1024 * 1024
            read = 0
            for delay, line in _SCRIPT:
                time.sleep(delay)
                self._emit(line)
                read = min(total, read + total // len(_SCRIPT))
                with self._lock:
                    self._progress = {"read": read, "total": total}
            finish()
            self.busy = False

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True}


def main() -> None:
    from installer.ui.window import run

    state = sys.argv[1] if len(sys.argv) > 1 else "not_installed"
    aliases = {
        "running": "installed_running",
        "stopped": "installed_stopped",
        "fresh": "not_installed",
    }
    run(FakeAPI(aliases.get(state, state)), version="1.4.2")


if __name__ == "__main__":
    main()
