"""Diagnostic environment for the "keyboard input" action."""

from __future__ import annotations

import types
from typing import Any, List, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _build_pyautogui_stub(
    recorded: List[Tuple[str, Tuple[str, ...]]],
) -> types.ModuleType:
    module = types.ModuleType("pyautogui")

    def press(key: str) -> None:
        recorded.append(("press", (key,)))

    def hotkey(*combo: str) -> None:
        recorded.append(("hotkey", tuple(combo)))

    module.press = press  # type: ignore[attr-defined]
    module.hotkey = hotkey  # type: ignore[attr-defined]
    return module


def prepare_keyboard_input(tmp_path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001, ANN001
    recorded: List[Tuple[str, Tuple[str, ...]]] = []
    stub = _build_pyautogui_stub(recorded)
    keys_sequence = ["ctrl+s", "enter"]

    return PreparedEnv(
        input_overrides={"keys": keys_sequence},
        extra_modules={"pyautogui": stub},
        context={
            "expected_operations": [
                ("hotkey", ("ctrl", "s")),
                ("press", ("enter",)),
            ],
            "recorded": recorded,
        },
    )


def validate_keyboard_input(
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

    recorded = context.get("recorded", [])
    expected_ops = context.get("expected_operations", [])
    if recorded != expected_ops:
        return (
            "incorrect result",
            f"Keystroke sequence mismatch. expected={expected_ops} actual={recorded}",
        )

    return "passed", "Keyboard input dispatched expected key sequence."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="keyboard input",
        base_input={},
        prepare=prepare_keyboard_input,
        validator=validate_keyboard_input,
    )
