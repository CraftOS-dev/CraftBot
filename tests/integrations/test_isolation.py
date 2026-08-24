"""Isolation gate: the integrations package must stay host-blind.

``craftos_integrations`` (contracts + core, and providers/ when it lands)
may not import from the host application (``app``, ``agent_core``,
``agent_file_system``) — that boundary is what makes the package mountable
into a different agent. This test walks the AST of every module so the
gate needs no extra dependency (import-linter) to run.
"""

from __future__ import annotations

import ast
from pathlib import Path

import craftos_integrations

FORBIDDEN_ROOTS = {"app", "agent_core", "agent_file_system", "decorators"}

# Scope: the integrations-package surface. (The pre-multi-account modules already follow the same rule
# by convention; they get added here as they're ported.)
PACKAGE_PATHS = ["contracts.py", "core", "providers", "hosts"]


def _iter_package_modules():
    package_root = Path(craftos_integrations.__file__).parent
    for rel in PACKAGE_PATHS:
        path = package_root / rel
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("*.py"))


def _imported_roots(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # absolute imports only
                yield node.module.split(".")[0]


def test_package_never_imports_the_host():
    violations = []
    for module_path in _iter_package_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for root in _imported_roots(tree):
            if root in FORBIDDEN_ROOTS:
                violations.append(f"{module_path.name} imports {root}")
    assert not violations, (
        "Host imports leaked into the integrations package:\n  "
        + "\n  ".join(violations)
    )


def test_every_module_parses():
    modules = list(_iter_package_modules())
    assert modules, "integration modules not found — did the layout move?"
    for module_path in modules:
        ast.parse(module_path.read_text(encoding="utf-8"))
