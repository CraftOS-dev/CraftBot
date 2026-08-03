# -*- coding: utf-8 -*-
"""Import-direction gate (FACTORY-PLAN §3.1): engine ↛ appfactory ↛ host.

    engine/      may import: stdlib, app.factory.engine.*
    appfactory/  may import: stdlib, app.factory.*
    (hosts import app.factory; nothing here checks hosts)

Run:  python3 -m app.factory.check_imports     (exit 1 on violation)
This is the mechanical guarantee that the factory stays a plug-and-play
component — the same philosophy as the kit's ownership hashes.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_STDLIB_HINT = None  # py3.10+: sys.stdlib_module_names


def _imports_of(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.lineno


def _violations(root: Path):
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for layer, allowed_prefixes in (
        ("engine", ("app.factory.engine",)),
        ("appfactory", ("app.factory",)),
    ):
        for py in sorted((root / layer).rglob("*.py")):
            for module, lineno in _imports_of(py):
                top = module.split(".")[0]
                if top in stdlib:
                    continue
                if any(module == p or module.startswith(p + ".") for p in allowed_prefixes):
                    continue
                yield f"{py.relative_to(root.parent.parent)}:{lineno}: {layer} imports '{module}'"


def main() -> int:
    root = Path(__file__).resolve().parent
    problems = list(_violations(root))
    if problems:
        print("FACTORY LAYERING VIOLATIONS (engine ↛ appfactory ↛ host):")
        for p in problems:
            print("  " + p)
        return 1
    print("factory layering OK (engine: stdlib-only; appfactory: engine-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
