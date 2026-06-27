# -*- coding: utf-8 -*-
import subprocess
import sys
import textwrap

from app import runtime_preflight


def test_find_missing_runtime_dependencies_reports_current_interpreter(monkeypatch):
    seen_commands = []

    def fake_run(cmd, capture_output, text, timeout):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='ignored import noise\n__CRAFTBOT_MISSING_RUNTIME_IMPORTS__["requests"]\n',
        )

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    missing, runtime_label = runtime_preflight.find_missing_runtime_dependencies(
        use_conda=False,
        env_name=None,
        checks={"requests": "requests", "aiohttp": "aiohttp"},
    )

    assert missing == ["requests"]
    assert runtime_label == sys.executable
    assert len(seen_commands) == 1
    assert seen_commands[0][:2] == [sys.executable, "-c"]
    assert "importlib.import_module(import_name)" in seen_commands[0][2]


def test_find_missing_runtime_dependencies_checks_conda_env(monkeypatch):
    seen_commands = []

    def fake_run(cmd, capture_output, text, timeout):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="__CRAFTBOT_MISSING_RUNTIME_IMPORTS__[]\n",
        )

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    missing, runtime_label = runtime_preflight.find_missing_runtime_dependencies(
        use_conda=True,
        env_name="craftbot",
        checks={"requests": "requests"},
        conda_command="conda",
    )

    assert missing == []
    assert runtime_label == "conda environment 'craftbot'"
    assert len(seen_commands) == 1
    assert seen_commands[0][:6] == ["conda", "run", "-n", "craftbot", "python", "-c"]
    assert "importlib.import_module(import_name)" in seen_commands[0][6]


def test_find_missing_runtime_dependencies_marks_all_missing_on_probe_failure(
    monkeypatch,
):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 1, stdout="import failed\n")

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    checks = {"requests": "requests", "aiohttp": "aiohttp"}
    missing, runtime_label = runtime_preflight.find_missing_runtime_dependencies(
        use_conda=False,
        env_name=None,
        checks=checks,
    )

    assert missing == ["requests", "aiohttp"]
    assert runtime_label == sys.executable


def test_find_missing_runtime_dependencies_marks_all_missing_without_sentinel(
    monkeypatch,
):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 0, stdout="third-party import noise\n")

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    checks = {"requests": "requests", "aiohttp": "aiohttp"}
    missing, runtime_label = runtime_preflight.find_missing_runtime_dependencies(
        use_conda=False,
        env_name=None,
        checks=checks,
    )

    assert missing == ["requests", "aiohttp"]
    assert runtime_label == sys.executable


def test_print_missing_runtime_dependencies_includes_fix(monkeypatch, capsys):
    monkeypatch.setattr(sys, "executable", "/opt/homebrew/bin/python3")

    runtime_preflight.print_missing_runtime_dependencies(
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


def test_runtime_preflight_does_not_require_provider_sdks():
    assert "openai" not in runtime_preflight.RUNTIME_IMPORT_CHECKS
    assert "anthropic" not in runtime_preflight.RUNTIME_IMPORT_CHECKS


def test_app_main_runs_preflight_before_agent_core_import():
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys
        import types

        fake_preflight = types.ModuleType("app.runtime_preflight")

        def ensure_current_runtime_dependencies():
            raise SystemExit(77)

        fake_preflight.ensure_current_runtime_dependencies = ensure_current_runtime_dependencies
        sys.modules["app.runtime_preflight"] = fake_preflight

        class BlockAgentCore(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "agent_core" or fullname.startswith("agent_core."):
                    raise AssertionError("agent_core imported before runtime preflight")
                return None

        sys.meta_path.insert(0, BlockAgentCore())

        try:
            import app.main  # noqa: F401
        except SystemExit as exc:
            assert exc.code == 77
        else:
            raise AssertionError("app.main did not run runtime preflight")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
