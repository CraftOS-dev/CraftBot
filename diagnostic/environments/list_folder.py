"""Environment and validation for the "list folder" action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def prepare_list_folder(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
    data_dir = tmp_path / "sample"
    data_dir.mkdir()
    (data_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
    (data_dir / "beta.txt").write_text("beta", encoding="utf-8")
    (data_dir / "nested").mkdir()
    (data_dir / "nested" / "gamma.txt").write_text("gamma", encoding="utf-8")

    expected_contents = sorted(["alpha.txt", "beta.txt", "nested"])
    return PreparedEnv(
        input_overrides={"path": str(data_dir)},
        context={"expected_contents": expected_contents},
    )


def validate_list_folder(
    result: ExecutionResult,
    input_data: Mapping[str, Any],  # noqa: ARG001 - included for consistency
    context: Mapping[str, Any],
) -> Tuple[str, str]:
    output = result.parsed_output or {}
    if not isinstance(output, Mapping):
        return "incorrect result", "Expected JSON object output."

    if output.get("status") != "success":
        return "error", f"Action reported failure: {output}"

    actual_contents = sorted(output.get("contents", []))
    expected_contents = list(context.get("expected_contents", []))
    if actual_contents != expected_contents:
        return (
            "incorrect result",
            f"Contents mismatch. expected={expected_contents} actual={actual_contents}",
        )

    return "passed", "Directory contents match expectation."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="list folder",
        base_input={},
        prepare=prepare_list_folder,
        validator=validate_list_folder,
    )
