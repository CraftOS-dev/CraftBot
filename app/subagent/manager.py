# -*- coding: utf-8 -*-
"""
SubAgentManager — registry and lifecycle owner for sub-agents.

This is a deliberate parallel to ``TaskManager`` but with NONE of the side
effects that would make a sub-agent visible in the UI, persisted to disk,
or reported to a chatserver. It only reuses the event-stream buffer and
LLM session-cache primitives, which are pure data structures.

Lifecycle is split into three operations to keep the event-stream usable
across all of them:

- :meth:`spawn` — register a new ``SubAgent`` and create its event stream.
- :meth:`end` — mark the sub-agent terminal (status + result + breadcrumb
  event). Safe to call from inside the ``sub_task_end`` action because the
  stream stays alive — the subsequent ``action_end`` log for ``sub_task_end``
  still routes to the child stream.
- :meth:`release` — actually tear down the child's event stream and LLM
  session caches. Called by the runner AFTER its loop exits, so every
  log for the terminating action has already fired.

What it deliberately does NOT do at any stage:
- Does NOT touch ``TaskManager.tasks`` or call ``create_task``.
- Does NOT call ``state_manager.on_task_created`` (the UI hot path).
- Does NOT call ``_on_task_persist`` (no SessionStorage row).
- Does NOT log to the main stream.
- Does NOT update ``current_task_id`` agent property.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from app.logger import logger
from app.subagent.registry import get_subagent_definition
from app.subagent.types import SubAgent

if TYPE_CHECKING:
    from app.event_stream import EventStreamManager
    from app.llm import LLMInterface


class SubAgentManager:
    """Owns the lifecycle of all in-flight sub-agents."""

    def __init__(
        self,
        event_stream_manager: "EventStreamManager",
        llm_interface: "LLMInterface",
    ):
        self.event_stream_manager = event_stream_manager
        self.llm_interface = llm_interface
        self.subagents: Dict[str, SubAgent] = {}

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------

    def spawn(
        self,
        agent_type: str,
        query: str,
        parent_task_id: Optional[str] = None,
        parent_temp_dir: Optional[str] = None,
    ) -> SubAgent:
        """
        Register a new sub-agent and set up its isolated event stream.

        Args:
            agent_type: Name of a sub-agent type registered in
                :mod:`app.subagent.registry` (one of the files under
                :mod:`app.subagent.definitions`).
            query: The full instruction for the sub-agent. Must be
                self-contained — the sub-agent has no access to the
                parent's context.
            parent_task_id: Optional id of the task that spawned this
                sub-agent, for logging only.
            parent_temp_dir: Optional temp directory of the spawning task.
                When set, the child's event stream externalizes oversized
                action outputs into ``<parent_temp_dir>/<sub_id>/`` (same
                mechanism as the main agent). Nesting under the parent's
                temp dir means the files outlive the sub-agent — the parent
                can still grep paths cited in the child's result — and are
                removed by the parent task's normal temp-dir cleanup.
                When None (e.g. conversation-mode spawn), externalization
                stays off, preserving the previous behaviour.

        Returns:
            The newly created :class:`SubAgent`.
        """
        defn = get_subagent_definition(agent_type)

        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        sub = SubAgent(
            id=sub_id,
            agent_type=agent_type,
            parent_task_id=parent_task_id,
            query=query,
            compiled_actions=defn.compiled_actions,
        )
        self.subagents[sub_id] = sub

        # Isolated event stream. EventStreamManager.create_stream is a pure
        # data-structure op — no UI/chatserver hooks fire here. The temp_dir
        # enables output externalization (EventStream._externalize_message);
        # the directory itself is created lazily on first externalized event.
        sub_temp_dir = Path(parent_temp_dir) / sub_id if parent_temp_dir else None
        self.event_stream_manager.create_stream(sub_id, temp_dir=sub_temp_dir)

        # Drop a single bootstrap event onto the CHILD's stream only.
        # The parent stream never sees it.
        self.event_stream_manager.log(
            kind="subagent_start",
            message=(
                f"Sub-agent of type '{agent_type}' started.\n"
                f"Query: {query}"
            ),
            display_message=f"subagent[{agent_type}] start",
            task_id=sub_id,
        )

        logger.info(
            f"[SubAgentManager] Spawned {sub_id} type={agent_type} "
            f"parent={parent_task_id}"
        )
        return sub

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, sub_id: str) -> Optional[SubAgent]:
        return self.subagents.get(sub_id)

    # ------------------------------------------------------------------
    # End — status update only, no resource teardown
    # ------------------------------------------------------------------

    def end(self, sub_id: str, status: str, result: str) -> None:
        """
        Mark a sub-agent terminal.

        This is intentionally **lightweight**: it sets the status/result,
        writes one ``subagent_end`` breadcrumb event to the child stream,
        and returns. The stream and any LLM session caches are kept alive
        because this method is called from inside the ``sub_task_end``
        action — the ActionManager still has to log ``action_end`` for
        ``sub_task_end`` after the action body returns, and that log must
        route to the child's stream (not the parent's main stream).

        Resource teardown happens in :meth:`release`, which the
        ``SubAgentRunner`` calls after its loop exits.

        Idempotent — repeat calls on a terminal sub-agent are ignored so
        a batch with multiple ``sub_task_end`` calls can't corrupt state.
        """
        sub = self.subagents.get(sub_id)
        if sub is None:
            logger.warning(f"[SubAgentManager] end() on unknown sub-agent: {sub_id}")
            return
        if sub.is_terminal():
            logger.debug(
                f"[SubAgentManager] end() called on already-terminal {sub_id} "
                f"(status={sub.status}); ignoring"
            )
            return

        sub.terminate(status=status, result=result)

        # Final breadcrumb on the child's stream (parent stream untouched).
        self.event_stream_manager.log(
            kind="subagent_end",
            message=f"Sub-agent ended with status '{status}'.",
            display_message=f"subagent[{sub.agent_type}] {status}",
            task_id=sub_id,
        )

        logger.info(
            f"[SubAgentManager] Ended {sub_id} status={status} "
            f"iterations={sub.iterations}"
        )

    # ------------------------------------------------------------------
    # Release — resource teardown (called by runner, post-loop)
    # ------------------------------------------------------------------

    def release(self, sub_id: str) -> None:
        """
        Tear down the per-sub-agent event stream and LLM session caches.

        Must be called AFTER every action lifecycle log for this sub-agent
        has fired. The runner calls it once, after ``run_to_completion``'s
        loop exits, so any ``action_end`` logged by ``sub_task_end`` is
        still routed to the child stream.
        """
        sub = self.subagents.get(sub_id)
        if sub is None:
            logger.debug(f"[SubAgentManager] release() on unknown sub-agent: {sub_id}")
            return

        self.event_stream_manager.remove_stream(sub_id)
        self.llm_interface.end_all_session_caches(sub_id)
        logger.debug(
            f"[SubAgentManager] Released {sub_id} (stream + session caches)"
        )

    # ------------------------------------------------------------------
    # Test / inspection helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Forget every tracked sub-agent. Test-only."""
        for sub_id in list(self.subagents.keys()):
            self.event_stream_manager.remove_stream(sub_id)
        self.subagents.clear()


__all__ = ["SubAgentManager"]
