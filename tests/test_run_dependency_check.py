# -*- coding: utf-8 -*-
import subprocess
import sys

import run


def test_find_missing_runtime_dependencies_reports_current_interpreter(monkeypatch):
    seen_commands = []

    def fake_run(cmd, capture_output, timeout):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[-1] == "import requests" else 0)

    monkeypatch.setattr(run.subprocess, "run", fake_run)

    missing, runtime_label = run.find_missing_runtime_dependencies(
        use_conda=False,
        env_name=None,
        checks={"requests": "requests", "aiohttp": "aiohttp"},
    )

    assert missing == ["requests"]
    assert runtime_label == sys.executable
    assert seen_commands == [
        [sys.executable, "-c", "import requests"],
        [sys.executable, "-c", "import aiohttp"],
    ]


def test_find_missing_runtime_dependencies_checks_conda_env(monkeypatch):
    seen_commands = []

    monkeypatch.setattr(run, "get_conda_command", lambda: "conda")

    def fake_run(cmd, capture_output, timeout):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(run.subprocess, "run", fake_run)

    missing, runtime_label = run.find_missing_runtime_dependencies(
        use_conda=True,
        env_name="craftbot",
        checks={"requests": "requests"},
    )

    assert missing == []
    assert runtime_label == "conda environment 'craftbot'"
    assert seen_commands == [
        ["conda", "run", "-n", "craftbot", "python", "-c", "import requests"]
    ]


def test_print_missing_runtime_dependencies_includes_fix(monkeypatch, capsys):
    monkeypatch.setattr(sys, "executable", "/opt/homebrew/bin/python3")

    run.print_missing_runtime_dependencies(
        missing=["requests", "aiohttp"],
        runtime_label="/opt/homebrew/bin/python3",
        use_conda=False,
        env_name=None,
    )

    output = capsys.readouterr().out
    assert "requests" in output
    assert "aiohttp" in output
    assert "/opt/homebrew/bin/python3" in output
    assert "/opt/homebrew/bin/python3 install.py" in output
