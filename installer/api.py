"""JS-callable Python API exposed to the wizard webview.

Each method is invoked from JS as `window.pywebview.api.<method>(...)` and
returns a Promise. Lifecycle actions (install/start/stop/repair/uninstall)
spawn a worker thread so the bridge call returns immediately; the worker
pushes log lines and progress events back to JS via `window.evaluate_js()`.

Why a thread per action: the JS bridge call is itself async, but blocking
the bridge thread means progress callbacks would back up. The worker keeps
the bridge thread free to handle state polls from JS while the install runs.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from typing import Callable, Optional

import craftbot

# webview imported lazily inside `attach` so a syntax error here doesn't
# break source-mode tests that don't have pywebview installed.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class WizardAPI:
    """Methods on this class become JS-callable. Method names map directly
    to `window.pywebview.api.<name>(...)`.

    All public methods MUST be JSON-serializable in/out — pywebview marshals
    arguments via JSON, so plain dict/list/str/int only.
    """

    def __init__(self) -> None:
        self._window: object = None  # set via attach() once the webview exists
        self._worker: Optional[threading.Thread] = None

    def attach(self, window: object) -> None:
        """Called once after webview.create_window() so we can push events
        back to JS via window.evaluate_js()."""
        self._window = window

    # ── State queries ───────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return the current install/run state. Polled by JS every ~1s.

        Mirrors the old Tk wizard's state machine — deliberately uses
        `installed_exe_path()` (install metadata + binary on disk) rather
        than `craftbot._is_installed()` which returns True for stale
        Task Scheduler entries from older installs.
        """
        installed_path = craftbot.installed_exe_path()
        installed = bool(installed_path and os.path.isfile(installed_path))
        pid = craftbot._read_pid()
        running = bool(pid and craftbot._is_running(pid))
        if installed and running:
            state = "installed_running"
        elif installed:
            state = "installed_stopped"
        elif running:
            state = "running_uninstalled"
        else:
            state = "not_installed"
        return {
            "state": state,
            "pid": pid if running else None,
            "worker_busy": self._worker is not None and self._worker.is_alive(),
            "browser_url": craftbot.BROWSER_URL,
        }

    def get_default_install_location(self) -> str:
        return craftbot.default_install_location()

    def pick_install_location(self) -> Optional[str]:
        """Open the OS-native folder picker, return the chosen path (or None
        if the user cancelled). Called from JS when Install is clicked."""
        import webview

        if not self._window:
            return None
        default = craftbot.default_install_location()
        initial_dir = (
            os.path.dirname(default)
            if os.path.isdir(os.path.dirname(default))
            else None
        )
        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, directory=initial_dir or ""
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        # If the user picked a parent rather than a CraftBot subdir, append
        # one — keeps the installed binary tidy.
        if os.path.basename(path).lower() != "craftbot":
            path = os.path.join(path, "CraftBot")
        return path

    def open_in_browser(self) -> None:
        import webbrowser

        webbrowser.open(craftbot.BROWSER_URL)

    def view_log(self) -> str:
        """Return the most recent session from craftbot.log as a string.
        cmd_start writes a `CraftBot service started at ...` separator on
        every launch so we trim to just the last block."""
        log_path = craftbot.LOG_FILE
        if not os.path.isfile(log_path):
            return f"[View log] No log file at {log_path}"
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            marker = "CraftBot service started at"
            if marker in content:
                idx = content.rfind(marker)
                lookback = content.rfind("=" * 60, 0, idx)
                start = lookback if lookback != -1 else idx
                return content[start:]
            lines = content.splitlines(keepends=True)
            return "".join(lines[-80:])
        except OSError as e:
            return f"[View log] Could not read {log_path}: {e}"

    # ── Lifecycle actions ───────────────────────────────────────────────────

    def install(self, target_dir: str) -> dict:
        return self._dispatch("Install", lambda: self._do_install(target_dir))

    def start(self) -> dict:
        return self._dispatch("Start", self._do_start)

    def stop(self) -> dict:
        return self._dispatch("Stop", craftbot.cmd_stop)

    def repair(self) -> dict:
        return self._dispatch(
            "Repair",
            lambda: craftbot.cmd_repair([], progress_cb=self._on_progress),
        )

    def uninstall(self) -> dict:
        return self._dispatch("Uninstall", craftbot.cmd_uninstall)

    # ── Worker dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, label: str, fn: Callable[[], None]) -> dict:
        if self._worker is not None and self._worker.is_alive():
            self._push_log(f"\n[{label}] Already running, ignoring click.\n")
            return {"started": False, "reason": "busy"}

        def target() -> None:
            saved_stdout, saved_stderr = sys.stdout, sys.stderr
            sys.stdout = _BridgeWriter(self)
            sys.stderr = _BridgeWriter(self)
            try:
                self._push_log(f"\n━━━ {label} ━━━\n")
                fn()
                self._push_log(f"\n━━━ {label} done ━━━\n")
            except Exception as exc:
                self._push_log(f"\n[{label}] ERROR: {exc!r}\n")
            finally:
                sys.stdout, sys.stderr = saved_stdout, saved_stderr
                self._push_event("workerDone", {"label": label})

        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()
        self._push_event("workerStarted", {"label": label})
        return {"started": True}

    def _do_install(self, target_dir: str) -> None:
        start_offset = self._log_size()
        craftbot._full_install_frozen(target_dir, [], progress_cb=self._on_progress)
        # Spin tailing off so the worker thread completes immediately —
        # otherwise worker_busy stays True for up to 90s while the tail
        # waits for the ready marker, and JS keeps stop/repair/uninstall
        # disabled the whole time.
        self._spawn_log_tail(start_offset)

    def _do_start(self) -> None:
        start_offset = self._log_size()
        craftbot.cmd_start([])
        self._spawn_log_tail(start_offset)

    def _spawn_log_tail(self, start_offset: int) -> None:
        """Run _tail_log on a fire-and-forget daemon thread so it doesn't
        keep the worker thread alive past the action's primary work."""
        threading.Thread(
            target=self._tail_log, args=(start_offset,), daemon=True
        ).start()

    @staticmethod
    def _log_size() -> int:
        try:
            return os.path.getsize(craftbot.LOG_FILE)
        except OSError:
            return 0

    def _tail_log(self, start_offset: int, deadline_s: float = 90.0) -> None:
        """Stream new bytes appended to craftbot.log into the JS log panel.

        Stops when the ready marker appears (run.py prints this once the
        frontend + agent are both up) or after `deadline_s` seconds."""
        offset = start_offset
        end_marker = craftbot.CRAFTBOT_READY_MARKER
        end_time = time.monotonic() + deadline_s
        announced = False
        while time.monotonic() < end_time:
            try:
                size = os.path.getsize(craftbot.LOG_FILE)
            except OSError:
                time.sleep(0.3)
                continue
            if size > offset:
                if not announced:
                    self._push_log("\n— agent boot —\n")
                    announced = True
                try:
                    with open(craftbot.LOG_FILE, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset).decode("utf-8", errors="replace")
                    offset = size
                except OSError:
                    chunk = ""
                if chunk:
                    self._push_log(chunk)
                    if end_marker in chunk:
                        return
            time.sleep(0.25)
        if announced:
            self._push_log("\n— agent boot timed out (still running) —\n")

    # ── Progress + log push to JS ───────────────────────────────────────────

    def _on_progress(self, read: int, total: Optional[int]) -> None:
        self._push_event("progress", {"read": read, "total": total})

    def _push_log(self, text: str) -> None:
        if not self._window or not text:
            return
        # Strip ANSI escapes — craftbot.py captures _USE_COLOR at import time
        # and may emit them even after we redirect sys.stdout.
        clean = _ANSI_RE.sub("", text)
        try:
            self._window.evaluate_js(
                f"window.appendLog && window.appendLog({json.dumps(clean)})"
            )
        except Exception:
            # Window may have been closed mid-write — ignore.
            pass

    def _push_event(self, name: str, data: Optional[dict] = None) -> None:
        if not self._window:
            return
        payload = json.dumps(data or {})
        try:
            self._window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('py:{name}', "
                f"{{detail: {payload}}}))"
            )
        except Exception:
            pass


class _BridgeWriter:
    """File-like that mirrors stdout/stderr writes from a worker thread into
    the JS log panel via WizardAPI._push_log. Runs on the worker thread; all
    cross-thread marshalling happens inside evaluate_js()."""

    def __init__(self, api: WizardAPI) -> None:
        self._api = api

    def write(self, text: str) -> int:
        if text:
            self._api._push_log(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False
