"""Diagnostic environment for the "keyboard typing" action."""

from __future__ import annotations

import types
from typing import Any, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def prepare_keyboard_typing(tmp_path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001, ANN001
    recorded: dict[str, Tuple[str, float]] = {}

    module = types.ModuleType("pyautogui")

    def write(text: str, interval: float = 0.0) -> None:
        recorded["typed"] = (text, interval)

    module.write = write  # type: ignore[attr-defined]

    text = "Automated typing"
    interval = 0.1

    return PreparedEnv(
        input_overrides={
            "text": text,
            "interval": interval,
        },
        extra_modules={"pyautogui": module},
        context={
            "expected_text": text,
            "expected_interval": interval,
            "recorded": recorded,
        },
    )


def validate_keyboard_typing(
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

    expected_text = context.get("expected_text")
    if output.get("typed_text") != expected_text:
        return (
            "incorrect result",
            f"Echo text mismatch. expected={expected_text} actual={output.get('typed_text')}",
        )

    recorded = context.get("recorded", {})
    typed_text, interval = recorded.get("typed", (None, None))
    if typed_text != expected_text or interval != context.get("expected_interval"):
        return (
            "incorrect result",
            "pyautogui.write was not invoked with expected arguments.",
        )

    return "passed", "Typing action issued expected write call."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="keyboard typing",
        base_input={},
        prepare=prepare_keyboard_typing,
        validator=validate_keyboard_typing,
    )
