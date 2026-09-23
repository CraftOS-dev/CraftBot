"""Saved pids are only acted on while they still name the SAME process.

A pid alone is not an identity: after a crash or reboot the OS reuses the
number, and a stale PID file / marker would make CraftBot kill (with /T, a
whole tree) some unrelated program. Each check here pairs a real process with
a record that either matches it or looks like a recycled pid.
"""

import json
import os
import subprocess
import sys
import time

import pytest

import craftbot
from agent_core.core.impl.action import cancellation
from app.ui_layer import local_llm_setup
from installer.helpers import process_start_time


@pytest.fixture
def sleeper():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)


def _alive(proc) -> bool:
    try:
        proc.wait(timeout=3)
        return False
    except subprocess.TimeoutExpired:
        return True


# ── installer.helpers.process_start_time ──────────────────────────────────


def test_start_time_of_live_and_dead_processes(sleeper):
    started = process_start_time(sleeper.pid)
    assert started is not None and abs(started - time.time()) < 60
    sleeper.kill()
    sleeper.wait(timeout=10)
    assert process_start_time(sleeper.pid) is None


# ── craftbot.py PID file ──────────────────────────────────────────────────


@pytest.fixture
def pid_file(tmp_path, monkeypatch):
    path = tmp_path / "craftbot.pid"
    monkeypatch.setattr(craftbot, "PID_FILE", str(path))
    return path


def test_pid_file_written_by_start_is_recognised(pid_file, sleeper):
    craftbot._write_pid(sleeper.pid)
    assert json.loads(pid_file.read_text())["started"] is not None
    assert craftbot._owned_pid() == sleeper.pid


def test_reused_pid_is_not_stopped(pid_file, sleeper):
    # Same pid, but recorded as starting an hour earlier: a recycled pid.
    pid_file.write_text(
        json.dumps(
            {"pid": sleeper.pid, "started": process_start_time(sleeper.pid) - 3600}
        )
    )
    craftbot.cmd_stop()
    assert _alive(sleeper), "craftbot stop killed a process it did not start"
    assert not pid_file.exists(), "the stale record should be cleaned up"


def test_legacy_pid_file_older_than_the_process_is_not_ours(pid_file, sleeper):
    # A bare-integer file from before this change, written long before this
    # pid's current process started — i.e. the number was reused since.
    pid_file.write_text(str(sleeper.pid))
    old = time.time() - 3600
    os.utime(pid_file, (old, old))
    assert craftbot._owned_pid() is None
    assert _alive(sleeper)


def test_legacy_pid_file_written_after_spawn_is_ours(pid_file, sleeper):
    time.sleep(0.2)
    pid_file.write_text(str(sleeper.pid))
    assert craftbot._owned_pid() == sleeper.pid


def test_stop_kills_the_process_we_started(pid_file, sleeper):
    craftbot._write_pid(sleeper.pid)
    craftbot.cmd_stop()
    assert not _alive(sleeper)


# ── cancellation markers ──────────────────────────────────────────────────


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(cancellation, "_marker_dir", lambda sid: tmp_path / sid)
    return "sess-1"


def test_marked_child_is_killed_on_stop(session, sleeper):
    cancellation.mark_subprocess(session, sleeper.pid)
    assert cancellation.kill_session_processes(session) == 1
    assert not _alive(sleeper)


def test_stale_marker_for_reused_pid_is_ignored(session, sleeper, tmp_path):
    marker = tmp_path / session / f"{sleeper.pid}.pid"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {"pid": sleeper.pid, "started": process_start_time(sleeper.pid) - 3600}
        )
    )
    assert cancellation.kill_session_processes(session) == 0
    assert _alive(sleeper), "a stale marker killed an unrelated process"
    assert not marker.exists()


# ── Ollama tray app ───────────────────────────────────────────────────────


def test_only_the_tray_app_our_install_launched_is_closed(monkeypatch):
    users_tray = (111, 1000.0)
    installer_tray = (222, 2000.0)
    monkeypatch.setattr(
        local_llm_setup, "_tray_app_snapshot", lambda: {users_tray, installer_tray}
    )
    killed = []
    import app.process_ledger

    monkeypatch.setattr(app.process_ledger, "kill_tree", killed.append)
    local_llm_setup._stop_tray_apps_started_since({users_tray})
    assert killed == [222]
