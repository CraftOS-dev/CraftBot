# -*- coding: utf-8 -*-
"""
core.impl.action.idempotency

Idempotency guard protocol for irreversible actions.

Actions flagged ``irreversible=True`` (send email/message, post publicly)
have a real crash window today: the side effect happens first, the
``action_end`` record is persisted after. A crash in between leaves the
effect done with no durable record — and on resume the LLM, re-reading the
event stream, sees no completion and may re-execute it.

The guard turns "did this already run?" into a hard database check:

- ``begin()`` is called BEFORE execution. It durably records intent and
  decides: proceed (fresh work), short-circuit with the stored output
  (this exact run already completed), or refuse with a warning (a previous
  attempt was interrupted and the side effect MAY have happened — verify
  or confirm with the user instead of blindly re-sending).
- ``complete()`` is called AFTER execution with the outcome.

The implementation (the activity ledger on sessions.db) lives in the app
layer; ActionManager only knows this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass
class GuardDecision:
    """begin()'s verdict for one irreversible action execution."""

    proceed: bool
    idem_key: Optional[str] = None
    # Set when this exact run already completed: returned as the action's
    # output instead of re-executing the side effect.
    stored_output: Optional[Dict[str, Any]] = None
    # Set when a previous attempt was interrupted mid-flight: a warning the
    # LLM sees as the action result instead of a blind re-execution.
    note: Optional[str] = None


@runtime_checkable
class IdempotencyGuard(Protocol):
    """Pre/post execution hooks for irreversible actions."""

    def begin(
        self,
        action_name: str,
        input_data: Dict[str, Any],
        session_id: Optional[str],
    ) -> GuardDecision:
        """Record intent durably and decide whether execution may proceed."""
        ...

    def complete(
        self,
        idem_key: str,
        status: str,
        outputs: Optional[Dict[str, Any]],
    ) -> None:
        """Record the outcome of an execution begin() allowed."""
        ...
