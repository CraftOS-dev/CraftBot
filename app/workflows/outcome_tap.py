# -*- coding: utf-8 -*-
"""Generic spawn-outcome tap — the platform half of the produce-and-verify
loop for domains WITHOUT bespoke infrastructure.

The engine's stages spawn workers/checkers but never observe results;
recorders are fed by TAPS. Living UI has a custom tap (construction_events,
which also feeds its build visualization). Every other domain gets this
one for free: when a ``spawn_subagent`` action ends and its inputs carry
the GENERIC routing keys (``workflow_name`` + ``workflow_state_dir``,
added by :meth:`Workflow.spawn_context`), the outcome is routed to the
owning workflow's recorder:

- ``agent_type == workflow.checker_agent`` → ``record_check_outcome``
- ``agent_type == workflow.worker_agent``  → for workflows with NO
  ``stage_action`` (no platform build/deploy pipeline), the worker's own
  completion IS the staging signal → ``record_work_outcome``. Workflows
  WITH a stage_action record work outcomes from that pipeline instead,
  and this tap deliberately skips their workers.

Opting out: override ``spawn_context`` without calling super() (drop the
routing keys) — Living UI does exactly that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from agent_core.core.registry.extensions import register_hook
from agent_core.core.registry.task_workflows import get_workflow

# run_id -> spawn inputs, captured at action_start (the end hook does not
# receive inputs). Bounded, same belt-and-braces as construction_events.
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_MAX = 200


def _on_action_start(run_id, action, input_data, parent_id, started_at) -> None:
    try:
        if getattr(action, "name", "") != "spawn_subagent":
            return
        if not isinstance(input_data, dict):
            return
        if "workflow_name" not in input_data:
            return  # not a generically-routed spawn (e.g. Living UI's)
        if len(_PENDING) >= _PENDING_MAX:
            _PENDING.pop(next(iter(_PENDING)), None)
        _PENDING[run_id] = dict(input_data)
    except Exception:
        pass


def _on_action_end(run_id, action, outputs, status, parent_id, ended_at) -> None:
    try:
        inputs = _PENDING.pop(run_id, None)
        if not inputs:
            return
        workflow = get_workflow(str(inputs.get("workflow_name") or ""))
        state_dir = str(inputs.get("workflow_state_dir") or "")
        if workflow is None or not state_dir:
            return
        out = outputs if isinstance(outputs, dict) else {}
        agent_type = str(inputs.get("agent_type") or "")
        sub_status = str(out.get("status") or status or "")
        result_text = str(out.get("result") or "")

        if agent_type == getattr(workflow, "checker_agent", None):
            workflow.record_check_outcome(Path(state_dir), sub_status, result_text)
            return

        if agent_type == getattr(workflow, "worker_agent", None) and not getattr(
            workflow, "stage_action", None
        ):
            ok = sub_status == "completed"
            workflow.record_work_outcome(
                Path(state_dir),
                {
                    "status": "success" if ok else "error",
                    "step": "worker",
                    "errors": [] if ok else [result_text[:500] or sub_status],
                },
            )
    except Exception as e:
        logger.debug(f"[WORKFLOWS:TAP] spawn outcome routing skipped: {e}")


def register() -> None:
    register_hook("action_start", _on_action_start)
    register_hook("action_end", _on_action_end)


register()
