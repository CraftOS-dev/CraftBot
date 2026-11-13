# -*- coding: utf-8 -*-
import subprocess
import sys

import pytest

import craftbot


@pytest.fixture(autouse=True)
def configured_context_window():
    """Service management runs before the agent's model dependencies exist."""


@pytest.fixture(autouse=True)
def isolated_service_state(tmp_path, monkeypatch):
    monkeypatch.setattr(craftbot, "PID_FILE", str(tmp_path / "craftbot.pid"))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(tmp_path / "craftbot.log"))
    monkeypatch.setattr(craftbot, "_orphan_listeners", lambda args=None: [])
    monkeypatch.setattr(craftbot.paths, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(craftbot.paths, "AGENT_READY_FILE", tmp_path / ".agent-ready")


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
        craftbot,
        "_create_desktop_shortcut_unix",
        lambda args: events.append("shortcut"),
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


@pytest.mark.parametrize(
    "platform,filename", [("darwin", "CraftBot.command"), ("linux", "CraftBot.desktop")]
)
@pytest.mark.parametrize("frozen", [False, True])
def test_unix_shortcuts_only_open_the_configured_url(
    tmp_path, monkeypatch, platform, filename, frozen
):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(craftbot, "_PLATFORM", platform)
    monkeypatch.setattr(craftbot, "IS_FROZEN", frozen)
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))
    # Replace an older shortcut which may have started the app itself.
    (desktop / filename).write_text("old shortcut: craftbot.py start")
    craftbot._create_desktop_shortcut_unix(
        ["--frontend-port=8123", "--backend-port", "8124"]
    )
    content = (desktop / filename).read_text()
    assert "http://localhost:8123" in content
    assert "7925" not in content
    assert "craftbot.py" not in content
    assert "run.py" not in content
    assert "curl" not in content
    if platform == "darwin":
        assert content == "#!/bin/sh\nexec open http://localhost:8123\n"
    else:
        assert "Exec=" in content


def test_start_ignores_stale_ready_marker_when_child_exits(
    tmp_path, monkeypatch, capsys
):
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    log_file.write_text(
        f"old run\n{craftbot.CRAFTBOT_READY_MARKER}\n", encoding="utf-8"
    )
    events = []

    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(
        craftbot,
        "_create_desktop_shortcut_unix",
        lambda args: events.append("shortcut"),
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
