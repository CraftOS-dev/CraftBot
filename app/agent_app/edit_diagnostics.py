"""Edit-time diagnostics — the agent's compiler, attached to its edits.

Measured live (2026-09-09, brainstorm 189495c4): an agent ran a coherent
compile-driven type migration using the LAUNCH GATE as its compiler — ~26
gate cycles at 60-90s each to answer questions `tsc --noEmit` answers in
~2s on apps this size. The strategy was right; the feedback loop was 30x
too expensive.

This module closes the loop the way an IDE does: after any turn in an app
session that changed TypeScript sources, the platform runs the project's
own tsc and puts the diagnostics into the event stream the agent reads
next. No new agent decision, no instruction to remember — the world simply
answers the edit.

Detection is CONTENT-based, not action-name based (same principle as
_warn_if_undeployed): the frontend tree's newest mtime is compared to the
last check, so an edit made through run_shell/sed is seen exactly like a
stream_edit. Output is deduplicated by error-set fingerprint so an
unchanged failure is never repeated into context, and the clean transition
is announced exactly once.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

_TSC_TIMEOUT_S = 90
_MAX_ERROR_LINES = 40
_SOURCE_SUFFIXES = (".ts", ".tsx")
# tsconfig/package changes alter compilation without touching src/.
_EXTRA_INPUTS = ("tsconfig.json", "package.json")


@dataclass
class _ProjectState:
    last_scan_at: float = 0.0
    last_report_fp: str = ""
    was_failing: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class EditDiagnostics:
    def __init__(self) -> None:
        self._states: Dict[str, _ProjectState] = {}

    async def after_turn(self, project) -> Optional[str]:
        """Diagnostics message for the agent, or None when there is nothing
        new to say (no TS edits since the last check, or an identical error
        set already reported). Never raises."""
        try:
            frontend = Path(project.path) / "frontend"
            if not (frontend / "src").is_dir():
                return None
            tsc = frontend / "node_modules" / "typescript" / "bin" / "tsc"
            if not tsc.exists():
                return None
            state = self._states.setdefault(project.id, _ProjectState())
            async with state.lock:
                newest = self._newest_source_mtime(frontend)
                if newest <= state.last_scan_at:
                    return None
                state.last_scan_at = time.time()
                count, output = await self._typecheck(frontend, tsc)
                return self._render(project, state, count, output)
        except Exception as e:
            logger.debug(f"[EDIT_DIAG] skipped: {e}")
            return None

    # ── internals ──────────────────────────────────────────────────────────
    @staticmethod
    def _newest_source_mtime(frontend: Path) -> float:
        newest = 0.0
        for path in (frontend / "src").rglob("*"):
            if path.suffix in _SOURCE_SUFFIXES:
                try:
                    newest = max(newest, path.stat().st_mtime)
                except OSError:
                    continue
        for rel in _EXTRA_INPUTS:
            extra = frontend / rel
            try:
                newest = max(newest, extra.stat().st_mtime)
            except OSError:
                continue
        return newest

    @staticmethod
    async def _typecheck(frontend: Path, tsc: Path) -> "tuple[int, str]":
        from app import node_runtime

        process = await asyncio.create_subprocess_exec(
            node_runtime.node_cmd() or "node",
            str(tsc),
            "-p",
            str(frontend),
            "--noEmit",
            "--pretty",
            "false",
            env=node_runtime.child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(
                process.communicate(), timeout=_TSC_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError(f"tsc timed out after {_TSC_TIMEOUT_S}s")
        text = out.decode(errors="replace")
        error_lines = [
            line for line in text.splitlines() if "): error TS" in line
        ]
        return len(error_lines), "\n".join(error_lines[:_MAX_ERROR_LINES])

    @staticmethod
    def _render(
        project, state: _ProjectState, count: int, output: str
    ) -> Optional[str]:
        if count == 0:
            if not state.was_failing:
                return None  # clean stayed clean — silence is the report
            state.was_failing = False
            state.last_report_fp = ""
            return (
                f"[typecheck] {project.name}: CLEAN — your TypeScript edits "
                "compile. agent_app_notify_ready will pass the types step."
            )
        fingerprint = hashlib.sha1(output.encode()).hexdigest()
        if fingerprint == state.last_report_fp:
            # The identical error set was already shown — repeating it adds
            # context weight, not information.
            return None
        state.last_report_fp = fingerprint
        state.was_failing = True
        return (
            f"[typecheck] {project.name}: {count} TypeScript error(s) after "
            f"your edits (ran automatically, ~2s — no relaunch needed):\n"
            f"{output}\n"
            "Fix ALL of these before calling agent_app_notify_ready — the "
            "gate runs this same compiler and will fail on them. Errors can "
            "cascade: after fixing, your next edit re-runs this check "
            "automatically."
        )


_DIAGNOSTICS: Optional[EditDiagnostics] = None


def get_edit_diagnostics() -> EditDiagnostics:
    global _DIAGNOSTICS
    if _DIAGNOSTICS is None:
        _DIAGNOSTICS = EditDiagnostics()
    return _DIAGNOSTICS
