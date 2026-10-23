"""Shell actions: which OS is offered which one, and how a stop is told apart
from a failure.

run_powershell has an implementation for Windows alone. Every other action
has one for each OS (or for "all"), so it is the one name in the registry
with nothing to run on Linux or macOS.
"""

import platform
import subprocess
import sys

import pytest

from agent_core.core.action_framework.loader import load_actions_from_directories
from agent_core.core.action_framework.registry import registry_instance
from agent_core.core.impl.action import cancellation
from app.action.action_set import action_set_manager
from app.config import PROJECT_ROOT


@pytest.fixture(scope="module", autouse=True)
def actions_loaded():
    load_actions_from_directories(
        base_dir=str(PROJECT_ROOT), paths_to_scan=["app/data/action"]
    )


@pytest.fixture
def on_os(monkeypatch):
    def switch(system):
        monkeypatch.setattr(platform, "system", lambda: system)

    return switch


# ── run_powershell is Windows-only ────────────────────────────────────────


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_other_os_neither_sees_nor_resolves_run_powershell(on_os, system):
    on_os(system)
    # Not offered: the compiled list is what the model is shown.
    assert "run_powershell" not in action_set_manager.compile_action_list([])
    assert "run_powershell" not in action_set_manager.get_actions_in_set("core")
    # Not callable either, should a model produce the name unprompted.
    assert registry_instance.find_action_by_name("run_powershell") is None


@pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
def test_every_os_keeps_its_own_run_shell(on_os, system):
    on_os(system)
    assert "run_shell" in action_set_manager.compile_action_list([])
    assert registry_instance.find_action_by_name("run_shell") is not None


def test_windows_is_offered_both_shell_actions(on_os):
    on_os("Windows")
    compiled = action_set_manager.compile_action_list([])
    assert {"run_shell", "run_powershell"} <= set(compiled)

    powershell = registry_instance.find_action_by_name("run_powershell")
    assert powershell["platforms"] == ["windows"]
    assert next(iter(powershell["input_schema"])) == "script"
    # cmd.exe only: PowerShell has its own action, so there is no shell to pick.
    shell = registry_instance.find_action_by_name("run_shell")
    assert "shell" not in shell["input_schema"]


def test_unix_run_shell_schemas_are_untouched(on_os):
    for system in ("Linux", "Darwin"):
        on_os(system)
        shell = registry_instance.find_action_by_name("run_shell")
        assert list(shell["input_schema"]) == [
            "command",
            "shell",
            "timeout",
            "cwd",
            "env",
            "background",
        ]
        assert "run_powershell" not in shell["description"]


# ── a stop is not a failure ───────────────────────────────────────────────


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setattr(cancellation, "_marker_dir", lambda sid: tmp_path / sid)
    return "sess-shell"


@pytest.fixture
def sleeper():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)


def test_stop_marks_the_registered_process_it_killed(session, sleeper):
    cancellation.register_process(session, sleeper)
    assert not cancellation.was_killed(sleeper)
    assert cancellation.kill_session_processes(session) == 1
    assert sleeper.poll() is not None
    assert cancellation.was_killed(sleeper)


def test_process_that_already_exited_is_not_marked(session, sleeper):
    cancellation.register_process(session, sleeper)
    sleeper.kill()
    sleeper.wait(timeout=10)
    assert cancellation.kill_session_processes(session) == 0
    assert not cancellation.was_killed(sleeper)
