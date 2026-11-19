# -*- coding: utf-8 -*-
import json
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import time
import urllib.error
import urllib.request

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
    monkeypatch.setattr(craftbot._instance, "UI_FILE", tmp_path / "ui.json")
    monkeypatch.setattr(craftbot._instance, "PID_FILE", tmp_path / "craftbot.pid")


@pytest.mark.parametrize("pid", [None, 12345])
def test_stop_clears_readiness_even_after_a_previous_crash(monkeypatch, pid):
    craftbot.paths.AGENT_READY_FILE.write_text("stale process")
    craftbot._instance.write_ui(7925, 7926)
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: pid)
    monkeypatch.setattr(craftbot, "_kill_owned_pid", lambda value: None)
    craftbot.cmd_stop(quiet=True)
    assert not craftbot.paths.AGENT_READY_FILE.exists()
    assert craftbot._instance.read_ui() is None


class _FakeProcess:
    """A launched run.py: alive for `alive_polls` polls, then exited."""

    pid = 12345

    def __init__(self, alive_polls=0, code=1, on_poll=None):
        self.alive_polls = alive_polls
        self.code = code
        self.on_poll = on_poll
        self.returncode = None
        self.polls = 0

    def poll(self):
        self.polls += 1
        if self.on_poll is not None:
            self.on_poll(self.polls)
        if self.polls > self.alive_polls:
            self.returncode = self.code
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None and self.poll() is None:
            raise subprocess.TimeoutExpired("craftbot", timeout)
        return self.returncode


@pytest.fixture
def service(tmp_path, monkeypatch):
    """craftbot.py wired to a scratch state: its pid file, log, ui.json and
    ready marker, no real port sweep (it must never reach a CraftBot that is
    running on this machine), and recorders for the shortcut and browser."""
    events = []
    monkeypatch.setattr(craftbot, "_frontend_serving", lambda url: True)
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    log_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(craftbot._instance, "UI_FILE", tmp_path / "ui.json")
    monkeypatch.setattr(craftbot._instance, "PID_FILE", pid_file)
    monkeypatch.setattr(craftbot.paths, "AGENT_READY_FILE", tmp_path / ".agent-ready")
    monkeypatch.setattr(craftbot, "_stop_orphan_listeners", lambda args=None: 0)
    monkeypatch.setattr(craftbot, "_PROGRESS_EVERY_S", 0.2)
    monkeypatch.setattr(craftbot.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        craftbot,
        "_create_desktop_shortcut_unix",
        lambda args: events.append("shortcut"),
    )
    monkeypatch.setattr(
        craftbot,
        "_create_desktop_shortcut_windows",
        lambda args=None: events.append("shortcut"),
    )
    monkeypatch.setattr(
        craftbot, "_open_browser_detached", lambda url: events.append(("browser", url))
    )
    return SimpleNamespace(
        tmp=tmp_path, pid_file=pid_file, log_file=log_file, events=events
    )


def _launch(monkeypatch, process):
    launched = []

    def fake_popen(cmd, **kwargs):
        launched.append((cmd, kwargs))
        return process

    monkeypatch.setattr(craftbot.subprocess, "Popen", fake_popen)
    return launched


def test_start_reports_immediate_child_failure(service, monkeypatch, capsys):
    service.log_file.write_text("dependency failure\n", encoding="utf-8")
    _launch(monkeypatch, _FakeProcess(alive_polls=0, code=1))

    assert craftbot.cmd_start([]) is False

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output
    assert "dependency failure" in output
    assert str(service.log_file) in output
    assert not service.pid_file.exists()
    assert service.events == []


def test_start_reports_a_crash_long_after_the_first_seconds(
    service, monkeypatch, capsys
):
    # Alive through many polls (well past the old 8-second window), then
    # dead before it was ever ready: a failure, not "CRAFTBOT STARTED".
    def write_crash(polls):
        if polls == 40:
            with open(service.log_file, "a", encoding="utf-8") as f:
                f.write("Traceback: agent boot failed\n")

    _launch(monkeypatch, _FakeProcess(alive_polls=40, code=3, on_poll=write_crash))

    assert craftbot.cmd_start([]) is False

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output
    assert "exit 3" in output
    assert "agent boot failed" in output
    assert "CRAFTBOT STARTED" not in output
    assert service.events == []


def test_start_ignores_stale_ready_marker_when_child_exits(
    service, monkeypatch, capsys
):
    service.log_file.write_text(
        f"old run\n{craftbot.CRAFTBOT_READY_MARKER}\n", encoding="utf-8"
    )
    _launch(monkeypatch, _FakeProcess(alive_polls=1, code=1))

    assert craftbot.cmd_start([]) is False

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output
    assert not service.pid_file.exists()
    assert service.events == []


def test_start_waits_for_the_ui_and_opens_the_address_run_py_reports(
    service, monkeypatch, capsys
):
    # run.py moved to other ports; ui.json says where the UI really is.
    def become_ready(polls):
        if polls == 5:
            craftbot._instance.write_ui(7927, 7928)

    launched = _launch(
        monkeypatch, _FakeProcess(alive_polls=10**6, on_poll=become_ready)
    )

    assert craftbot.cmd_start([]) is True

    output = capsys.readouterr().out
    assert "CRAFTBOT STARTED" in output
    assert "http://localhost:7927" in output
    assert ("browser", "http://localhost:7927") in service.events
    cmd, kwargs = launched[0]
    assert "--no-open-browser" in cmd
    # Loopback calls must never go through a proxy, in run.py or its children.
    assert "127.0.0.1" in kwargs["env"]["NO_PROXY"]
    assert kwargs["env"]["PYTHONNOUSERSITE"] == "1"


def test_start_without_browser_does_not_open_one(service, monkeypatch, capsys):
    _launch(
        monkeypatch,
        _FakeProcess(
            alive_polls=10**6,
            on_poll=lambda n: n == 2 and craftbot._instance.write_ui(7925, 7926),
        ),
    )

    assert craftbot.cmd_start(["--no-open-browser"]) is True
    assert not [e for e in service.events if e != "shortcut"]


def test_start_that_is_still_booting_is_not_a_failure(service, monkeypatch, capsys):
    monkeypatch.setattr(craftbot, "BROWSER_READY_TIMEOUT_S", 0)
    _launch(monkeypatch, _FakeProcess(alive_polls=10**6))

    assert craftbot.cmd_start([]) is True

    output = capsys.readouterr().out
    assert "STILL STARTING" in output
    assert service.events == []


@pytest.mark.parametrize("command", ["start", "install"])
def test_cli_mode_is_refused_for_background_runs(service, monkeypatch, capsys, command):
    launched = _launch(monkeypatch, _FakeProcess())
    run = craftbot.cmd_start if command == "start" else craftbot.cmd_install

    assert run(["--cli"]) is False

    assert launched == []
    # The CLI is retired: the refusal points at the terminal edition.
    assert "python run.py --tui" in capsys.readouterr().out


@pytest.mark.parametrize(
    "platform,filename", [("darwin", "CraftBot.command"), ("linux", "CraftBot.desktop")]
)
@pytest.mark.parametrize("frozen", [False, True])
def test_unix_shortcuts_open_or_start_this_install(
    tmp_path, monkeypatch, platform, filename, frozen
):
    """Source and managed installs: the icon runs `craftbot.py open` with
    this install's state root and ports. The legacy installer EXE has no
    run.py to start, so its icon only opens the browser."""
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
    assert "7925" not in content
    assert "run.py" not in content
    assert "curl" not in content
    if frozen:
        assert "http://localhost:8123" in content
        assert "craftbot.py" not in content
        if platform == "darwin":
            assert content == "#!/bin/sh\nexec open http://localhost:8123\n"
        else:
            assert "Exec=" in content
    else:
        assert "craftbot.py" in content
        assert " open " in content
        assert "--state-root=" in content
        assert "--frontend-port=8123" in content
        assert "--backend-port 8124" in content
        if platform == "darwin":
            assert content.startswith("#!/bin/sh\nexec ")
        else:
            assert "Exec=" in content
            assert "Terminal=false" in content


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


def test_install_never_closes_the_console_on_failure(service, monkeypatch, capsys):
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(service.tmp))
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: False)
    monkeypatch.setattr(
        craftbot,
        "_close_console_window",
        lambda: (_ for _ in ()).throw(AssertionError("should not close")),
    )
    monkeypatch.setattr(craftbot, "_console_owned_alone", lambda: False)

    assert craftbot.cmd_install([]) is False
    assert "Full log" in capsys.readouterr().out


def test_closing_the_install_window_never_kills_another_process(monkeypatch, capsys):
    monkeypatch.setattr(craftbot, "_console_owned_alone", lambda: False)
    monkeypatch.setattr(
        craftbot.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned a process")),
    )
    monkeypatch.setattr(
        craftbot.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran a process")),
    )

    craftbot._close_console_window()

    assert "You can close this window now." in capsys.readouterr().out


# ── service files ─────────────────────────────────────────────────────────


def test_systemd_unit_carries_the_install_environment(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    base = tmp_path / "Craft Bot 100%"
    python = "/opt/My Python/bin/python3.10"
    monkeypatch.setattr(craftbot, "_PLATFORM", "linux")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(base))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(base / "run.py"))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: python)
    monkeypatch.setattr(craftbot, "_create_desktop_shortcut_unix", lambda *a: None)
    monkeypatch.setattr(craftbot, "_print_linger_hint", lambda: None)
    monkeypatch.setattr(
        craftbot.os.path, "expanduser", lambda p: p.replace("~", str(home))
    )
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:p%40ss@proxy.corp:3128")
    calls = []
    monkeypatch.setattr(craftbot.subprocess, "run", lambda cmd, **k: calls.append(cmd))

    assert craftbot._install_linux(["--no-open-browser"]) is True

    unit = (home / ".config/systemd/user/craftbot.service").read_text(encoding="utf-8")
    # systemd C-unescapes quoted words and expands % specifiers.
    run_py = str(base / "run.py").replace("\\", "\\\\").replace("%", "%%")
    assert f'ExecStart="{python}" "{run_py}" "--no-open-browser" "--service"' in unit
    assert 'Environment="PATH=/opt/homebrew/bin:/usr/bin"' in unit
    # Network settings reach the service; % is escaped for systemd.
    assert 'Environment="HTTPS_PROXY=http://user:p%%40ss@proxy.corp:3128"' in unit
    assert ["systemctl", "--user", "enable", "craftbot"] in calls


def test_linux_without_systemd_explains_how_to_enable_it(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setattr(craftbot, "_PLATFORM", "linux")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "_systemd_running", lambda: False)
    monkeypatch.setattr(craftbot, "_is_wsl", lambda: True)
    monkeypatch.setattr(
        craftbot.os.path, "expanduser", lambda p: p.replace("~", str(home))
    )

    def no_systemctl(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(craftbot.subprocess, "run", no_systemctl)

    assert craftbot._install_linux([]) is False

    output = capsys.readouterr().out
    assert "systemd=true" in output
    assert "--no-autostart" in output


def test_launchd_plist_carries_the_install_environment(tmp_path, monkeypatch):
    home = tmp_path / "home"
    base = tmp_path / "R&D <CraftBot>"
    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(base))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(base / "run.py"))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: "/usr/bin/python3")
    monkeypatch.setattr(craftbot, "_create_desktop_shortcut_unix", lambda *a: None)
    monkeypatch.setattr(
        craftbot.os.path, "expanduser", lambda p: p.replace("~", str(home))
    )
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    monkeypatch.setenv("NO_PROXY", "corp.local,10.0.0.0/8")

    assert craftbot._install_macos(["--no-open-browser"]) is True

    plist_file = home / "Library/LaunchAgents/com.craftbot.agent.plist"
    with open(plist_file, "rb") as f:
        plist = plistlib.load(f)
    assert plist["ProgramArguments"][:4] == [
        "/usr/bin/python3",
        str(base / "run.py"),
        "--no-open-browser",
        "--service",
    ]
    assert plist["WorkingDirectory"] == str(base)
    assert plist["EnvironmentVariables"]["PATH"] == "/opt/homebrew/bin:/usr/bin"
    assert plist["EnvironmentVariables"]["NO_PROXY"] == "corp.local,10.0.0.0/8"


def test_windows_login_task_carries_network_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(craftbot, "_PLATFORM", "win32")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "_python_exe", lambda: r"C:\Py\pythonw.exe")
    monkeypatch.setattr(craftbot, "_remove_windows_registry", lambda: True)
    monkeypatch.setattr(
        craftbot, "_create_desktop_shortcut_windows", lambda args=None: None
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:3128")
    monkeypatch.setenv("PIP_INDEX_URL", "https://mirror.corp/simple")
    arguments = []

    def fake_run(cmd, **kwargs):
        if cmd[0] == "whoami":
            return subprocess.CompletedProcess(cmd, 0, '"host\\user","S-1-5-21-1"\n')
        task = ET.fromstring(
            Path(cmd[cmd.index("/xml") + 1]).read_text(encoding="utf-16")
        )
        arguments.append(task.findtext("{*}Actions/{*}Exec/{*}Arguments"))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(craftbot.subprocess, "run", fake_run)

    assert craftbot._install_windows(["--no-open-browser"]) is True

    # The login task starts run.py --service, which loads the saved settings.
    assert "--service" in arguments[0].split()
    saved = json.loads((tmp_path / "service-env.json").read_text(encoding="utf-8"))
    assert saved["HTTPS_PROXY"] == "http://proxy.corp:3128"
    assert saved["PIP_INDEX_URL"] == "https://mirror.corp/simple"


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

    monkeypatch.setattr(
        craftbot._instance, "loopback_opener", lambda: SimpleNamespace(open=fake)
    )
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
    monkeypatch.setattr(
        craftbot, "_create_desktop_shortcut_windows", lambda args=None: None
    )
    monkeypatch.setattr(craftbot, "_create_desktop_shortcut_unix", lambda args: None)
    monkeypatch.setattr(
        craftbot,
        "_wait_until_ready",
        lambda proc, offset, timeout: "ready" if agent_ready else "timeout",
    )
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: None)
    monkeypatch.setattr(craftbot, "_open_browser_detached", opened.append)

    def fake_popen(cmd, **kwargs):
        # The child announces itself, so the early-exit check returns at once.
        kwargs["stdout"].write(f"{craftbot.CRAFTBOT_READY_MARKER}\n")
        kwargs["stdout"].flush()
        return _FakeProcess(alive_polls=10**6)

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
    assert url_lines and all("when it finishes" in line for line in url_lines)
    assert "craftbot.py logs" in output


def test_start_without_browser_still_checks_the_announced_url(
    tmp_path, monkeypatch, capsys
):
    opened = _start_with_running_child(tmp_path, monkeypatch)
    probed = _fake_urlopen(monkeypatch, _FakeResponse(_UI_HTML))

    assert craftbot.cmd_start(["--no-open-browser"]) is True

    output = capsys.readouterr().out
    assert probed == ["http://localhost:7925"]
    assert opened == []
    assert "Waiting for the browser interface" in output
