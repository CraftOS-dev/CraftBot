# -*- coding: utf-8 -*-
"""Step programs — code-chosen turns for any agentic loop.

A workflow (or sub-agent type) may carry a ``step_program``: a callable the
driver consults BEFORE asking the LLM what to do next. When it returns a
step, code has decided the turn; the LLM is consulted only where the step
explicitly delegates. This is the structural fix for advisory rails that a
session-cached model never re-reads (task_state reaches the model only at
session creation) — code doesn't need to be reminded of the state machine,
it IS the state machine.

Contract — ``step_program(task, turn_context) -> Optional[dict]``:

    turn_context = {"query": str, "user_message": Optional[str], ...}
    (drivers may add keys; programs must tolerate extras)

    None                     → no opinion; the normal LLM decide runs.
    {"kind": "actions",      → execute these directly, NO decision LLM call.
     "label": str,             Multi-action steps are the norm (a fix round =
     "actions": [               rebuild spawn + repair spawn + validate).
       {"action_name": str,
        "parameters": dict}]}
    {"kind": "llm",          → ONE bounded LLM decision. ``prompt`` is a
     "purpose": str,           complete code-built instruction, guaranteed
     "prompt": str,            to reach the model THIS turn (delta turns
     "allowed_actions":        carry it too, not just session creation).
       Optional[list]}         Non-allowed actions are dropped post-parse.
    {"kind": "wait",         → do nothing this turn (task drivers: the empty
     "label": str}             no-op decision; blocking drivers treat it as
                               malformed and fall back to the LLM).
    {"kind": "end",          → end the run honestly. Task drivers convert to
     "status": "complete"      a task_end action (which still passes the
        | "abort",             task_end completion gate); the sub-agent
     "reason": str,            driver ends the sub directly.
     "summary": str}

Failure semantics (weak-model-proof by construction): a step program that
raises, or returns a malformed step, LOUDLY logs and yields the turn to the
normal LLM decide — a broken program degrades to today's behavior, it never
wedges the loop.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.agentic._log import logger

STEP_KINDS = ("actions", "llm", "wait", "end")


def consult_step_program(
    step_program: Optional[Callable],
    task: Any,
    turn_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Ask the program for this turn's step. None = the LLM decides.

    Fail-open on every path: program exceptions and malformed steps are
    logged loudly and treated as "no opinion".
    """
    if step_program is None:
        return None
    try:
        step = step_program(task, dict(turn_context or {}))
    except Exception:
        logger.exception(
            "[AGENTIC:STEP] step program crashed — falling back to LLM decide"
        )
        return None
    if step is None:
        return None
    error = validate_step(step)
    if error:
        logger.error(
            f"[AGENTIC:STEP] malformed step ({error}) — falling back to LLM "
            f"decide. Step: {str(step)[:300]!r}"
        )
        return None
    return step


def validate_step(step: Any) -> Optional[str]:
    """None if ``step`` honors the contract, else a description of the hole."""
    if not isinstance(step, dict):
        return "step is not a dict"
    kind = step.get("kind")
    if kind not in STEP_KINDS:
        return f"unknown kind {kind!r} (expected one of {STEP_KINDS})"
    if kind == "actions":
        actions = step.get("actions")
        if not isinstance(actions, list) or not actions:
            return "'actions' must be a non-empty list"
        for i, entry in enumerate(actions):
            if not isinstance(entry, dict) or not entry.get("action_name"):
                return f"actions[{i}] missing 'action_name'"
            params = entry.get("parameters")
            if params is not None and not isinstance(params, dict):
                return f"actions[{i}] 'parameters' is not a dict"
    elif kind == "llm":
        if not str(step.get("prompt") or "").strip():
            return "'llm' step has an empty 'prompt'"
        allowed = step.get("allowed_actions")
        if allowed is not None and not isinstance(allowed, (list, tuple)):
            return "'allowed_actions' is not a list"
    elif kind == "end":
        if step.get("status") not in (None, "complete", "abort"):
            return f"'end' status {step.get('status')!r} not complete/abort"
    return None


def step_to_decisions(step: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """A validated actions/wait/end step as task-driver decision payloads.

    Returns None for "llm" steps — those run through the normal decide
    path. The label rides in ``reasoning`` so it lands in the event stream
    and UI exactly like model reasoning would.
    """
    kind = step.get("kind")
    if kind == "llm":
        return None
    if kind == "actions":
        label = str(step.get("label") or "Executing workflow step.")
        return [
            {
                "action_name": entry["action_name"],
                "parameters": dict(entry.get("parameters") or {}),
                "reasoning": label,
            }
            for entry in step["actions"]
        ]
    if kind == "wait":
        return [
            {
                "action_name": "",
                "parameters": {},
                "reasoning": str(step.get("label") or "Waiting for user input."),
            }
        ]
    if kind == "end":
        return [
            {
                "action_name": "task_end",
                "parameters": {
                    "status": step.get("status") or "complete",
                    "reason": str(
                        step.get("reason") or "Workflow step program ended the task."
                    ),
                    "summary": str(step.get("summary") or ""),
                },
                "reasoning": str(step.get("label") or "Ending the task."),
            }
        ]
    return None
