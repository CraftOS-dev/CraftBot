# -*- coding: utf-8 -*-
"""Verifiers — pluggable "is the app actually working?" checks (Brick 2).

A Verifier answers ONE question against the real Workspace and returns
pass/fail plus concrete, actionable failures. "Done" = every registered
verifier passes. This is the seam that lets capability grow without touching
the agent loop (CODING_AGENT_PLAN.md):

    Phase 1:  [BuildVerifier]                      → app builds
    Phase 2:  [BuildVerifier, LaunchVerifier]      → app launches, console clean
    Phase 3:  + WalkVerifier                       → flows work in a browser

Each new phase adds a Verifier object; the loop that consumes `List[Verifier]`
never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from app.workflows.living_ui.workspace import Workspace


@dataclass
class VerifyResult:
    ok: bool
    failures: List[str]  # empty when ok; else actionable, root-cause-first


class Verifier(ABC):
    """One check against the running/built project."""

    name: str = "verifier"

    @abstractmethod
    def verify(self, workspace: Workspace) -> VerifyResult:  # pragma: no cover
        ...


class BuildVerifier(Verifier):
    """Passes when the project builds. On failure it reports ONE line per root
    cause (not per error line): a cascade of 590 identical
    "Cannot find module '@/lib/utils'" errors becomes a single instruction to
    fix the one root — the "fix causes, not symptoms" principle, enforced."""

    name = "build"

    def verify(self, workspace: Workspace) -> VerifyResult:
        result = workspace.build()
        if result.ok:
            return VerifyResult(ok=True, failures=[])
        failures: List[str] = []
        for _cause, group in result.grouped():
            sample = group[0]
            n = len(group)
            head = f"{sample.code}: {sample.message}"
            if n > 1:
                failures.append(
                    f"{head}  — {n}× (e.g. {sample.where}); ONE root cause, fix it once"
                )
            else:
                failures.append(f"{head}  ({sample.where})")
        if not failures:
            # build failed but no structured errors parsed (e.g. a vite/rollup
            # error) — surface the raw tail so the agent still has something real.
            failures.append("Build failed:\n" + result.raw[-1500:])
        return VerifyResult(ok=False, failures=failures)
