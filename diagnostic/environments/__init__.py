"""Environment definitions for diagnostic action tests."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Dict

from diagnostic.framework import ActionTestCase


def load_environment_cases() -> Dict[str, ActionTestCase]:
    """Discover and load all available action test cases."""
    package_dir = Path(__file__).parent
    cases: Dict[str, ActionTestCase] = {}

    for module_path in package_dir.glob("*.py"):
        if module_path.name == "__init__.py":
            continue

        module_name = f"{__name__}.{module_path.stem}"
        module = import_module(module_name)
        get_case = getattr(module, "get_test_case", None)
        if callable(get_case):
            testcase = get_case()
            cases[testcase.name] = testcase

    return cases
