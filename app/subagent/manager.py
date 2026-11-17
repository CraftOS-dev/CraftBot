# -*- coding: utf-8 -*-
"""
SubAgentManager — registry and lifecycle owner for sub-agents.

A deliberate parallel to ``SessionManager`` with NONE of the side effects
that would make a sub-agent visible in the UI as a chat, persist it, or
report it to a chatserver. A sub-agent gets its own event stream and its
own LLM session history; nothing of the spawning session's context.

Lifecycle:

- :meth:`spawn` — register a new ``SubAgent`` and create its event stream.
- :meth:`run` — drive it until its run ends (SubAgentRunner), then
  :meth:`release` it. Both ``spawn_subagent`` and the Agent-App verifier
  start sub-agents this way.
- :meth:`end` — mark it terminal (status + result + breadcrumb event).
  Called from inside the ``sub_task_end`` action, so the stream stays alive:
  the action's ``action_end`` still has to be logged to it.
- :meth:`release` — drop its stream, LLM session and record once the run
  is over.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from agent_core.core.event_stream.event import EventType
from agent_core.core.session import MAIN_SESSION_ID
from app.logger import add_subagent_log_sink, logger, remove_subagent_log_sink
from app.subagent.registry import get_subagent_definition
from app.subagent.runner import SubAgentRunner
from app.subagent.types import SubAgent

if TYPE_CHECKING:
    from agent_core.core.impl.action.library import ActionLibrary
    from agent_core.core.impl.action.manager import ActionManager
    from app.event_stream import EventStreamManager
    from app.llm import LLMInterface
    from app.session.session_manager import SessionManager


class SubAgentManager:
    """Owns the lifecycle of all in-flight sub-agents."""

    def __init__(
        self,
        event_stream_manager: "EventStreamManager",
        llm_interface: "LLMInterface",
        action_library: "ActionLibrary",
        action_manager: "ActionManager",
        session_manager: "SessionManager",
    ):
        self.event_stream_manager = event_stream_manager
        self.llm_interface = llm_interface
        self.action_library = action_library
        self.action_manager = action_manager
        self.session_manager = session_manager
        self.subagents: Dict[str, SubAgent] = {}

    # ------------------------------------------------------------------
    # Spawn / run
    # ------------------------------------------------------------------

    def spawn(
        self,
        agent_type: str,
        query: str,
        parent_session_id: Optional[str] = None,
    ) -> SubAgent:
        """
        Register a new sub-agent and set up its isolated event stream.

        Args:
            agent_type: Name of a sub-agent type registered in
                :mod:`app.subagent.registry`.
            query: The full instruction for the sub-agent. Must be
                self-contained — the sub-agent has no access to the
                parent's context.
            parent_session_id: The session whose turn spawns it.

        Raises:
            ValueError: for an unknown ``agent_type``.
        """
        definition = get_subagent_definition(agent_type)
        sub = SubAgent(
            id=f"sub_{uuid.uuid4().hex[:8]}",
            agent_type=agent_type,
            parent_session_id=parent_session_id,
            query=query,
            compiled_actions=definition.compiled_actions,
        )
        self.subagents[sub.id] = sub

        # Its workspace lives inside the spawning session's: oversized action
        # outputs are saved there (EventStream._externalize_message), so the
        # parent can still read paths the result cites, and they go with
        # that session's workspace.
        workspace = self._parent_workspace(parent_session_id) / sub.id
        workspace.mkdir(parents=True, exist_ok=True)
        self.event_stream_manager.create_stream(sub.id, temp_dir=workspace)
        self.event_stream_manager.log(
            kind="subagent_start",
            message=f"Sub-agent of type '{agent_type}' started.",
            event_type=EventType.INTERNAL,
            display_message=f"subagent[{agent_type}] start",
            task_id=sub.id,
        )

        logger.info(
            f"[SubAgentManager] Spawned {sub.id} type={agent_type} "
            f"parent={parent_session_id}"
        )
        return sub

    async def run(self, sub: SubAgent) -> SubAgent:
        """Drive ``sub`` until its run ends, then release it.

        Its log lines are tagged "sub:<type>:<id>" and also go to a file of
        their own inside the spawning session's log folder.
        """
        tag = f"sub:{sub.agent_type}:{sub.id.removeprefix('sub_')}"
        log_session = sub.parent_session_id or MAIN_SESSION_ID
        sink = add_subagent_log_sink(tag, log_session)
        try:
            with logger.contextualize(agent=tag, session=log_session):
                try:
                    await SubAgentRunner(self, sub).run()
                except Exception as e:
                    # A bug, not the model: the runner ends runs itself.
                    logger.exception(f"[SubAgentManager] {sub.id} crashed: {e}")
                    self.end(sub.id, "error", f"(sub-agent crashed: {e})")
                finally:
                    self.release(sub.id)
        finally:
            remove_subagent_log_sink(sink)
        return sub

    def _parent_workspace(self, parent_session_id: Optional[str]) -> Path:
        """The spawning session's workspace (the main session's when there
        is no spawning session)."""
        session = self.session_manager.get(parent_session_id) or self.session_manager.main
        return Path(session.workspace_dir)

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

        Sets the status/result and writes one ``subagent_end`` breadcrumb
        to the child stream. The stream stays alive: this is called from
        inside the ``sub_task_end`` action, whose ``action_end`` the
        ActionManager logs after the action body returns. :meth:`run`
        releases it once the run is over.

        Idempotent — repeat calls on a terminal sub-agent are ignored.
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
            event_type=EventType.INTERNAL,
            display_message=f"subagent[{sub.agent_type}] {status}",
            task_id=sub_id,
        )

        logger.info(
            f"[SubAgentManager] Ended {sub_id} status={status} "
            f"iterations={sub.iterations}"
        )

    # ------------------------------------------------------------------
    # Release — resource teardown
    # ------------------------------------------------------------------

    def release(self, sub_id: str) -> None:
        """
        Drop a finished sub-agent: its event stream (the removal listeners
        drain it to the UI and close its Mini Browser tabs), its LLM session
        and its record. Idempotent.
        """
        if self.event_stream_manager.has_stream(sub_id):
            self.event_stream_manager.remove_stream(sub_id)
        self.llm_interface.end_all_session_caches(sub_id)
        if self.subagents.pop(sub_id, None) is not None:
            logger.debug(f"[SubAgentManager] Released {sub_id}")


__all__ = ["SubAgentManager"]
