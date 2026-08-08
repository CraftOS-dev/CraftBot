"""Diagnostic environment for the "end_turn" action."""

from __future__ import annotations

from diagnostic.framework import ActionTestCase


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="end_turn",
        base_input={},
        skip_reason="Requires internal_action_interface service to acknowledge end_turn events.",
    )
