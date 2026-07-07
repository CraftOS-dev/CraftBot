# -*- coding: utf-8 -*-
import shlex
import subprocess
import sys

import pytest

import craftbot
from startup_constants import CRAFTBOT_READY_MARKER


class _ExitedProcess:
    pid = 12345

    def wait(self, timeout=None):
        return 1


class _RunningProcess:
    pid = 23456

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("craftbot", timeout)


class _DelayedFailureProcess:
    pid = 34567

    def __init__(self):
        self.calls = 0

    def wait(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired("craftbot", timeout)
        return 1


def test_start_reports_immediate_child_failure(tmp_path, monkeypatch, capsys):
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    log_file.write_text("dependency failure\n", encoding="utf-8")
    events = []

    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(
        craftbot, "_create_desktop_shortcut_unix", lambda args: events.append("shortcut")
    )
    monkeypatch.setattr(
        craftbot, "_open_browser_detached", lambda url: events.append("browser")
    )

    def fake_popen(*args, **kwargs):
        return _ExitedProcess()

    monkeypatch.setattr(craftbot.subprocess, "Popen", fake_popen)

    assert craftbot.cmd_start([]) is False

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output
    assert "dependency failure" in output
    assert not pid_file.exists()
    assert events == []


def test_macos_source_shortcut_uses_custom_backend_port(
    tmp_path, monkeypatch, capsys
):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    base_dir = tmp_path / "Craft Bot"
    base_dir.mkdir()
    python_exe = "/Applications/Python 3.10/bin/python3.10"

    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: python_exe)

    craftbot._create_desktop_shortcut_unix(["--backend-port", "8123"])

    shortcut = desktop / "CraftBot.command"
    content = shortcut.read_text()
    assert f"cd {shlex.quote(str(base_dir))}" in content
    assert "curl -fsS http://localhost:7925" in content
    assert "backend_status=$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:8123" in content
    assert "[ \"$backend_status\" -ge 100 ]" in content
    assert "[ \"$backend_status\" -lt 500 ]" in content
    assert "curl -fsS http://localhost:8123" not in content
    assert "http://localhost:7926" not in content
    assert "open http://localhost:7925" in content
    assert f"exec {shlex.quote(python_exe)} craftbot.py start --backend-port 8123" in content

    output = capsys.readouterr().out
    assert "Desktop shortcut created" in output


def test_macos_source_shortcut_accepts_equals_backend_port(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    base_dir = tmp_path / "CraftBot"
    base_dir.mkdir()

    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: "/usr/local/bin/python3.10")

    craftbot._create_desktop_shortcut_unix(["--backend-port=8123"])

    content = (desktop / "CraftBot.command").read_text()
    assert "backend_status=$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:8123" in content
    assert "craftbot.py start --backend-port=8123" in content


def test_macos_frozen_shortcut_starts_installed_agent_executable(
    tmp_path, monkeypatch
):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    base_dir = tmp_path / "CraftBot"
    base_dir.mkdir()
    installed_agent = "/Applications/CraftBot/CraftBot Agent"

    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "IS_FROZEN", True)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: "/bad/python")
    monkeypatch.setattr(craftbot, "installed_exe_path", lambda: installed_agent)

    craftbot._create_desktop_shortcut_unix(["--frontend-port", "9000"])

    content = (desktop / "CraftBot.command").read_text()
    assert f"exec {shlex.quote(installed_agent)} --frontend-port 9000" in content
    assert "craftbot.py start" not in content
    assert "/bad/python" not in content


def test_start_ignores_stale_ready_marker_when_child_exits(
    tmp_path, monkeypatch, capsys
):
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    log_file.write_text(f"old run\n{CRAFTBOT_READY_MARKER}\n", encoding="utf-8")
    events = []

    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(
        craftbot, "_create_desktop_shortcut_unix", lambda args: events.append("shortcut")
    )
    monkeypatch.setattr(
        craftbot, "_open_browser_detached", lambda url: events.append(("browser", url))
    )

    def fake_popen(*args, **kwargs):
        return _DelayedFailureProcess()

    monkeypatch.setattr(craftbot.subprocess, "Popen", fake_popen)

    assert craftbot.cmd_start([]) is False

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output
    assert not pid_file.exists()
    assert events == []


def test_cli_start_exits_nonzero_when_start_fails(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["craftbot.py", "start"])
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: False)

    with pytest.raises(SystemExit) as exc:
        craftbot.main()

    assert exc.value.code == 1


def test_source_install_returns_false_when_service_start_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "_is_installed", lambda: True)
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: False)
    monkeypatch.setattr(
        craftbot,
        "_close_console_window",
        lambda: (_ for _ in ()).throw(AssertionError("should not close")),
    )

    assert craftbot.cmd_install([]) is False

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output


def test_ready_marker_constant_is_shared():
    assert CRAFTBOT_READY_MARKER == "CRAFTBOT IS READY"
