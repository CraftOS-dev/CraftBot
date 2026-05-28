"""Diagnostic environment for the "open application" action."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Mapping

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _build_subprocess_stub(
    invocations: list[tuple[list[str], Mapping[str, Any]]],
) -> types.ModuleType:
    module = types.ModuleType("subprocess")
    module.DEVNULL = object()
    module.CREATE_NEW_CONSOLE = 0

    class _Process:
        def __init__(self, cmd: list[str], kwargs: Mapping[str, Any]) -> None:
            self.cmd = cmd
            self.kwargs = dict(kwargs)
            self.pid = 4242

    def popen(cmd: list[str], *args: Any, **kwargs: Any) -> _Process:  # noqa: ANN401
        record = (list(cmd), dict(kwargs))
        invocations.append(record)
        return _Process(record[0], record[1])

    module.Popen = popen  # type: ignore[attr-defined]
    return module


def get_test_case() -> ActionTestCase:
    def prepare(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
        exe_path = tmp_path / "bin" / "utility.exe"
        exe_path.parent.mkdir(parents=True)
        exe_path.write_text("binary", encoding="utf-8")

        calls: list[tuple[list[str], Mapping[str, Any]]] = []
        subprocess_stub = _build_subprocess_stub(calls)

        context = {
            "exe_path": exe_path,
            "invocations": calls,
        }

        return PreparedEnv(
            input_overrides={
                "exe_path": str(exe_path),
                "args": ["--flag"],
            },
            extra_modules={"subprocess": subprocess_stub},
            context=context,
        )

    def validator(
        result: ExecutionResult,
        input_data: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> tuple[str, str]:
        if result.has_error():
            return "error", "Execution raised an exception."

        payload = result.parsed_output or {}
        if payload.get("status") != "success":
            return "incorrect result", f"Unexpected status {payload.get('status')!r}."
        if payload.get("pid") != 4242:
            return "incorrect result", "Reported PID does not match stubbed process."
        if payload.get("message") not in ("", None):
            return "incorrect result", "Message field should be empty on success."

        invocations: list[tuple[list[str], Mapping[str, Any]]] = context["invocations"]
        if len(invocations) != 1:
            return (
                "incorrect result",
                f"Expected exactly one launch attempt, saw {len(invocations)}.",
            )

        command, kwargs = invocations[0]
        expected = [str(context["exe_path"]), "--flag"]
        if command != expected:
            return "incorrect result", f"Command mismatch: {command!r} != {expected!r}."
        cwd = kwargs.get("cwd")
        if cwd != str(context["exe_path"].parent):
            return (
                "incorrect result",
                "Process started with unexpected working directory.",
            )

        return "passed", "Application launch simulated successfully."

    return ActionTestCase(
        name="open application",
        base_input={"exe_path": ""},
        prepare=prepare,
        validator=validator,
    )
