"""Diagnostic environment for the "find in file content" action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def prepare_find_in_file_content(
    tmp_path: Path, action: Mapping[str, Any]
) -> PreparedEnv:  # noqa: ARG001
    target_file = tmp_path / "log.txt"
    lines = [
        "Startup complete",
        "ERROR: disk full",
        "warning: low memory",
        "Another Error occurred",
    ]
    target_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    pattern = "error"

    expected_matches = [
        "Line 2: ERROR: disk full",
        "Line 4: Another Error occurred",
    ]

    return PreparedEnv(
        input_overrides={
            "file_path": str(target_file),
            "pattern": pattern,
            "ignore_case": True,
        },
        context={
            "expected_matches": expected_matches,
        },
    )


def validate_find_in_file_content(
    result: ExecutionResult,
    input_data: Mapping[str, Any],  # noqa: ARG001
    context: Mapping[str, Any],
) -> Tuple[str, str]:
    output = result.parsed_output or {}
    if not isinstance(output, Mapping):
        return "incorrect result", "Expected JSON object output."

    if output.get("status") != "success":
        message = output.get("message", "No message provided")
        return "error", f"Action reported failure: {message}"

    matches = output.get("matches")
    if not isinstance(matches, list):
        return "incorrect result", "Expected 'matches' to be a list of strings."

    expected = context.get("expected_matches", [])
    if matches != expected:
        return (
            "incorrect result",
            f"Match lines mismatch. expected={expected} actual={matches}",
        )

    return "passed", "Pattern search returned expected lines."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="find in file content",
        base_input={},
        prepare=prepare_find_in_file_content,
        validator=validate_find_in_file_content,
    )
