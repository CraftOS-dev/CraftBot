"""Write-time TypeScript verification for Living UI builds (Pillar 2 of the
reliability design: continuous deterministic feedback, not batch-at-the-end).

After the agent writes a frontend .ts/.tsx file, the platform runs the
project's OWN TypeScript compiler (`tsc --noEmit`) and injects the COMPLETE
error list into the write result — the same channel as the pace-guard
notes. The agent sees every type error seconds after introducing it,
instead of minutes later through a full validation pipeline.

Properties:
  - Uses the tool's machine-readable format (`--pretty false`), passed
    through verbatim — no truncation, no caps, no fuzzy parsing.
  - Incremental (`--incremental` + tsBuildInfoFile) so repeat runs are
    fast; the first run after npm install pays the cold cost once.
  - Fail-open everywhere: no node, no node_modules (npm install still
    running), timeout, crash => no note, never an exception. A feedback
    feature must never break a build.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

# tsc's stable machine-output line: path(line,col): error TSxxxx: message
_TS_ERROR_RE = re.compile(r"error TS\d+:")

_TSC_TIMEOUT_S = 120  # cold first run resolves all node_modules types


def _find_node() -> Optional[str]:
    return shutil.which("node")


def _tsc_entry(project_root: Path) -> Optional[Path]:
    entry = project_root / "node_modules" / "typescript" / "lib" / "tsc.js"
    return entry if entry.is_file() else None


# Marker dropped by manager.start_dev_preview for the duration of ITS
# npm install (see _npm_install_marker there). Checks must not run against
# a half-extracted node_modules: tsc would report phantom "Cannot find
# module" errors on SYSTEM files and steer the agent into running a
# second, racing npm install.
_INSTALL_MARKER = Path("logs") / ".npm-installing"


def _install_incomplete(project_root: Path) -> bool:
    """True while npm install is running or has never completed for this
    project — the fail-open condition for every node-based check."""
    if (project_root / _INSTALL_MARKER).exists():
        return True
    # npm writes node_modules/.package-lock.json as the LAST step of a
    # successful install; its absence means mid-install or corrupted.
    if not (project_root / "node_modules" / ".package-lock.json").is_file():
        return True
    return False


def run_tsc(project_root: Path) -> Optional[List[str]]:
    """Run `tsc --noEmit` for the project. Returns the list of error lines
    (empty list = clean), or None when the check could not run (fail-open)."""
    node = _find_node()
    tsc = _tsc_entry(project_root)
    if not node or not tsc or not (project_root / "tsconfig.json").is_file():
        return None
    if _install_incomplete(project_root):
        logger.debug("[LIVING_UI:TSC] skipped: npm install in progress/incomplete")
        return None
    cache_dir = project_root / "node_modules" / ".cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    cmd = [
        node,
        str(tsc),
        "--noEmit",
        "--pretty",
        "false",
        "--incremental",
        "--tsBuildInfoFile",
        str(cache_dir / "craftbot-tsc.tsbuildinfo"),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TSC_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug(f"[LIVING_UI:TSC] check skipped: {exc}")
        return None
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    errors = [line.strip() for line in output.splitlines() if _TS_ERROR_RE.search(line)]
    return errors


def run_eslint(project_root: Path, rel_path: str) -> Optional[List[str]]:
    """Lint ONE just-written file with the project's own ESLint (react-hooks
    rules — the bug class tsc can't see). Returns message lines (empty =
    clean) or None when the check could not run (fail-open)."""
    node = _find_node()
    eslint = project_root / "node_modules" / "eslint" / "bin" / "eslint.js"
    if not node or not eslint.is_file():
        return None
    if _install_incomplete(project_root):
        return None
    target = project_root / rel_path
    if not target.is_file():
        return None
    try:
        proc = subprocess.run(
            [node, str(eslint), "--format", "json", str(target)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TSC_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug(f"[LIVING_UI:ESLINT] check skipped: {exc}")
        return None
    try:
        import json as _json

        results = _json.loads(proc.stdout or "[]")
    except ValueError:
        return None
    lines: List[str] = []
    for result in results:
        for msg in result.get("messages", []):
            severity = "error" if msg.get("severity") == 2 else "warning"
            lines.append(
                f"{rel_path}({msg.get('line', 0)},{msg.get('column', 0)}): "
                f"{severity} {msg.get('ruleId') or 'parse'}: {msg.get('message', '')}"
            )
    return lines


def tsc_note_for(project_root: Path, rel_path: str) -> Optional[str]:
    """Write-time note for a frontend code write: the project's complete
    current type-error list plus this file's lint findings, or None when
    clean/unavailable."""
    p = rel_path.replace("\\", "/").lower()
    if not p.startswith("frontend/") or not p.endswith((".ts", ".tsx")):
        return None
    notes: List[str] = []
    errors = run_tsc(Path(project_root))
    if errors:
        listing = "\n".join(f"  {e}" for e in errors)
        notes.append(
            f"TYPE ERRORS — `tsc --noEmit` reports {len(errors)} error(s) in the "
            f"project right now (complete list, newest write included). Fix ALL "
            f"of them in your next step; they will fail validation otherwise:\n"
            f"{listing}"
        )
    lint = run_eslint(Path(project_root), rel_path.replace("\\", "/"))
    if lint:
        listing = "\n".join(f"  {e}" for e in lint)
        notes.append(
            f"REACT-HOOKS LINT — {len(lint)} finding(s) in this file "
            f"(conditional hooks / stale dependency arrays cause runtime blank "
            f"screens tsc can't catch). Fix the errors now:\n{listing}"
        )
    return "\n\n".join(notes) if notes else None
