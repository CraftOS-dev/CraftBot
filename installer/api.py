"""Lifecycle actions behind the installer window.

Each method is called straight from installer/ui/window.py. Install, start,
stop, repair and uninstall spawn a worker thread and return immediately;
their output is buffered here and the window collects it with
drain_output() on its own tick.

Why a thread per action: an install runs for minutes, and doing it on Tk's
main loop would freeze the window — no repaint, no log, no close button —
for the entire time, which is exactly when the user most needs to see that
something is happening.

Note the direction of travel: the worker does NOT push to the UI, it
buffers. An earlier version pushed via pywebview's window.evaluate_js(), and
when the UI changed that channel disappeared silently — the install ran to
completion with an empty output panel, because the push no-opped whenever
there was no window to push into. Polling cannot fail that way.

This class deliberately knows nothing about Tk. Everything it exposes is
plain dict/list/str/int, so the command-line path exercises the same code.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import Callable, Optional

import craftbot

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class WizardAPI:
    """The installer's actions, with no UI attached.

    Kept free of Tk imports on purpose: this is what the window calls, and
    it is also what a headless install path can call, so the two cannot
    drift apart.
    """

    #: Cap on buffered log lines. A pip install emits tens of thousands, and
    #: a UI that stopped polling must not grow this without limit.
    _OUTPUT_MAX = 5000

    def __init__(self) -> None:
        # Log lines waiting for the UI to collect, plus the most recent
        # progress event. Written from the worker thread, read from the UI
        # thread, so both go through the lock.
        self._output: list = []
        self._progress: Optional[dict] = None
        self._output_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

    # ── State queries ───────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return the current install/run state. Polled about once a second.

        Called from a worker thread, not the UI thread: on Windows this
        shells out to `tasklist`, which is far too slow to run on Tk's main
        loop every second.

        Mirrors the old Tk wizard's state machine — deliberately checks that
        the install is actually launchable, rather than `craftbot._is_installed()`
        which returns True for stale Task Scheduler entries from older installs.

        `launch_command()` handles both layouts: a schema-2 install (a source
        tree plus an interpreter) and a legacy schema-1 frozen bundle (an EXE).
        Testing `os.path.isfile(installed_path)` directly would report every
        schema-2 install as missing, because there installed_path is a
        directory.
        """
        installed = bool(
            craftbot._metadata.launch_command(craftbot.INSTALL_METADATA_FILE)
        )
        pid = craftbot._read_pid()
        running = bool(pid and craftbot._is_running(pid))
        ready = running and self._agent_ready()
        if installed and running:
            # A live PID is NOT a usable CraftBot — see _agent_ready().
            state = "installed_running" if ready else "installed_starting"
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
            # Which boot step it is on, so a slow start reads as progress
            # rather than a hang.
            "detail": self._starting_detail() if state == "installed_starting" else "",
        }

    #: run.py prints "  [ 2/8] Starting agent backend...      ✓" and the agent
    #: prints "  [ 3/7] Initializing agent...                 ✓".
    _STEP_RE = re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]\s*([^\r\n]*)")

    @classmethod
    def _starting_detail(cls) -> str:
        """The most recent boot step from the log, e.g. "Loading skills".

        A first run downloads an embedding model, so "Starting…" can sit
        there for minutes. Without naming the current step that is
        indistinguishable from a hang — which is exactly what it looked like.
        """
        try:
            size = os.path.getsize(craftbot.LOG_FILE)
            with open(craftbot.LOG_FILE, "rb") as fh:
                fh.seek(max(0, size - cls._READY_TAIL_BYTES))
                tail = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        banner = tail.rfind("CraftBot service started at")
        if banner != -1:
            tail = tail[banner:]
        matches = cls._STEP_RE.findall(tail)
        if not matches:
            return ""
        step, total, message = matches[-1]
        # The line is padded out to a fixed width before its tick, so cut at
        # the first run of two or more spaces: "Loading skills   ✓" -> "Loading
        # skills". Single spaces inside the message itself must survive.
        message = re.split(r"\s{2,}", message.strip())[0]
        message = message.replace("...", "").strip(" .·✓")
        return f"{message} ({step}/{total})" if message else ""

    #: How much of the tail of craftbot.log to search for the ready marker.
    #: The banner and the boot sequence are the last thing written, so this is
    #: generous — and bounded, because the log grows without limit and this
    #: runs once a second.
    _READY_TAIL_BYTES = 64 * 1024

    @classmethod
    def _agent_ready(cls) -> bool:
        """True once the agent has logged its ready marker for THIS run.

        The window used to report "Running" the moment a PID existed. But
        run.py then spends a noticeable while initialising the agent, MCP
        servers, skills, integrations and the scheduler — so the user was
        told CraftBot was up and sent to a browser tab that was not serving
        yet.

        Two signals, in order:

          1. app.paths.AGENT_READY_FILE, written by the agent itself. This is
             authoritative — cmd_start deletes it before each launch, so it can
             only mean "this run is up".
          2. The ready banner in the log, for an older installed agent that
             predates the marker file.

        The log alone is not enough: run.py's stdout is a log FILE here, so
        Python block-buffers it, and the banner can sit unflushed for a long
        time after the agent is actually serving.

        The log check is still scoped to the last service-start banner so a
        marker from a previous session cannot make a still-booting agent look
        finished.
        """
        try:
            from app import paths

            if paths.AGENT_READY_FILE.is_file():
                return True
        except Exception:
            pass
        try:
            size = os.path.getsize(craftbot.LOG_FILE)
            with open(craftbot.LOG_FILE, "rb") as fh:
                fh.seek(max(0, size - cls._READY_TAIL_BYTES))
                tail = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return False
        banner = tail.rfind("CraftBot service started at")
        if banner != -1:
            tail = tail[banner:]
        return craftbot.CRAFTBOT_READY_MARKER in tail

    def get_default_install_location(self) -> str:
        return craftbot.default_install_location()

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
        """Buffer a log line for the UI to collect.

        Buffering rather than pushing is deliberate — see the module
        docstring for the empty-output-panel bug that pushing caused.
        """
        if not text:
            return
        # Strip ANSI escapes — craftbot.py captures _USE_COLOR at import time
        # and may emit them even after we redirect sys.stdout.
        clean = _ANSI_RE.sub("", text)
        with self._output_lock:
            self._output.append(clean)
            # Bound the buffer: a pip install is tens of thousands of lines,
            # and a page that stops polling must not grow it without limit.
            if len(self._output) > self._OUTPUT_MAX:
                del self._output[: len(self._output) - self._OUTPUT_MAX]

    def _push_event(self, name: str, data: Optional[dict] = None) -> None:
        """Record an event (currently only progress) for the next poll."""
        if name == "progress":
            with self._output_lock:
                self._progress = dict(data or {})

    def drain_output(self) -> dict:
        """Return buffered log lines and the latest progress, then clear.

        Called by the window several times a second. Draining rather than
        accumulating keeps each hand-off small during a long install.
        """
        with self._output_lock:
            lines = self._output
            self._output = []
            progress = self._progress
            self._progress = None
        return {"lines": lines, "progress": progress}


class _BridgeWriter:
    """File-like that redirects a worker thread's stdout/stderr into the log
    buffer. craftbot.py's install functions print their progress, so this is
    what makes that progress visible in the window without changing them."""

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
