# -*- coding: utf-8 -*-
"""`craftbot.py open`: what the desktop icon runs.

It must open the browser when CraftBot runs, wait for a CraftBot that is
already starting instead of starting a second one, and start CraftBot when
nothing runs. Everything here works on a scratch state root and never reaches
a CraftBot running on this machine.
"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import craftbot

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def configured_context_window():
    """Service management runs before the agent's model dependencies exist."""


@pytest.fixture
def opener(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(craftbot, "PID_FILE", str(tmp_path / "craftbot.pid"))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(tmp_path / "craftbot.log"))
    monkeypatch.setattr(craftbot._instance, "UI_FILE", tmp_path / "ui.json")
    monkeypatch.setattr(craftbot._instance, "PID_FILE", tmp_path / "craftbot.pid")
    monkeypatch.setattr(craftbot.paths, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(craftbot, "_orphan_listeners", lambda args=None: [])
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        craftbot, "_open_browser_detached", lambda url: events.append(("browser", url))
    )

    def fake_start(args):
        events.append(("start", list(args)))
        return True

    monkeypatch.setattr(craftbot, "cmd_start", fake_start)
    # A terminal, so the progress window is never opened by these tests.
    monkeypatch.setattr(craftbot, "_has_console", lambda: True)
    return SimpleNamespace(tmp=tmp_path, events=events)


def _answering(monkeypatch, urls):
    monkeypatch.setattr(
        craftbot._instance, "http_answers", lambda url, timeout=2.0: url in urls
    )


def test_running_craftbot_is_only_opened(opener, monkeypatch):
    craftbot._instance.write_ui(7931, 7932)
    _answering(monkeypatch, {"http://localhost:7931"})

    assert craftbot.cmd_open([]) is True
    assert opener.events == [("browser", "http://localhost:7931")]


def test_nothing_running_starts_craftbot_with_the_icon_ports(opener, monkeypatch):
    _answering(monkeypatch, set())
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: None)

    args = ["--frontend-port", "8123", "--backend-port", "8124"]
    assert craftbot.cmd_open(args) is True
    # Started once; cmd_start opens the browser itself when the UI answers.
    assert opener.events == [("start", args)]


def test_a_starting_craftbot_is_waited_for_not_replaced(opener, monkeypatch):
    """The login start (or an earlier click) is still booting."""
    answers = {"n": 0}

    def answers_after_three_checks(url, timeout=2.0):
        answers["n"] += 1
        return answers["n"] > 3

    craftbot._instance.write_ui(7925, 7926)
    monkeypatch.setattr(craftbot._instance, "http_answers", answers_after_three_checks)
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: 4242)
    monkeypatch.setattr(craftbot, "_is_running", lambda pid: True)

    assert craftbot.cmd_open([]) is True
    assert opener.events == [("browser", "http://localhost:7925")]


def test_a_starting_craftbot_that_dies_is_started_again(opener, monkeypatch):
    _answering(monkeypatch, set())
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: 4242)
    monkeypatch.setattr(craftbot, "_is_running", lambda pid: False)

    assert craftbot.cmd_open([]) is True
    assert opener.events == [("start", [])]


def test_a_failed_start_reports_the_reason_and_the_log(opener, monkeypatch, capsys):
    _answering(monkeypatch, set())
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: None)
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: False)
    Path(craftbot.LOG_FILE).write_text(
        "booting\nRuntimeError: port 7926 is held\n", encoding="utf-8"
    )

    assert craftbot.cmd_open([]) is False
    output = capsys.readouterr().out
    assert "CraftBot could not start" in output
    assert "port 7926 is held" in output
    assert craftbot.LOG_FILE in output


def test_another_program_on_the_port_is_not_mistaken_for_craftbot(opener, monkeypatch):
    """No ui.json and no listener of THIS install: something else answers on
    7925, so CraftBot is started rather than that program opened."""
    _answering(monkeypatch, {"http://localhost:7925"})
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: None)

    assert craftbot.cmd_open([]) is True
    assert opener.events == [("start", [])]


def test_without_a_console_the_progress_window_runs_the_work(opener, monkeypatch):
    _answering(monkeypatch, set())
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: None)
    monkeypatch.setattr(craftbot, "_has_console", lambda: False)
    import installer.open_window as window

    seen = {}

    def fake_window(work, log_file=None):
        seen["log"] = log_file
        ok, _detail = work(lambda text: seen.setdefault("status", text))
        return ok

    monkeypatch.setattr(window, "run_with_window", fake_window)
    assert craftbot.cmd_open([]) is True
    assert seen["log"] == craftbot.LOG_FILE
    assert "Starting CraftBot" in seen["status"]
    assert opener.events == [("start", [])]


def test_progress_window_without_tk_still_does_the_work(monkeypatch):
    import builtins

    import installer.open_window as window

    real_import = builtins.__import__

    def no_tk(name, *args, **kwargs):
        if name.startswith("tkinter"):
            raise ImportError("no Tk here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_tk)
    assert window.run_with_window(lambda status: (True, None)) is True
    assert window.run_with_window(lambda status: (False, "broken")) is False


def test_legacy_installer_exe_icon_only_opens_the_browser(opener, monkeypatch):
    monkeypatch.setattr(craftbot, "IS_FROZEN", True)
    assert craftbot.cmd_open(["--frontend-port", "8123"]) is True
    assert opener.events == [("browser", "http://localhost:8123")]


def test_state_root_argument_is_applied_before_app_paths(tmp_path):
    """The icon names the state root because it does not inherit
    CRAFTBOT_HOME; craftbot.py must apply it before app.paths resolves."""
    home = tmp_path / "state home"
    argv = ["craftbot.py", "status", f"--state-root={home}"]
    code = (
        f"import sys; sys.argv = {argv!r};"
        "import craftbot;"
        "print(craftbot.paths.STATE_ROOT); print(sys.argv)"
    )
    env = {k: v for k, v in os.environ.items() if k != "CRAFTBOT_HOME"}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    assert Path(lines[-2]).resolve() == home.resolve()
    assert "--state-root" not in lines[-1]


def test_open_command_names_this_install(tmp_path, monkeypatch):
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot.paths, "STATE_ROOT", tmp_path)
    command = craftbot._open_command(["--frontend-port=8123", "--no-open-browser"])
    assert Path(command[1]).name == "craftbot.py"
    assert command[2] == "open"
    assert f"--state-root={tmp_path.resolve()}" in command
    assert "--frontend-port=8123" in command
    assert "--no-open-browser" not in command

    monkeypatch.setattr(craftbot, "IS_FROZEN", True)
    assert craftbot._open_command([]) is None


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("/usr/bin/python3", "/usr/bin/python3"),
        ("/home/u/My Apps/craftbot.py", '"/home/u/My Apps/craftbot.py"'),
        ("--state-root=/home/u/a$b", '"--state-root=/home/u/a\\\\$b"'),
        ("100%", "100%%"),
    ],
)
def test_desktop_entry_arguments_are_quoted_per_spec(arg, expected):
    assert craftbot._desktop_entry_arg(arg) == expected
