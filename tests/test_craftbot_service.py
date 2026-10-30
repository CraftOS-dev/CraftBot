# -*- coding: utf-8 -*-
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

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


def test_macos_source_shortcut_uses_custom_backend_port(tmp_path, monkeypatch, capsys):
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
    assert (
        "backend_status=$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:8123"
        in content
    )
    assert '[ "$backend_status" -ge 100 ]' in content
    assert '[ "$backend_status" -lt 500 ]' in content
    assert "curl -fsS http://localhost:8123" not in content
    assert "http://localhost:7926" not in content
    assert "open http://localhost:7925" in content
    assert (
        f"exec {shlex.quote(python_exe)} craftbot.py start --backend-port 8123"
        in content
    )

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
    assert (
        "backend_status=$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:8123"
        in content
    )
    assert "craftbot.py start --backend-port=8123" in content


def test_macos_frozen_shortcut_starts_installed_agent_executable(tmp_path, monkeypatch):
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
    monkeypatch.setattr(craftbot, "_installed_launch", lambda: [installed_agent])

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


# ─── Browser interface readiness (#488) ───────────────────────────────────────

_UI_HTML = b'<!DOCTYPE html><html><body><div id="root"></div></body></html>'


class _FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code):
    return urllib.error.HTTPError("http://localhost:7925", code, "err", None, None)


def _fake_urlopen(monkeypatch, *outcomes):
    """Patch urlopen to play `outcomes` in order (the last one repeats)."""
    calls = []

    def fake(url, timeout=None):
        outcome = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


class _FakeClock:
    """Stands in for craftbot.time: sleeping advances time instantly."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def __getattr__(self, name):
        return getattr(time, name)  # strftime etc. stay real


@pytest.mark.parametrize("code", [404, 403, 500, 503])
def test_frontend_error_response_is_not_ready(monkeypatch, code):
    _fake_urlopen(monkeypatch, _http_error(code))

    assert craftbot._frontend_serving("http://localhost:7925") is False


def test_frontend_200_without_ui_is_not_ready(monkeypatch):
    # e.g. the directory listing of a dist/ with no index.html
    _fake_urlopen(monkeypatch, _FakeResponse(b"<html>Directory listing</html>"))

    assert craftbot._frontend_serving("http://localhost:7925") is False


def test_frontend_serving_ui_is_ready(monkeypatch):
    _fake_urlopen(monkeypatch, _FakeResponse(_UI_HTML))

    assert craftbot._frontend_serving("http://localhost:7925") is True


def test_wait_for_frontend_retries_through_startup_failures(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(craftbot, "time", clock)
    calls = _fake_urlopen(
        monkeypatch,
        urllib.error.URLError("connection refused"),
        _http_error(404),
        _FakeResponse(_UI_HTML),
    )

    assert craftbot._wait_for_frontend("http://localhost:7925", timeout=30) is True
    assert len(calls) == 3


def test_wait_for_frontend_gives_up_at_the_deadline(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(craftbot, "time", clock)
    calls = _fake_urlopen(monkeypatch, _http_error(404))

    assert craftbot._wait_for_frontend("http://localhost:7925", timeout=5) is False
    assert sum(clock.sleeps) <= 5
    assert len(calls) == len(clock.sleeps) + 1


def _start_with_running_child(tmp_path, monkeypatch, agent_ready=True):
    """cmd_start against a child that boots; returns the browser-open log."""
    opened = []
    monkeypatch.setattr(craftbot, "PID_FILE", str(tmp_path / "craftbot.pid"))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(tmp_path / "craftbot.log"))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(craftbot, "cmd_stop", lambda quiet=False, args=None: False)
    monkeypatch.setattr(craftbot, "_clear_agent_ready", lambda: None)
    monkeypatch.setattr(craftbot, "_create_desktop_shortcut_windows", lambda: None)
    monkeypatch.setattr(craftbot, "_create_desktop_shortcut_unix", lambda args: None)
    monkeypatch.setattr(
        craftbot, "_wait_for_ready_marker", lambda offset, timeout: agent_ready
    )
    monkeypatch.setattr(craftbot, "_open_browser_detached", opened.append)

    def fake_popen(cmd, **kwargs):
        # The child announces itself, so the early-exit check returns at once.
        kwargs["stdout"].write(f"{craftbot.CRAFTBOT_READY_MARKER}\n")
        kwargs["stdout"].flush()
        return _RunningProcess()

    monkeypatch.setattr(craftbot.subprocess, "Popen", fake_popen)
    return opened


def test_start_does_not_show_url_while_frontend_returns_404(
    tmp_path, monkeypatch, capsys
):
    opened = _start_with_running_child(tmp_path, monkeypatch)
    monkeypatch.setattr(craftbot, "time", _FakeClock())
    _fake_urlopen(monkeypatch, _http_error(404))

    # Still a successful start: the agent is running, only the UI is not.
    assert craftbot.cmd_start([]) is True

    output = capsys.readouterr().out
    assert opened == []
    assert "not responding at http://localhost:7925" in output
    url_lines = [line for line in output.splitlines() if "localhost:7925" in line]
    assert all("not responding" in line for line in url_lines)


def test_start_shows_url_only_after_frontend_serves_ui(tmp_path, monkeypatch, capsys):
    opened = _start_with_running_child(tmp_path, monkeypatch)
    probed = _fake_urlopen(monkeypatch, _FakeResponse(_UI_HTML))

    assert craftbot.cmd_start(["--frontend-port", "8925"]) is True

    output = capsys.readouterr().out
    assert probed == ["http://localhost:8925"]
    assert opened == ["http://localhost:8925"]
    assert output.index("Waiting for the browser interface") < output.index(
        "http://localhost:8925"
    )


def test_start_agent_timeout_skips_frontend_probe_and_explains(
    tmp_path, monkeypatch, capsys
):
    opened = _start_with_running_child(tmp_path, monkeypatch, agent_ready=False)
    probed = _fake_urlopen(monkeypatch, _FakeResponse(_UI_HTML))

    assert craftbot.cmd_start([]) is True

    output = capsys.readouterr().out
    assert probed == []
    assert opened == []
    # The URL only appears as "open it once it finishes", never as ready.
    url_lines = [line for line in output.splitlines() if "localhost:7925" in line]
    assert url_lines and all("Still starting" in line for line in url_lines)
    assert "craftbot.py logs" in output


def test_start_without_browser_neither_waits_nor_probes(tmp_path, monkeypatch, capsys):
    opened = _start_with_running_child(tmp_path, monkeypatch)
    probed = _fake_urlopen(monkeypatch, _FakeResponse(_UI_HTML))

    assert craftbot.cmd_start(["--no-open-browser"]) is True

    output = capsys.readouterr().out
    assert probed == []
    assert opened == []
    assert "Waiting for the browser interface" not in output
