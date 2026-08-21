"""Walk-verify hard gate (Living UI).

Runs the ``walk_verify`` sub-agent against a RUNNING project and parses its
verdicts. Called by ``living_ui_notify_ready`` AFTER a successful launch —
success is only reported to the building agent when every feature verdict
is pass/unverified. Structural by design: the building agent cannot skip it
or grade itself.
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _runtime():
    from app.internal_action_interface import InternalActionInterface as I

    parts = (
        I.subagent_manager,
        I.action_manager,
        I.action_library,
        I.llm_interface,
        I.event_stream_manager,
    )
    return None if any(p is None for p in parts) else parts


async def run_walk_verify(
    project: Any,
    base_url: Optional[str] = None,
    project_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Run the walk_verify sub-agent for a running project.

    base_url/project_path override where the verifier drives and reads —
    used to point it at the DEV environment, where the app under test is a
    disposable copy on a hidden port, never the user's live instance.
    Defaults preserve the original behavior (the registered project).

    Returns the parsed verdict dict, or None when the sub-agent runtime is
    unavailable (headless/test contexts) — callers treat None as 'skipped',
    never as 'pass'.
    """
    runtime = _runtime()
    if runtime is None:
        return None
    mgr, action_manager, action_library, llm, event_stream_manager = runtime

    from app.subagent.runner import SubAgentRunner

    target_url = base_url or f"http://127.0.0.1:{project.port}"
    target_path = project_path or project.path
    query = (
        f"Verify the Living UI project '{project.name}'.\n"
        f"project_id: {project.id}\n"
        f"project_path: {target_path}\n"
        f"base_url: {target_url}\n"
        f"Requirements: read {target_path}/reference/requirements.md "
        f"(fallback: the feature checklist in {target_path}/LIVING_UI.md)."
    )

    sub = mgr.spawn(
        agent_type="walk_verify",
        query=query,
        parent_task_id=project.session_id,
        parent_temp_dir=None,
    )
    runner = SubAgentRunner(
        subagent_manager=mgr,
        action_manager=action_manager,
        action_library=action_library,
        event_stream_manager=event_stream_manager,
        llm_interface=llm,
    )

    # Same dedicated log file as agent-spawned sub-agents:
    # <run>/<session>/sub_walk_verify_<id>.log
    from app.logger import (
        add_subagent_log_sink,
        logger as app_logger,
        remove_subagent_log_sink,
    )

    short_id = sub.id[4:] if sub.id.startswith("sub_") else sub.id
    agent_tag = f"sub:{sub.agent_type}:{short_id}"
    log_session = project.session_id or "main"
    sink_id = add_subagent_log_sink(agent_tag, log_session)
    try:
        with app_logger.contextualize(agent=agent_tag, session=log_session):
            sub = await runner.run_to_completion(sub)
    finally:
        remove_subagent_log_sink(sink_id)

    raw = (getattr(sub, "result", None) or "").strip()
    return parse_check_report(raw)


# ---------------------------------------------------------------------------
# Check-report parsing (ported from PR #388 — pure, testable, no I/O).
# ---------------------------------------------------------------------------

_BLOCKED_MARKERS = (
    "mcp server connection lost",
    "browser mcp",
    "browser is unavailable",
    "browser tool",
    "no features could be tested",
    "could not launch a browser",
)


def _reads_as_blocked(result_text: str) -> bool:
    body = (result_text or "").lower()
    return any(marker in body for marker in _BLOCKED_MARKERS)


def parse_check_report(text: str) -> Dict[str, Any]:
    """Classify a walk_verify result. kinds:
    pass | defects | incomplete (NOT REACHED, defect-free) | blocked |
    throttled (the verifier's own LLM died — not the app, not the report)."""
    text = text or ""

    # A sub the runner aborted on consecutive LLM failures returns
    # "(sub-agent aborted — LLM unavailable: …)". That is neither an app
    # verdict nor an unparseable report: retrying LATER can succeed, and
    # counting it toward stuck punishes the app for the provider (observed
    # live 2026-08-06: two walkers died on rate limits 4 seconds apart and a
    # healthy modify went STUCK).
    if "sub-agent aborted" in text and "LLM unavailable" in text:
        return {"kind": "throttled", "passed": [], "defects": [], "raw": text}
    # The contract allows PASS|FAIL|BLOCKED, but sub-agents invent softeners —
    # "VERDICT: INCOMPLETE" and "VERDICT: PARTIAL VERIFICATION" both observed
    # live. An unknown word must NOT fall through to "blocked" (which
    # announces the app with a misleading tooling-issue warning): treat the
    # softeners as FAIL and let the defect / NOT-REACHED logic classify the
    # report into the honest "incomplete" kind.
    m = re.search(
        r"VERDICT:\s*(PASS|FAIL|BLOCKED|INCOMPLETE|PARTIAL(?:\s+\w+)?)",
        text,
        re.IGNORECASE,
    )
    verdict = m.group(1).upper() if m else None
    if verdict is not None and verdict.startswith(("INCOMPLETE", "PARTIAL")):
        verdict = "FAIL"

    # A FAIL whose body describes a blockage is a blockage wearing a FAIL
    # costume — never dispatch fixes for defects nobody observed.
    if verdict == "FAIL" and _reads_as_blocked(text):
        verdict = "BLOCKED"

    # The mirror image: a BLOCKED verdict with NO tooling evidence but real
    # per-feature lines is a partial walk wearing a BLOCKED costume (observed
    # live 2026-08-05: "BLOCKED BY: limited turns" with 1 PASS + 6 NOT
    # REACHED — it was classified unparseable and a working app went stuck
    # with 0 missions). Route it through the FAIL branch so the FEATURES
    # evidence decides: FAIL lines → defects, NOT-REACHED-only → incomplete
    # (delivered with the coverage caveat). Evidence-free BLOCKED stays
    # blocked — the caller's no-markers second-guess makes it unparseable.
    if verdict == "BLOCKED" and not _reads_as_blocked(text):
        if re.search(
            r"^-\s+.*\b(?:FAIL|NOT REACHED)\b", text, re.MULTILINE | re.IGNORECASE
        ):
            verdict = "FAIL"

    if verdict == "PASS":
        return {"kind": "pass", "passed": _passed(text), "defects": [], "raw": text}

    if verdict == "FAIL":
        # Feature lines come from the FEATURES section ONLY — prose in
        # FAILURES/BLOCKED BY must never become a work order.
        feature_section = re.split(
            r"^\s*(?:FAILURES|BLOCKED BY)\b",
            text,
            maxsplit=1,
            flags=re.MULTILINE | re.IGNORECASE,
        )[0]
        passed = _passed(feature_section)
        defects = [
            d.strip()
            for d in re.findall(
                r"^-\s+(?!.*\bNOT REACHED\b).*(?:—|–|:|-)\s*FAIL\b.*$",
                feature_section,
                re.MULTILINE,
            )
        ]
        if not defects and re.search(r"NOT REACHED", feature_section, re.IGNORECASE):
            return {"kind": "incomplete", "passed": passed, "defects": [], "raw": text}
        return {"kind": "defects", "passed": passed, "defects": defects, "raw": text}

    return {"kind": "blocked", "passed": [], "defects": [], "raw": text}


def _passed(section: str) -> list:
    return [
        f.strip()
        for f in re.findall(
            r"^-\s+(.{1,120}?)\s*(?:—|–|:|-)\s*PASS\b", section, re.MULTILINE
        )
        if f.strip()
    ]
