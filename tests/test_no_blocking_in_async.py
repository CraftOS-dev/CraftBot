"""
Guard: no synchronous blocking calls directly inside ``async def`` in the UI layer.

The browser UI server shares one asyncio loop with the agent, so a blocking
call made directly inside an ``async def`` freezes every browser tab while it
runs (docs/plans/ui-data-freshness-plan.md, RS-0). This test scans
``app/ui_layer`` and fails on any such call that isn't in the baseline.

Offload instead: ``await asyncio.to_thread(fn, ...)`` or
``await asyncio.create_subprocess_exec(...)``. Calls inside nested ``def`` /
``lambda`` bodies and awaited calls are not flagged. The scan only sees direct
calls; a sync helper that blocks internally is caught at runtime by the loop
stall detector instead.

The baseline (``no_blocking_async_baseline.txt``) lists known violations still
to fix; delete a line when you fix it (the second test enforces that).

Report-only scan of other code, e.g. agent code outside this plan's scope:

    python -m tests.test_no_blocking_in_async agent_core app
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable, Iterator, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_LAYER = PROJECT_ROOT / "app" / "ui_layer"
BASELINE_FILE = Path(__file__).with_name("no_blocking_async_baseline.txt")
SKIP_DIR_NAMES = frozenset({"node_modules", "dist", "__pycache__", ".venv", "venv"})

# Fully-qualified call names that block the calling thread.
BLOCKING_CALLS = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
        "os.popen",
        "time.sleep",
        "urllib.request.urlopen",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.patch",
        "requests.delete",
        "requests.head",
        "requests.request",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.patch",
        "httpx.delete",
        "httpx.request",
        "shutil.rmtree",
        "shutil.copytree",
        "shutil.move",
        "shutil.make_archive",
        "shutil.unpack_archive",
    }
)
# Names imported directly, e.g. ``from urllib.request import urlopen``.
BLOCKING_BARE_NAMES = frozenset({"urlopen"})
# Methods that block whatever they're called on (when not awaited).
BLOCKING_METHODS = frozenset({"extractall", "communicate"})


def scan(roots: Iterable[Path]) -> Set[str]:
    """Violation keys ``path::qualified_function::call`` under the given roots."""
    found: Set[str] = set()
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if SKIP_DIR_NAMES.intersection(path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            scanner = _AsyncBodyScanner(path.relative_to(PROJECT_ROOT).as_posix())
            scanner.visit(tree)
            found |= scanner.found
    return found


def load_baseline() -> Set[str]:
    if not BASELINE_FILE.exists():
        return set()
    lines = BASELINE_FILE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


class _AsyncBodyScanner(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self._path = relative_path
        self._scope: list[str] = []
        self.found: Set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._within(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._within(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope.append(node.name)
        qualified = ".".join(self._scope)
        for call in _direct_calls(node):
            name = _blocking_name(call)
            if name:
                self.found.add(f"{self._path}::{qualified}::{name}")
        self.generic_visit(node)  # nested async defs get their own pass
        self._scope.pop()

    def _within(self, name: str, node: ast.AST) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()


def _direct_calls(function: ast.AsyncFunctionDef) -> Iterator[ast.Call]:
    """Calls executed on the loop by this coroutine body (not awaited, not nested)."""
    awaited: Set[int] = set()
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            awaited.add(id(node.value))
        if isinstance(node, ast.Call) and id(node) not in awaited:
            yield node
        pending.extend(ast.iter_child_nodes(node))


def _dotted_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _blocking_name(call: ast.Call) -> Optional[str]:
    dotted = _dotted_name(call.func)
    if dotted in BLOCKING_CALLS:
        return dotted
    if isinstance(call.func, ast.Name) and call.func.id in BLOCKING_BARE_NAMES:
        return call.func.id
    if isinstance(call.func, ast.Attribute) and call.func.attr in BLOCKING_METHODS:
        return f".{call.func.attr}"
    return None


def test_no_new_blocking_calls_in_ui_layer_async_code():
    new = sorted(scan([UI_LAYER]) - load_baseline())
    assert not new, (
        "Blocking call(s) directly inside `async def` in app/ui_layer freeze every "
        "browser tab. Offload with asyncio.to_thread / asyncio.create_subprocess_exec:\n  "
        + "\n  ".join(new)
    )


def test_baseline_lists_only_current_violations():
    fixed = sorted(load_baseline() - scan([UI_LAYER]))
    assert not fixed, (
        f"These entries no longer occur; delete them from {BASELINE_FILE.name}:\n  "
        + "\n  ".join(fixed)
    )


if __name__ == "__main__":
    roots = [PROJECT_ROOT / arg for arg in sys.argv[1:]] or [UI_LAYER]
    violations = sorted(scan(roots))
    for violation in violations:
        print(violation)
    print(f"\n{len(violations)} blocking call(s) directly inside async functions")
