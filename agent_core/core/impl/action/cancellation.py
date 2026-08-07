# -*- coding: utf-8 -*-
"""
core.impl.action.cancellation

Per-session registry of kill handles for force-stopping a run.

Cancelling a turn's asyncio task aborts LLM calls and async actions, but it
cannot reach real OS work already in flight: a shell command spawned by
``run_shell`` (blocking a pool thread in ``communicate()``) or the python
child of a sandboxed action (spawned inside a ProcessPoolExecutor worker).
This module is the one place such work is registered so a user stop can
kill it.

Two mechanisms, one kill call:

- ``register_process`` / ``unregister_process``: in-process registry of
  ``subprocess.Popen`` handles, used by actions running in the main process
  (thread-pool actions like ``run_shell``).
- ``mark_subprocess`` / ``unmark_subprocess``: pid marker FILES under the
  system temp dir, used by code running in a DIFFERENT process (the
  sandboxed-action pool worker) where no in-memory registry can be shared.

``kill_session_processes(session_id)`` kills both kinds, entire process
trees included, and is safe to call at any time (missing/exited processes
are ignored). It is blocking (taskkill / killpg) — call it from a worker
thread, not the event loop.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict

from agent_core.utils.logger import logger

_lock = threading.Lock()
# session_id -> {pid: Popen}. Popen handles registered by in-process actions.
_procs: Dict[str, Dict[int, subprocess.Popen]] = {}


def _marker_dir(session_id: str) -> Path:
    return Path(tempfile.gettempdir()) / "craftbot_run_cancel" / session_id


# ─────────────────────── In-process Popen registry ───────────────────────


def register_process(session_id: str, proc: subprocess.Popen) -> None:
    """Register a live child process as killable when this session is stopped."""
    if not session_id or proc is None or proc.pid is None:
        return
    with _lock:
        _procs.setdefault(session_id, {})[proc.pid] = proc


def unregister_process(session_id: str, proc: subprocess.Popen) -> None:
    """Remove a child process from the kill set (it finished normally)."""
    if not session_id or proc is None or proc.pid is None:
        return
    with _lock:
        session = _procs.get(session_id)
        if session:
            session.pop(proc.pid, None)
            if not session:
                _procs.pop(session_id, None)


# ─────────────────────── Cross-process pid markers ───────────────────────


def mark_subprocess(session_id: str, pid: int) -> None:
    """Record a child pid from ANOTHER process (e.g. a pool worker).

    The main process cannot hold the Popen handle, so the pid is written as
    a marker file that ``kill_session_processes`` scans.
    """
    if not session_id or not pid:
        return
    try:
        d = _marker_dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pid}.pid").write_text(str(pid), encoding="utf-8")
    except Exception:
        pass  # markers are best-effort; never fail the action over them


def unmark_subprocess(session_id: str, pid: int) -> None:
    """Remove a pid marker (the child exited normally)."""
    if not session_id or not pid:
        return
    try:
        (_marker_dir(session_id) / f"{pid}.pid").unlink(missing_ok=True)
    except Exception:
        pass


# ─────────────────────── Kill ───────────────────────


def _kill_tree(pid: int) -> None:
    """Kill a process and its descendants. Missing processes are fine."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            import signal

            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGKILL)
    except Exception as e:
        logger.debug(f"[CANCEL] Kill of pid {pid} failed (likely already gone): {e}")


def kill_session_processes(session_id: str) -> int:
    """Force-kill every process registered/marked for a session.

    Returns the number of kill targets attempted. Blocking — run in a
    worker thread.
    """
    if not session_id:
        return 0

    with _lock:
        handles = list(_procs.pop(session_id, {}).values())

    killed = 0
    for proc in handles:
        if proc.poll() is None:
            _kill_tree(proc.pid)
            killed += 1
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    # Cross-process markers (sandboxed action children).
    try:
        d = _marker_dir(session_id)
        if d.is_dir():
            for marker in d.glob("*.pid"):
                try:
                    _kill_tree(int(marker.stem))
                    killed += 1
                except ValueError:
                    pass
                marker.unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"[CANCEL] Marker sweep failed for {session_id}: {e}")

    if killed:
        logger.info(
            f"[CANCEL] Force-killed {killed} process tree(s) for session {session_id}"
        )
    return killed
