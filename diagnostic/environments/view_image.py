"""Diagnostic environment for the "view image" action."""

from __future__ import annotations

from diagnostic.framework import ActionTestCase


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="view image",
        base_input={"image_path": ""},
        skip_reason=(
            "Requires InternalActionInterface.describe_image and a visual model, which are"
            " unavailable in the diagnostic sandbox."
        ),
    )
