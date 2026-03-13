"""Diagnostic environment for the "switch to CLI mode" action."""
from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


EXPECTED_MODE = False


def _build_internal_interface_stub() -> tuple[types.ModuleType, type]:
    module = types.ModuleType("app.internal_action_interface")

    class InternalActionInterface:  # noqa: D401
        gui_mode = True

        @staticmethod
        def switch_to_CLI_mode() -> None:
            InternalActionInterface.gui_mode = False

        @staticmethod
        def switch_to_GUI_mode() -> None:  # pragma: no cover - not used here
            InternalActionInterface.gui_mode = True

    module.InternalActionInterface = InternalActionInterface
    return module, InternalActionInterface


def _prepare_switch_to_cli(
    tmp_path: Path,  # noqa: ARG001
    action: Mapping[str, Any],  # noqa: ARG001
) -> PreparedEnv:
    internal_module, interface_cls = _build_internal_interface_stub()
    return PreparedEnv(
        extra_modules={"app.internal_action_interface": internal_module},
        context={
            "interface_cls": interface_cls,
        },
    )


def _validate_switch_to_cli(
    result: ExecutionResult,
    input_data: Mapping[str, Any],  # noqa: ARG001
    context: Mapping[str, Any],
) -> Tuple[str, str]:
    payload = result.parsed_output
    if not isinstance(payload, Mapping):
        return "incorrect result", "Output must be a JSON object."

    if payload.get("status") != "ok":
        return "error", f"Action reported failure: {payload}"

    if payload.get("gui_mode") != EXPECTED_MODE:
        return "incorrect result", "Reported gui_mode did not match expected CLI mode."

    interface_cls = context.get("interface_cls")
    if getattr(interface_cls, "gui_mode", None) != EXPECTED_MODE:
        return "incorrect result", "Internal interface did not switch to CLI mode."

    return "passed", "Agent switched to CLI mode successfully."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="switch to CLI mode",
        base_input={},
        prepare=_prepare_switch_to_cli,
        validator=_validate_switch_to_cli,
    )
