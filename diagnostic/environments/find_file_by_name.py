"""Diagnostic environment for the "find file by name" action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def prepare_find_file_by_name(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
    project_dir = tmp_path / "project"
    nested_dir = project_dir / "notes"
    nested_dir.mkdir(parents=True)

    files = [
        project_dir / "report.md",
        project_dir / "summary.txt",
        nested_dir / "report_final.md",
    ]
    for file_path in files:
        file_path.write_text(f"Contents for {file_path.name}\n", encoding="utf-8")

    pattern = str(project_dir / "**" / "report*.md")

    expected_matches = sorted(
        str(path.resolve()) for path in files if path.suffix == ".md"
    )

    return PreparedEnv(
        input_overrides={
            "pattern": pattern,
            "recursive": True,
        },
        context={"expected_matches": expected_matches},
    )


def validate_find_file_by_name(
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
        return "incorrect result", "Expected 'matches' to be a list."

    expected = context.get("expected_matches", [])
    if sorted(matches) != expected:
        return (
            "incorrect result",
            f"Matches mismatch. expected={expected} actual={sorted(matches)}",
        )

    for path_str in matches:
        if not Path(path_str).exists():
            return "error", f"Matched file does not exist on disk: {path_str}"

    return "passed", "Glob pattern located the expected files."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="find file by name",
        base_input={},
        prepare=prepare_find_file_by_name,
        validator=validate_find_file_by_name,
    )
