"""Diagnostic environment for the "mouse move" action."""

from __future__ import annotations

from diagnostic.framework import ActionTestCase


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="mouse move",
        base_input={},
        skip_reason=(
            "Depends on GUI automation via pyautogui and real display access, which are not"
            " provided in the diagnostic sandbox."
        ),
    )
