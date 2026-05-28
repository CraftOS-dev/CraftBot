"""Diagnostic environment for the "shell exec (windows)" action."""

from __future__ import annotations

from diagnostic.framework import ActionTestCase


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="shell exec (windows)",
        base_input={},
        skip_reason="Windows-specific shell execution not supported in the Linux diagnostic environment.",
    )
