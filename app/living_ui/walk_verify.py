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


async def run_walk_verify(project: Any) -> Optional[Dict[str, Any]]:
    """Run the walk_verify sub-agent for a running project.

    Returns the parsed verdict dict, or None when the sub-agent runtime is
    unavailable (headless/test contexts) — callers treat None as 'skipped',
    never as 'pass'.
    """
    runtime = _runtime()
    if runtime is None:
        return None
    mgr, action_manager, action_library, llm, event_stream_manager = runtime

    from app.subagent.runner import SubAgentRunner

    query = (
        f"Verify the Living UI project '{project.name}'.\n"
        f"project_id: {project.id}\n"
        f"project_path: {project.path}\n"
        f"base_url: http://127.0.0.1:{project.port}\n"
        f"Requirements: read {project.path}/reference/requirements.md "
        f"(fallback: the feature checklist in {project.path}/LIVING_UI.md)."
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
    pass | defects | incomplete (NOT REACHED, defect-free) | blocked."""
    text = text or ""
    m = re.search(r"VERDICT:\s*(PASS|FAIL|BLOCKED)", text, re.IGNORECASE)
    verdict = m.group(1).upper() if m else None

    # A FAIL whose body describes a blockage is a blockage wearing a FAIL
    # costume — never dispatch fixes for defects nobody observed.
    if verdict == "FAIL" and _reads_as_blocked(text):
        verdict = "BLOCKED"

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
