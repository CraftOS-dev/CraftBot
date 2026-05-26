"""Diagnostic environment for the "ignore" action."""

from __future__ import annotations

from diagnostic.framework import ActionTestCase


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="ignore",
        base_input={},
        skip_reason="Requires internal_action_interface service to acknowledge ignore events.",
    )
