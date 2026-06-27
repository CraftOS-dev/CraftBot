# -*- coding: utf-8 -*-
import shlex
import subprocess
import sys

import pytest
import craftbot


class _ExitedProcess:
    pid = 12345

    def wait(self, timeout=None):
        return 1


class _RunningProcess:
    pid = 23456

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("craftbot", timeout)


def test_start_reports_immediate_child_failure(tmp_path, monkeypatch, capsys):
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    log_file.write_text("dependency failure\n", encoding="utf-8")
    events = []

    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(
        craftbot, "_create_desktop_shortcut_unix", lambda: events.append("shortcut")
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


def test_start_reports_success_for_long_running_child(tmp_path, monkeypatch, capsys):
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    events = []

    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(
        craftbot, "_create_desktop_shortcut_unix", lambda: events.append("shortcut")
    )
    monkeypatch.setattr(
        craftbot, "_open_browser_detached", lambda url: events.append(("browser", url))
    )

    def fake_popen(*args, **kwargs):
        return _RunningProcess()

    monkeypatch.setattr(craftbot.subprocess, "Popen", fake_popen)

    assert craftbot.cmd_start([]) is True

    output = capsys.readouterr().out
    assert "CRAFTBOT STARTED" in output
    assert pid_file.read_text() == "23456"
    assert events == ["shortcut", ("browser", craftbot.BROWSER_URL)]


def test_macos_source_shortcut_opens_or_starts_service(tmp_path, monkeypatch, capsys):
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

    craftbot._create_desktop_shortcut_unix()

    shortcut = desktop / "CraftBot.command"
    content = shortcut.read_text()
    assert f"cd {shlex.quote(str(base_dir))}" in content
    assert "curl -fsS http://localhost:7925" in content
    assert "open http://localhost:7925" in content
    assert f"exec {shlex.quote(python_exe)} craftbot.py start" in content

    output = capsys.readouterr().out
    assert "Desktop shortcut created" in output


def test_macos_frozen_shortcut_only_opens_url(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "IS_FROZEN", True)
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))

    craftbot._create_desktop_shortcut_unix()

    content = (desktop / "CraftBot.command").read_text()
    assert content == "#!/bin/sh\nopen http://localhost:7925\n"
    assert "craftbot.py start" not in content


def test_linux_shortcut_remains_url_opener(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    monkeypatch.setattr(craftbot, "_PLATFORM", "linux")
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))

    craftbot._create_desktop_shortcut_unix()

    content = (desktop / "CraftBot.desktop").read_text()
    assert "Exec=" in content
    assert "http://localhost:7925" in content
    assert "craftbot.py start" not in content


def test_cli_start_exits_nonzero_when_start_fails(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["craftbot.py", "start"])
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: False)

    with pytest.raises(SystemExit) as exc:
        craftbot.main()

    assert exc.value.code == 1


def test_cli_restart_exits_nonzero_when_restart_fails(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["craftbot.py", "restart"])
    monkeypatch.setattr(craftbot, "cmd_restart", lambda args: False)

    with pytest.raises(SystemExit) as exc:
        craftbot.main()

    assert exc.value.code == 1
