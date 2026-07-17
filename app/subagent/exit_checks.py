# -*- coding: utf-8 -*-
"""
Deterministic exit checks for sub-agents.

``sub_task_end(status="completed")`` consults the agent type's
``exit_checks`` before accepting: any failing check REFUSES the end and
returns the problems verbatim, so the agent spends its remaining
iterations actually resolving them instead of shipping them. This is the
same prose-to-gate conversion that fixed notify_ready/task_end/verdict
defection — applied to the last place agents could self-certify.

Every check returns a list of problem strings (empty = pass) and is
fail-open on infrastructure errors: a broken check must never wedge an
agent, only a genuinely failing artifact may.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from app.subagent.types import SubAgent


def _living_ui_project_root(paths: List[str]) -> Path | None:
    """The living_ui project root containing the written files, if any.

    A project root is ``<...>/living_ui/<project_dir>`` carrying the
    template's manifest at ``config/manifest.json``."""
    for raw in paths:
        p = Path(raw)
        for parent in p.parents:
            if (
                parent.parent.name == "living_ui"
                and (parent / "config" / "manifest.json").exists()
            ):
                return parent
    return None


def _build_passes(sub: "SubAgent") -> List[str]:
    """Ground truth for the coding agent: the project must actually BUILD
    before it can end. Failures come back grouped by root cause (a cascade is
    one thing to fix, not hundreds). Fail-open when the project root or build
    can't be located/run (infra gap, not a failing artifact)."""
    try:
        root = _living_ui_project_root(list(sub.written_files or []))
        if root is None:
            return []
        from app.workflows.living_ui.verifiers import BuildVerifier
        from app.workflows.living_ui.workspace import Workspace

        result = BuildVerifier().verify(Workspace(root))
        if result.ok:
            return []
        listed = "\n".join(result.failures[:20])
        return [
            "The app does NOT build yet — it must build before you end. Fix "
            f"these root cause(s), then verify again:\n{listed}"
        ]
    except Exception as e:
        logger.debug(f"[EXIT_CHECKS] build_passes skipped: {e}")
        return []


def _browser_verified(sub: "SubAgent") -> List[str]:
    """A software engineer TESTS their own work before shipping. This refuses
    "done" until the agent has actually driven the app in a browser — opened
    it, interacted with it, and checked the console — instead of trusting the
    code it wrote (compiling is not working).

    Judges SUCCESSFUL actions, not attempts, and fails OPEN when browser
    actions were attempted but none ever succeeded: that is a dead tool, and
    requiring evidence only a dead tool can produce makes the gate
    unsatisfiable — the agent's only legal exit becomes "failed". A missing
    tool is an infra gap, not a failing artifact. The build gate and the
    independent walk still stand behind this.
    """
    try:
        from collections import Counter

        attempts = Counter(sub.actions_run or [])
        failures = Counter(getattr(sub, "actions_failed", None) or [])
        succeeded = attempts - failures  # multiset diff: worked at least once

        def _browser(names) -> bool:
            return any("browser_" in a for a in names)

        def any_of(names, *subs):
            return any(any(s in a for s in subs) for a in names)

        # Tried the browser, nothing ever came back OK → the tool is down.
        if _browser(attempts) and not _browser(succeeded):
            logger.warning(
                "[EXIT_CHECKS] browser_verified fails OPEN: the agent attempted "
                f"{sum(v for k, v in attempts.items() if 'browser_' in k)} browser "
                "action(s) and every one errored — the browser tooling is "
                "unavailable, so it cannot be required to verify there. The "
                "build gate and the independent walk still apply."
            )
            return []

        opened = any_of(succeeded, "browser_navigate")
        interacted = any_of(
            succeeded,
            "browser_click",
            "browser_type",
            "browser_fill_form",
            "browser_select_option",
            "browser_press_key",
        )
        checked = any_of(succeeded, "browser_snapshot", "browser_console_messages")
        missing = []
        if not opened:
            missing.append("open the app (browser_navigate to the app URL)")
        if not interacted:
            missing.append(
                "USE each feature (browser_click / browser_type / fill_form)"
            )
        if not checked:
            missing.append(
                "check it responded (browser_snapshot + browser_console_messages)"
            )
        if not missing:
            return []
        return [
            "You have NOT verified the app works in a browser — compiling is "
            "not working. Before you finish you must: "
            + "; ".join(missing)
            + ". Open the running app, use every feature with real data, "
            "confirm each one actually works, then end."
        ]
    except Exception as e:
        logger.debug(f"[EXIT_CHECKS] browser_verified skipped: {e}")
        return []


_CHECKS: Dict[str, Callable[["SubAgent"], List[str]]] = {
    "build_passes": _build_passes,
    "browser_verified": _browser_verified,
}


def run_exit_checks(sub: "SubAgent", check_names) -> List[str]:
    """All problems from the named checks (empty = the agent may end)."""
    problems: List[str] = []
    for name in check_names or ():
        check = _CHECKS.get(name)
        if check is None:
            continue
        try:
            problems.extend(check(sub))
        except Exception as e:  # fail-open per check
            logger.debug(f"[EXIT_CHECKS] {name} crashed (ignored): {e}")
    return problems
