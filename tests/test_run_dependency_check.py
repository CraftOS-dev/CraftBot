# -*- coding: utf-8 -*-
import subprocess
import sys
import textwrap

import pytest

from app import runtime_preflight


def test_confirmed_missing_runtime_dependencies_exit(monkeypatch, capsys):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='noise\n__CRAFTBOT_MISSING_RUNTIME_IMPORTS__["requests"]\n',
        )

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        runtime_preflight.ensure_runtime_dependencies(
            use_conda=False,
            env_name=None,
            checks={"requests": "requests"},
        )

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "CraftBot Python dependencies are missing" in output
    assert "requests" in output


def test_probe_timeout_warns_and_continues(monkeypatch, capsys):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    runtime_preflight.ensure_runtime_dependencies(
        use_conda=False,
        env_name=None,
        checks={"requests": "requests"},
    )

    output = capsys.readouterr().out
    assert "Warning: CraftBot could not verify Python dependencies" in output
    assert "timed out" in output


def test_malformed_probe_output_warns_and_continues(monkeypatch, capsys):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="__CRAFTBOT_MISSING_RUNTIME_IMPORTS__not-json\n",
        )

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fake_run)

    runtime_preflight.ensure_runtime_dependencies(
        use_conda=False,
        env_name=None,
        checks={"requests": "requests"},
    )

    output = capsys.readouterr().out
    assert "Warning: CraftBot could not verify Python dependencies" in output
    assert "unexpected probe output" in output


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
