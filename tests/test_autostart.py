"""Login startup must work without the installer's console or environment."""

import json
import os
import plistlib
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import craftbot
from installer import startup


@pytest.fixture(autouse=True)
def configured_context_window():
    """Override the suite's model fixture: startup must need only the stdlib."""


@pytest.fixture(autouse=True)
def isolated_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(craftbot.paths, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(craftbot, "PID_FILE", str(tmp_path / "craftbot.pid"))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(tmp_path / "craftbot.log"))
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: None)
    monkeypatch.setattr(craftbot, "_close_console_window", lambda: None)
    monkeypatch.setattr(craftbot, "_warn_path_issues", lambda: None)
    monkeypatch.setattr(craftbot.time, "sleep", lambda seconds: None)


@pytest.mark.parametrize("enabled", [True, False])
def test_install_refreshes_registration_and_preserves_opt_out(
    tmp_path, monkeypatch, enabled
):
    startup.write(tmp_path, enabled, ["--frontend-port", "8123", "--backend-port=8124"])
    events = []
    monkeypatch.setattr(
        craftbot, "cmd_start", lambda args: events.append(("start", args)) or True
    )
    # An existing registration is no reason to skip refreshing it.
    monkeypatch.setattr(craftbot, "_is_installed", lambda: True)
    monkeypatch.setattr(
        craftbot,
        "_configure_autostart",
        lambda on, args: events.append((on, args)) or True,
    )
    assert craftbot.cmd_install(["--no-open-browser"])
    assert events == [
        (
            "start",
            ["--frontend-port", "8123", "--backend-port=8124", "--no-open-browser"],
        ),
        (
            enabled,
            ["--frontend-port", "8123", "--backend-port=8124", "--no-open-browser"],
        ),
    ]


def test_fresh_install_defaults_to_automatic_startup(monkeypatch):
    choices = []
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: True)
    monkeypatch.setattr(
        craftbot, "_configure_autostart", lambda on, args: choices.append(on) or True
    )
    assert craftbot.cmd_install([])
    assert choices == [True]


def test_install_opt_out_and_registration_failure_are_not_silent(monkeypatch):
    choices = []
    monkeypatch.setattr(craftbot, "cmd_start", lambda args: True)
    monkeypatch.setattr(
        craftbot,
        "_configure_autostart",
        lambda on, args: choices.append((on, args)) or False,
    )
    assert not craftbot.cmd_install(["--no-autostart"])
    assert choices == [(False, [])]


def test_enable_disable_persist_without_stopping_current_session(tmp_path, monkeypatch):
    events = []

    def dispatch(**handlers):
        if "_install_windows" in getattr(handlers["win"], "__name__", ""):
            return lambda args: events.append(("enable", args)) or True
        return lambda **kwargs: events.append(("disable", kwargs)) or True

    monkeypatch.setattr(craftbot._helpers, "dispatch_per_platform", dispatch)
    assert craftbot.cmd_autostart(["disable", "--frontend-port", "8123"])
    assert startup.read(tmp_path) == {
        "enabled": False,
        "args": ["--frontend-port", "8123"],
    }
    assert events[0] == ("disable", {"stop": False})
    assert craftbot.cmd_autostart(["enable"])
    assert events[1] == ("enable", ["--frontend-port", "8123", "--no-open-browser"])
    assert startup.read(tmp_path)["enabled"] is True


def test_repair_port_override_does_not_keep_old_port():
    assert startup.merge_args(
        ["--frontend-port", "8123", "--backend-port=8124", "--conda"],
        ["--frontend-port=9123", "--no-conda", "--no-autostart"],
    ) == ["--backend-port=8124", "--frontend-port=9123", "--no-conda"]


def test_startup_failure_does_not_persist_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        craftbot._helpers, "dispatch_per_platform", lambda **kw: lambda args: False
    )
    assert not craftbot.cmd_autostart(["enable"])
    assert not (tmp_path / "startup.json").exists()


def test_windows_registration_replaces_task_and_removes_registry_duplicate(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(craftbot, "_PLATFORM", "win32")
    python = str(tmp_path / "Python & tools" / "pythonw.exe")
    monkeypatch.setattr(craftbot, "_python_exe", lambda: python)
    definitions = []

    def run(cmd, **kwargs):
        if cmd[0] == "whoami":
            return subprocess.CompletedProcess(
                cmd, 0, '"domain\\user","S-1-5-21-123"\n'
            )
        assert cmd[:2] == ["schtasks", "/create"]
        definitions.append(
            ET.fromstring(Path(cmd[cmd.index("/xml") + 1]).read_text(encoding="utf-16"))
        )
        return subprocess.CompletedProcess(cmd, 0)

    cleaned = []
    monkeypatch.setattr(craftbot.subprocess, "run", run)
    monkeypatch.setattr(
        craftbot, "_remove_windows_registry", lambda: cleaned.append(True) or True
    )
    assert craftbot._install_windows(["--frontend-port", "8123"])
    root = definitions[0]

    def value(path):
        return root.findtext("/".join("{*}" + part for part in path.split("/")))

    assert value("Actions/Exec/Command") == python
    assert value("Actions/Exec/WorkingDirectory") == str(tmp_path)
    arguments = value("Actions/Exec/Arguments")
    assert "--service" in arguments and "--no-open-browser" in arguments
    assert "--frontend-port 8123" in arguments
    assert value("Triggers/LogonTrigger/UserId") == "S-1-5-21-123"
    assert value("Settings/DisallowStartIfOnBatteries") == "false"
    assert value("Settings/StopIfGoingOnBatteries") == "false"
    assert value("Settings/ExecutionTimeLimit") == "PT0S"
    assert value("Settings/StartWhenAvailable") == "true"
    assert cleaned == [True]


def test_windows_registry_fallback_replaces_old_task_first(monkeypatch):
    events = []

    def run(cmd, **kwargs):
        events.append(cmd[:2])
        if cmd[0] == "whoami":
            return subprocess.CompletedProcess(cmd, 0, '"user","S-1-5-21-123"')
        return subprocess.CompletedProcess(cmd, 1 if "/create" in cmd else 0)

    monkeypatch.setattr(craftbot.subprocess, "run", run)
    monkeypatch.setattr(
        craftbot,
        "_install_windows_registry",
        lambda action: events.append(action) or True,
    )
    assert craftbot._install_windows([])
    assert events[-2] == ["schtasks", "/delete"]
    assert "--service" in events[-1]
    assert "--no-open-browser" in events[-1]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_unix_registration_quotes_paths_and_keeps_ports(
    tmp_path, monkeypatch, platform
):
    home = tmp_path / "Home & space"
    home.mkdir()
    monkeypatch.setattr(craftbot, "_PLATFORM", platform)
    monkeypatch.setattr(
        craftbot.os.path, "expanduser", lambda path: str(home / path.removeprefix("~/"))
    )
    monkeypatch.setattr(craftbot, "_python_exe", lambda: "/Python & tools/python3")
    monkeypatch.setattr(
        craftbot.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
    )
    if platform == "darwin":
        assert craftbot._install_macos(["--frontend-port", "8123"])
        data = plistlib.loads(
            (home / "Library/LaunchAgents/com.craftbot.agent.plist").read_bytes()
        )
        assert data["ProgramArguments"] == [
            "/Python & tools/python3",
            craftbot.RUN_SCRIPT,
            "--frontend-port",
            "8123",
            "--no-open-browser",
            "--service",
            f"--state-root={tmp_path.resolve()}",
        ]
        assert data["RunAtLoad"] is True
    else:
        assert craftbot._install_linux(["--frontend-port", "8123"])
        content = (home / ".config/systemd/user/craftbot.service").read_text()
        assert 'ExecStart="/Python & tools/python3"' in content
        assert '"--service"' in content and '"8123"' in content
        assert craftbot._uninstall_linux(stop=False)
        assert not (home / ".config/systemd/user/craftbot.service").exists()


def test_service_pid_does_not_replace_running_app(tmp_path, monkeypatch):
    monkeypatch.setattr(craftbot, "_owned_pid", lambda: 123)
    assert not craftbot._claim_service_process()
    assert not Path(craftbot.PID_FILE).exists()


def test_service_pid_is_published_and_cleared():
    assert craftbot._claim_service_process()
    assert craftbot._owned_pid() == os.getpid()
    craftbot._release_service_process(os.getpid())
    assert not Path(craftbot.PID_FILE).exists()


@pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("systemd-analyze"),
    reason="requires systemd's real unit parser",
)
def test_generated_linux_unit_is_accepted_by_systemd(tmp_path, monkeypatch):
    home = tmp_path / "Home with spaces"
    home.mkdir()
    monkeypatch.setattr(
        craftbot.os.path, "expanduser", lambda path: str(home / path.removeprefix("~/"))
    )
    monkeypatch.setattr(craftbot, "_python_exe", lambda: sys.executable)
    real_run = subprocess.run
    monkeypatch.setattr(
        craftbot.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
    )
    assert craftbot._install_linux([])
    unit = home / ".config/systemd/user/craftbot.service"
    result = real_run(
        ["systemd-analyze", "verify", str(unit)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    sys.platform != "win32", reason="requires actual pythonw.exe handles"
)
def test_cold_pythonw_startup_logs_and_survives_interpreter_handoff(tmp_path):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pytest.skip("pythonw.exe is not installed")
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "config.json").write_text(
        json.dumps({"python_executable": sys.executable})
    )
    probe = tmp_path / "startup_probe.py"
    probe.write_text(
        textwrap.dedent("""\
        import json, os, pathlib, sys
        sys.path.insert(0, sys.argv[1])
        work = pathlib.Path(sys.argv[2])
        from app import python_runtime
        from app.console import configure_console
        if not os.environ.get("CRAFTBOT_PY_REEXEC"):
            (work / "initial.json").write_text(json.dumps({"stdout_missing": sys.stdout is None}))
        configure_console(log_file=str(work / "startup.log"))
        python_runtime.CONFIG_FILE = str(work / "config.json")
        python_runtime.reexec_if_needed()
        print("HANDOFF COMPLETE", flush=True)
        (work / "result.json").write_text(json.dumps({"python": sys.executable}))
    """),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CRAFTBOT_", "CONDA_"))
        and k not in ("PYTHONPATH", "VIRTUAL_ENV")
    }
    proc = subprocess.run(
        [str(pythonw), str(probe), str(repo), str(tmp_path)],
        cwd=os.environ["WINDIR"],
        env=env,
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        timeout=30,
    )
    assert proc.returncode == 0
    assert json.loads((tmp_path / "initial.json").read_text())["stdout_missing"] is True
    assert (
        json.loads((tmp_path / "result.json").read_text())["python"] == sys.executable
    )
    assert "HANDOFF COMPLETE" in (tmp_path / "startup.log").read_text()


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows shortcuts")
def test_real_windows_shortcut_refreshes_url_without_launching_agent(
    tmp_path, monkeypatch
):
    desktop = tmp_path / "Desktop O'Hare $literal"
    desktop.mkdir()
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))
    monkeypatch.setattr(craftbot, "_ensure_ico", lambda: None)
    craftbot._create_desktop_shortcut_windows([])
    craftbot._create_desktop_shortcut_windows(["--frontend-port", "8123"])
    link = desktop / "CraftBot.lnk"
    inspect = tmp_path / "inspect.ps1"
    inspect.write_text(
        "$ws = New-Object -ComObject WScript.Shell\n"
        f"$s = $ws.CreateShortcut({craftbot._ps_literal(str(link))})\n"
        "$s | Select-Object TargetPath,Arguments | ConvertTo-Json\n",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(inspect),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    shortcut = json.loads(result.stdout)
    assert Path(shortcut["TargetPath"]).name.lower() == "cmd.exe"
    assert shortcut["Arguments"] == '/c start "" http://localhost:8123'


@pytest.mark.skipif(sys.platform != "win32", reason="requires pythonw.exe")
@pytest.mark.parametrize("relocated_state", [False, True])
def test_real_run_service_entry_from_unrelated_working_directory(
    tmp_path, monkeypatch, relocated_state
):
    """Run the actual entry point, stopping at preflight before real servers start."""
    repo = Path(__file__).resolve().parents[1]
    tree = tmp_path / "installed CraftBot"
    for relative in (
        "run.py",
        "craftbot.py",
        "app/__init__.py",
        "app/paths.py",
        "app/console.py",
        "app/python_runtime.py",
        "app/runtime_preflight.py",
        "app/node_runtime.py",
        "installer/__init__.py",
        "installer/helpers.py",
        "installer/metadata.py",
        "installer/payload.py",
        "installer/startup.py",
    ):
        dest = tree / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / relative, dest)
    # A disposable source installation: no user data or real app dependencies.
    (tree / "install.py").touch()
    (tree / "requirements.txt").touch()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    (tree / "config.json").write_text(json.dumps({"python_executable": str(pythonw)}))
    (tree / "craftbot.pid").write_text('{"pid": 2147483647, "started": 1}')
    state = tmp_path / "relocated user data" if relocated_state else tree
    monkeypatch.setattr(craftbot.paths, "STATE_ROOT", state)
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tree / "run.py"))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: str(pythonw))
    command = craftbot._autostart_launch([])
    runner = tmp_path / "entry_probe.py"
    runner.write_text(
        textwrap.dedent("""\
        import json, os, pathlib, runpy, sys
        tree = pathlib.Path(sys.argv[1])
        state = pathlib.Path(sys.argv[2])
        command = sys.argv[3:]
        sys.path.insert(0, str(tree))
        from app import runtime_preflight
        def reached_preflight(**kwargs):
            import craftbot
            assert craftbot._owned_pid() == os.getpid()
            assert "--service" not in sys.argv
            assert pathlib.Path.cwd() == state
            print("SERVICE ENTRY OK", flush=True)
            (tree / "preflight-reached").touch()
            raise SystemExit(0)
        runtime_preflight.ensure_runtime_dependencies = reached_preflight
        sys.argv = command
        runpy.run_path(str(tree / "run.py"), run_name="__main__")
    """),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CRAFTBOT_", "CONDA_"))
        and k not in ("PYTHONPATH", "VIRTUAL_ENV")
    }
    child = subprocess.run(
        [str(pythonw), str(runner), str(tree), str(state), *command[1:]],
        cwd=os.environ["WINDIR"],
        env=env,
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        timeout=30,
    )
    assert child.returncode == 0, (tree / "craftbot.log").read_text(encoding="utf-8")
    assert (tree / "preflight-reached").exists()
    assert not (tree / "craftbot.pid").exists()
    assert "SERVICE ENTRY OK" in (tree / "craftbot.log").read_text(encoding="utf-8")
