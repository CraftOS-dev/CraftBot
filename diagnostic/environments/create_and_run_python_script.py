"""Diagnostic environment for the "create and run python script" action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


SCRIPT_SNIPPET = """
import math
print(f"circle:{round(math.pi, 3)}")
""".strip()


def prepare_create_and_run(
    tmp_path: Path,  # noqa: ARG001 - workspace not needed
    action: Mapping[str, Any],  # noqa: ARG001
) -> PreparedEnv:
    return PreparedEnv(
        input_overrides={"code": SCRIPT_SNIPPET},
    )


def validate_create_and_run(
    result: ExecutionResult,
    input_data: Mapping[str, Any],  # noqa: ARG001
    context: Mapping[str, Any],  # noqa: ARG001
) -> Tuple[str, str]:
    output = result.parsed_output or {}
    if not isinstance(output, Mapping):
        return "incorrect result", "Expected JSON object output."

    if output.get("status") != "success":
        message = output.get("message", "No message provided")
        return "error", f"Action reported failure: {message}"

    if output.get("stdout") != "circle:3.142":
        return (
            "incorrect result",
            f"Unexpected stdout: {output.get('stdout')!r}",
        )

    if output.get("stderr") not in ("", None):
        return "incorrect result", f"Unexpected stderr output: {output.get('stderr')!r}"

    return "passed", "Python snippet executed successfully."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="create and run python script",
        base_input={},
        prepare=prepare_create_and_run,
        validator=validate_create_and_run,
    )
