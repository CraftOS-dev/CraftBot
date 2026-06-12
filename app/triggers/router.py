# -*- coding: utf-8 -*-
"""
app.triggers.router

SessionRouter — decides which session an incoming item belongs to.

This is the ONE routing implementation. It was extracted from AgentBase
(`_route_to_session` + context formatters); the second, near-duplicate
routing path that lived inside TriggerQueue.put() was deleted outright —
every producer sets a session_id, so it was unreachable in practice.

Routing is consulted only by the chat-message handler, only when active
tasks exist, and only AFTER the message has been durably parked — so the
LLM call here is off the persistence-critical path: a crash mid-route
loses nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent_core.core.trigger import Trigger

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class SessionRouter:
    """Routes incoming messages/triggers to existing sessions via the LLM."""

    def __init__(
        self,
        llm: Any,
        route_to_session_prompt: str,
        task_manager: Any = None,
        event_stream_manager: Any = None,
    ) -> None:
        self._llm = llm
        self._prompt = route_to_session_prompt
        self._task_manager = task_manager
        self._event_stream_manager = event_stream_manager

    def bind(self, *, task_manager: Any = None, event_stream_manager: Any = None):
        """Late-bind managers created after the router."""
        if task_manager is not None:
            self._task_manager = task_manager
        if event_stream_manager is not None:
            self._event_stream_manager = event_stream_manager

    # ─────────────────────── Routing decision ───────────────────────────────

    async def route(
        self,
        item_type: str,
        item_content: str,
        existing_sessions: str,
        source_platform: str = "default",
        current_living_ui_id: Optional[str] = None,
        recent_conversation: str = "(no recent conversation)",
    ) -> Dict[str, Any]:
        """Route incoming item to appropriate session using unified prompt.

        Args:
            item_type: Type of incoming item ("message" or "trigger")
            item_content: The content of the message or trigger description
            existing_sessions: Formatted string of existing sessions
            source_platform: The platform the message came from (e.g., "cli", "gui")
            current_living_ui_id: The Living UI page the user is currently viewing,
                if any. Used by the prompt to default context-dependent messages
                ("fix this", "it's broken") to that Living UI's task while still
                allowing explicit cross-Living-UI references to override.
            recent_conversation: Formatted recent messages across sessions for
                cross-session context (helps disambiguate "and Spanish" style
                continuations and references to completed tasks).

        Returns:
            Dict with routing decision containing:
            - action: "route" | "new"
            - session_id: The session to route to (or "new")
            - reason: Explanation of the routing decision
        """
        prompt = self._prompt.format(
            item_type=item_type,
            item_content=item_content,
            source_platform=source_platform,
            existing_sessions=existing_sessions,
            current_living_ui_id=current_living_ui_id or "(not on a Living UI page)",
            recent_conversation=recent_conversation,
        )

        logger.debug(f"[UNIFIED ROUTING PROMPT]:\n{prompt}")
        response = await self._llm.generate_response_async(
            system_prompt="You are a session routing system.",
            user_prompt=prompt,
        )
        logger.debug(f"[UNIFIED ROUTING RESPONSE]: {response}")

        try:
            result = json.loads(response)
            # Ensure action field exists for backward compatibility
            if "action" not in result:
                result["action"] = (
                    "route" if result.get("session_id", "new") != "new" else "new"
                )
            return result
        except json.JSONDecodeError:
            logger.error("[ROUTING] Failed to parse routing response JSON")
            return {
                "action": "new",
                "session_id": "new",
                "reason": "Failed to parse routing response",
            }

    # ─────────────────────── Context formatting ─────────────────────────────

    def format_sessions_for_routing(
        self, active_task_ids: List[str], triggers: Optional[List[Trigger]] = None
    ) -> str:
        """Format active sessions with rich context for routing prompt.

        Uses active task IDs from state_manager (not just triggers in queue) to ensure
        all running tasks are visible for routing decisions.

        Args:
            active_task_ids: List of task IDs from state_manager.main_state.active_task_ids
            triggers: Optional list of triggers (used to check waiting_for_reply status)

        Returns:
            Formatted string with session context for routing decisions.
        """
        if not active_task_ids:
            return "No existing sessions."

        # Build a lookup of triggers by session_id for waiting_for_reply status
        trigger_map = {}
        if triggers:
            for tr in triggers:
                if tr.session_id:
                    trigger_map[tr.session_id] = tr

        sections = []
        for i, task_id in enumerate(active_task_ids, 1):
            task = (
                self._task_manager.tasks.get(task_id) if self._task_manager else None
            )
            trigger = trigger_map.get(task_id)

            # Check waiting_for_reply from trigger OR from task state
            is_waiting = False
            if trigger and trigger.waiting_for_reply:
                is_waiting = True
            if (
                task
                and hasattr(task, "waiting_for_user_reply")
                and task.waiting_for_user_reply
            ):
                is_waiting = True

            status = "WAITING FOR REPLY" if is_waiting else "ACTIVE"
            platform = (
                trigger.payload.get("platform", "default") if trigger else "default"
            )

            lines = [
                f"--- Session {i} ---",
                f"Session ID: {task_id}",
                f"Status: {status}",
            ]

            if task:
                lines.extend(
                    [
                        f'Task Name: "{task.name}"',
                        f'Original Request: "{task.instruction}"',
                        f"Mode: {task.mode}",
                        f"Created: {task.created_at}",
                    ]
                )

                # Todo progress
                if task.todos:
                    completed = sum(1 for t in task.todos if t.status == "completed")
                    in_progress_todo = next(
                        (t for t in task.todos if t.status == "in_progress"), None
                    )
                    lines.append(
                        f"Progress: {completed}/{len(task.todos)} todos completed"
                    )
                    if in_progress_todo:
                        lines.append(
                            f'Currently working on: "{in_progress_todo.content}"'
                        )

                # Get recent events from event stream for this task
                if self._event_stream_manager and task_id:
                    stream = self._event_stream_manager.get_stream_by_id(task_id)
                    if stream and stream.tail_events:
                        # Get last 10 events for better routing context
                        # (5 was insufficient - file creation events were missed)
                        recent_events = stream.tail_events[-10:]
                        lines.append("Recent Activity:")
                        for rec in recent_events:
                            # Only truncate very long event messages (500+ chars)
                            # Short truncation caused loss of important context like file paths
                            event_line = rec.compact_line()
                            if len(event_line) > 500:
                                event_line = event_line[:497] + "..."
                            lines.append(f"  - {event_line}")
            else:
                # Fallback to trigger description if no task found
                desc = trigger.next_action_description if trigger else "Unknown task"
                lines.append(f'Description: "{desc}"')

            lines.append(f"Platform: {platform}")

            # Add Living UI context if the user is on a Living UI page
            living_ui_id = trigger.payload.get("living_ui_id") if trigger else None
            if living_ui_id:
                lines.append(f"Living UI ID: {living_ui_id}")
                try:
                    from app.living_ui import get_living_ui_manager

                    mgr = get_living_ui_manager()
                    if mgr:
                        proj = mgr.get_project(living_ui_id)
                        if proj:
                            lines.append(f"Living UI Name: {proj.name}")
                            lines.append(f"Living UI Path: {proj.path}")
                            lines.append(
                                f"  Read {proj.path}/LIVING_UI.md for app context"
                            )
                            lines.append(
                                "  If debugging issues, FIRST read these logs:"
                            )
                            lines.append(
                                f"    - {proj.path}/backend/logs/subprocess_output.log (crashes, stack traces)"
                            )
                            lines.append(
                                f"    - {proj.path}/backend/logs/frontend_console.log (frontend errors, network failures)"
                            )
                except Exception:
                    pass

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def format_recent_conversation(self, limit: int = 10) -> str:
        """Format recent conversation messages for routing context.

        Provides the routing LLM with recent conversation history so it can
        recognize messages related to completed tasks that are no longer in
        the active sessions list.

        Args:
            limit: Maximum number of recent messages to include.

        Returns:
            Formatted string of recent conversation messages.
        """
        if not self._event_stream_manager:
            return "No recent conversation history."

        recent_msgs = self._event_stream_manager.get_recent_conversation_messages(
            limit=limit
        )
        if not recent_msgs:
            return "No recent conversation history."

        lines = []
        for evt in recent_msgs:
            ts = evt.ts.strftime("%Y-%m-%d %H:%M:%S") if evt.ts else "unknown"
            line = f"[{ts}] [{evt.kind}]: {evt.message}"
            if len(line) > 300:
                line = line[:297] + "..."
            lines.append(line)

        return "\n".join(lines)
