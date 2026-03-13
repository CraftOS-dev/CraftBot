# -*- coding: utf-8 -*-
"""
core.impl.trigger.queue

TriggerQueue implementation - manages agent trigger events with priority ordering.
"""
from __future__ import annotations

import asyncio
import heapq
import json
import logging
import time
from collections import defaultdict, OrderedDict
from typing import Dict, List, Optional, Any, TYPE_CHECKING

from agent_core.decorators import profile, OperationCategory
from agent_core.core.trigger import Trigger
from agent_core.core.state import get_state_or_none

if TYPE_CHECKING:
    from agent_core.core.protocols import LLMInterfaceProtocol, TaskManagerProtocol
    from agent_core.core.task import Task
    # TaskManager type alias for backwards compatibility
    TaskManager = TaskManagerProtocol

# Logging setup
try:
    from agent_core.utils.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class TriggerQueue:
    """
    Concurrency-safe priority queue for Trigger.
    """

    def __init__(
        self,
        llm: "LLMInterfaceProtocol",
        *,
        route_to_session_prompt: str = "",
        task_manager: Optional["TaskManager"] = None,
        event_stream_manager: Optional[Any] = None,
    ) -> None:
        """
        Initialize a concurrency-safe trigger queue.

        The queue manages incoming :class:`Trigger` objects using a heap to
        preserve ordering by ``fire_at`` timestamp and priority. A shared
        :class:`asyncio.Condition` coordinates producers and consumers so agent
        loops can await triggers without busy waiting.

        Args:
            llm: Interface used to resolve conflicts between competing triggers
                for the same session.
            route_to_session_prompt: Prompt template for routing triggers to sessions.
                Should contain {item_type}, {item_content}, {existing_sessions},
                {source_platform}, and {conversation_id} placeholders.
            task_manager: Optional task manager for accessing task details during routing.
            event_stream_manager: Optional event stream manager for accessing recent events.
        """
        self._heap: List[Trigger] = []
        self._active: Dict[str, Trigger] = {}  # Triggers being processed (session_id -> trigger)
        self._cv = asyncio.Condition()
        self.llm = llm
        self._route_to_session_prompt = route_to_session_prompt
        self._task_manager = task_manager
        self._event_stream_manager = event_stream_manager

    def set_task_manager(self, task_manager: Optional["TaskManager"]) -> None:
        """Set the task manager for accessing task details during routing.

        This allows late binding of task_manager when it's created after TriggerQueue.

        Args:
            task_manager: The task manager instance to use for routing context.
        """
        self._task_manager = task_manager

    def set_event_stream_manager(self, event_stream_manager: Optional[Any]) -> None:
        """Set the event stream manager for accessing recent events during routing.

        This allows late binding of event_stream_manager when it's created after TriggerQueue.

        Args:
            event_stream_manager: The event stream manager instance.
        """
        self._event_stream_manager = event_stream_manager

    # =================================================================
    # Pretty Printer for Debugging
    # =================================================================
    def _print_queue(self, label: str) -> None:
        logger.debug("=" * 70)
        logger.debug(f"[TRIGGER QUEUE] {label}")
        logger.debug("=" * 70)

        if not self._heap:
            logger.debug("(empty)")
            return

        now = time.time()
        for i, t in enumerate(sorted(self._heap, key=lambda x: (x.fire_at, x.priority))):
            logger.debug(
                f"{i+1}. session_id={t.session_id} | "
                f"prio={t.priority} | "
                f"fire_at={t.fire_at:.6f} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.fire_at))}) | "
                f"delta={t.fire_at - now:.2f}s\n"
                f"   desc={t.next_action_description}"
            )
        logger.debug("=" * 70 + "\n")

    def create_event_stream_state(self) -> str:
        """Return formatted event stream content for trigger comparison."""
        state = get_state_or_none()
        event_stream = state.event_stream if state else None
        if event_stream:
            return (
                "Use the event stream to understand the current situation, past agent actions to craft the input parameters:\nEvent stream (oldest to newest):"
                f"\n{event_stream}"
            )
        return ""

    def create_task_state(self) -> str:
        """Return formatted task/plan context for trigger comparison."""
        state = get_state_or_none()
        current_task: Optional["Task"] = state.current_task if state else None
        if current_task:
            # Format task in LLM-friendly way (matching context_engine format)
            lines = [
                "<current_task>",
                f"Task: {current_task.name}",
                f"Instruction: {current_task.instruction}",
                "",
                "Todos:",
            ]

            if current_task.todos:
                for todo in current_task.todos:
                    if todo.status == "completed":
                        checkbox = "[x]"
                    elif todo.status == "in_progress":
                        checkbox = "[>]"
                    else:
                        checkbox = "[ ]"
                    lines.append(f"{checkbox} {todo.content}")
            else:
                lines.append("(no todos yet)")

            lines.append("</current_task>")
            return "\n".join(lines)
        return ""

    async def clear(self) -> None:
        """
        Remove all pending triggers from the queue.

        The queue is cleared under the protection of the condition variable so
        waiting consumers are notified immediately that the queue state has
        changed.
        """
        async with self._cv:
            self._heap.clear()
            self._cv.notify_all()

    # =================================================================
    # PUT
    # =================================================================

    def _format_sessions_for_routing(
        self,
        running_tasks: List["Task"],
        event_stream_manager: Optional[Any] = None,
    ) -> str:
        """Format running tasks with rich context for routing prompt.

        Args:
            running_tasks: List of currently running tasks from TaskManager
            event_stream_manager: Optional event stream manager to retrieve recent events

        Returns:
            Formatted string with session context for routing decision
        """
        if not running_tasks:
            return "No existing sessions."

        sections = []
        for i, task in enumerate(running_tasks, 1):
            # Check waiting_for_user_reply state on task
            is_waiting = getattr(task, 'waiting_for_user_reply', False)
            status = "WAITING FOR REPLY" if is_waiting else "ACTIVE"

            lines = [
                f"--- Session {i} ---",
                f"Session ID: {task.id}",
                f"Status: {status}",
                f"Task Name: \"{task.name}\"",
                f"Original Request: \"{task.instruction}\"",
                f"Mode: {task.mode}",
                f"Created: {task.created_at}",
            ]

            # Todo progress
            if task.todos:
                completed = sum(1 for t in task.todos if t.status == "completed")
                in_progress_todo = next(
                    (t for t in task.todos if t.status == "in_progress"), None
                )
                lines.append(f"Progress: {completed}/{len(task.todos)} todos completed")
                if in_progress_todo:
                    lines.append(f"Currently working on: \"{in_progress_todo.content}\"")

            # Get recent events from event stream for this task
            if event_stream_manager and task.id:
                try:
                    stream = event_stream_manager.get_stream_by_id(task.id)
                    if stream and stream.tail_events:
                        # Get last 10 events for better routing context
                        recent_events = stream.tail_events[-10:]
                        lines.append("Recent Activity:")
                        for rec in recent_events:
                            lines.append(f"  - {rec.compact_line()}")
                except Exception:
                    pass  # Gracefully handle if event stream not available

            # Add platform/conversation info if available
            platform = getattr(task, 'platform', 'default')
            conversation_id = getattr(task, 'conversation_id', 'N/A')
            lines.append(f"Platform: {platform}")
            lines.append(f"Conversation ID: {conversation_id}")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    @profile("trigger_queue_put", OperationCategory.TRIGGER)
    async def put(self, trig: Trigger, skip_merge: bool = False) -> None:
        """
        Insert a trigger into the queue, optionally merging with existing session triggers.

        When a trigger arrives for a session that already has queued work, the
        method consults the LLM to generate a new session identifier that
        represents the preferred trigger. Existing triggers for that session
        are removed so the freshest trigger wins.

        Args:
            trig: Trigger instance describing when and why the agent should act.
            skip_merge: If True, skip LLM-based trigger merging. Use for system
                        triggers that should not be merged with user triggers.
        """
        logger.debug(f"\n[PUT] Incoming trigger for session={trig.session_id} (skip_merge={skip_merge})")
        self._print_queue("BEFORE PUT")

        # Get running tasks from TaskManager (the source of truth for active sessions)
        # This includes tasks being processed (trigger consumed) AND tasks with queued triggers
        running_tasks: List["Task"] = []
        if self._task_manager:
            running_tasks = [t for t in self._task_manager.tasks.values() if t.status == "running"]

        # Skip LLM routing if:
        # 1. Trigger already has a session_id assigned (proceed with that session)
        # 2. skip_merge is True (already routed at message handler level)
        # 3. System triggers (memory_processing, task_execution, scheduled)
        trigger_type = trig.payload.get("type", "")
        is_system_trigger = trigger_type in ("memory_processing", "task_execution", "scheduled")
        has_session_id = trig.session_id is not None and trig.session_id != ""

        if has_session_id:
            logger.debug(f"[PUT] Trigger already has session_id={trig.session_id}, skipping LLM routing")
        elif len(running_tasks) > 0 and not skip_merge and not is_system_trigger and self._route_to_session_prompt:
            # Use unified routing prompt with rich task context from running tasks
            existing_sessions = self._format_sessions_for_routing(
                running_tasks,
                event_stream_manager=self._event_stream_manager,
            )

            # Format prompt with available placeholders
            usr_msg = self._route_to_session_prompt.format(
                item_type="trigger",
                item_content=trig.next_action_description,
                source_platform=trig.payload.get("platform", "default"),
                conversation_id=trig.payload.get("conversation_id", "N/A"),
                existing_sessions=existing_sessions,
            )

            logger.debug(f"[UNIFIED ROUTING PROMPT]:\n{usr_msg}")
            response = await self.llm.generate_response_async(
                system_prompt="You are a session routing system.",
                user_prompt=usr_msg,
            )
            logger.debug(f"[UNIFIED ROUTING RESPONSE]: {response}")

            # Parse routing response
            try:
                routing_result = json.loads(response)
                action = routing_result.get("action", "route")

                if action == "route":
                    matched_session_id = routing_result.get("session_id", "new")
                else:  # action == "new" or unknown
                    matched_session_id = "new"
            except (json.JSONDecodeError, TypeError):
                logger.error("[PUT] Failed to parse routing response JSON")
                matched_session_id = "new"

            # Update the incoming trigger's session ID based on routing result
            if matched_session_id != "new":
                trig.session_id = matched_session_id
                logger.debug(f"[PUT] Routed to existing session: {matched_session_id}")
            else:
                logger.debug(f"[PUT] Creating new session (no match found)")
        else:
            logger.debug(f"[PUT] Skipping LLM routing (no_running_tasks={len(running_tasks) == 0}, skip_merge={skip_merge}, is_system={is_system_trigger})")

        async with self._cv:
            # find all triggers in heap with same session_id
            same = [t for t in self._heap if t.session_id == trig.session_id]

            if same:
                logger.debug("[PUT] Existing trigger(s) found → PREFER NEW TRIGGER")
                self._print_queue("BEFORE REPLACE (PUT)")

                # Remove ALL old triggers for this session
                self._heap = [t for t in self._heap if t.session_id != trig.session_id]

                # NEW BEHAVIOUR: prefer new → push new trigger only
                heapq.heappush(self._heap, trig)

                logger.debug("[PUT] REPLACED old triggers with NEW trigger")
                self._print_queue("AFTER REPLACE (PUT)")

            else:
                logger.debug("[PUT] No existing session trigger → pushing normally")
                heapq.heappush(self._heap, trig)

            heapq.heapify(self._heap)

            self._print_queue("AFTER PUT")
            self._cv.notify()

    # =================================================================
    # GET
    # =================================================================
    @profile("trigger_queue_get", OperationCategory.TRIGGER)
    async def get(self) -> Trigger:
        """
        Retrieve the next trigger to execute, waiting until one is ready.

        The method drains all triggers that are ready to fire, merges triggers
        belonging to the same session, and returns the highest-priority
        combined trigger. If no trigger is ready, it waits until either the
        earliest trigger's ``fire_at`` time arrives or a producer notifies the
        condition.

        Returns:
            The next merged :class:`Trigger` ready for execution.
        """
        logger.debug("\n[GET] CALLED")
        self._print_queue("QUEUE BEFORE GET")

        async with self._cv:
            while True:
                now = time.time()

                # collect ready triggers
                ready: List[Trigger] = []
                while self._heap and self._heap[0].fire_at <= now:
                    ready.append(heapq.heappop(self._heap))

                if ready:
                    logger.debug(f"[GET] {len(ready)} trigger(s) are ready")
                    self._print_queue("READY BEFORE MERGE (GET)")

                    merged_ready = self._merge_ready_triggers(ready)
                    merged_ready.sort(key=lambda t: (t.priority, t.fire_at))

                    trig = merged_ready.pop(0)
                    logger.info(
                        f"[TRIGGER FIRED] session={trig.session_id} | desc={trig.next_action_description}"
                    )

                    # requeue leftover
                    for t in merged_ready:
                        heapq.heappush(self._heap, t)

                    # Track as active so fire() can find it while processing
                    if trig.session_id:
                        self._active[trig.session_id] = trig

                    self._print_queue("QUEUE AFTER GET (POST-MERGE)")
                    return trig

                # wait for next trigger
                if self._heap:
                    next_fire = self._heap[0].fire_at
                    delay = next_fire - now
                    if delay <= 0:
                        continue
                    try:
                        await asyncio.wait_for(self._cv.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        continue
                else:
                    await self._cv.wait()

    # =================================================================
    # SIZE / LIST
    # =================================================================
    async def size(self) -> int:
        """
        Count how many triggers are currently queued.

        Returns:
            The number of triggers stored in the heap.
        """
        async with self._cv:
            return len(self._heap)

    async def list_triggers(self) -> List[Trigger]:
        """
        List the triggers currently in the queue without altering order.

        Returns:
            A shallow copy of the internal trigger heap contents.
        """
        async with self._cv:
            return list(self._heap)

    # =================================================================
    # FIRE NOW
    # =================================================================
    async def fire(
        self,
        session_id: str,
        *,
        message: str | None = None,
        platform: str | None = None,
    ) -> bool:
        """
        Mark a trigger for a given session as ready to fire immediately.

        The ``fire_at`` timestamp for matching triggers is updated to the
        current time, and waiting consumers are notified. Also checks active
        triggers (currently being processed) to attach messages.

        Args:
            session_id: Identifier of the session whose trigger should fire
                now.
            message: Optional new user message to append to the trigger's
                description so the reasoning step sees it.
            platform: Optional platform identifier (e.g., "Telegram", "WhatsApp")
                to preserve message source information.

        Returns:
            ``True`` if a trigger was found (queued or active), otherwise ``False``.
        """
        async with self._cv:
            found = False

            # Check queued triggers first
            for t in self._heap:
                if t.session_id == session_id:
                    t.fire_at = time.time()
                    if message:
                        t.next_action_description += (
                            f"\n\n[NEW USER MESSAGE]: {message}"
                        )
                        if platform:
                            t.payload["pending_platform"] = platform
                    found = True

            if found:
                heapq.heapify(self._heap)  # restore heap invariant after fire_at change
                self._cv.notify()
                return True

            # Check active triggers (being processed)
            if session_id in self._active:
                t = self._active[session_id]
                if message:
                    t.next_action_description += (
                        f"\n\n[NEW USER MESSAGE]: {message}"
                    )
                    if platform:
                        t.payload["pending_platform"] = platform
                logger.debug(f"[FIRE] Attached message to active trigger for session {session_id}")
                return True

            return False

    # =================================================================
    # REMOVE SESSIONS
    # =================================================================
    async def remove_sessions(self, session_ids: list[str]) -> None:
        """
        Remove all triggers that belong to the provided session identifiers.

        Args:
            session_ids: Sessions whose queued triggers should be discarded.
                An empty list leaves the queue unchanged.
        """
        if not session_ids:
            return
        async with self._cv:
            self._heap = [t for t in self._heap if t.session_id not in session_ids]
            # Also remove from active triggers
            for sid in session_ids:
                self._active.pop(sid, None)
            heapq.heapify(self._heap)
            self._cv.notify_all()

    def mark_session_inactive(self, session_id: str) -> None:
        """
        Remove a session from active tracking when processing completes.

        This should be called when a task/session ends to clean up the
        _active dict.

        Args:
            session_id: The session that finished processing.
        """
        self._active.pop(session_id, None)

    def pop_pending_user_message(self, session_id: str) -> tuple[str | None, str | None]:
        """
        Extract and remove any pending user message from an active trigger.

        When fire() attaches a message to an active trigger via
        '[NEW USER MESSAGE]: ...', this method extracts that message
        so it can be carried forward to the next trigger.

        Args:
            session_id: The session to check for pending messages.

        Returns:
            Tuple of (message, platform). Both are None if no pending message.
        """
        if session_id not in self._active:
            return None, None

        trigger = self._active[session_id]
        marker = "\n\n[NEW USER MESSAGE]:"
        desc = trigger.next_action_description

        if marker not in desc:
            return None, None

        # Extract the message
        idx = desc.index(marker)
        message = desc[idx + len(marker):].strip()

        # Extract and remove the platform from payload
        platform = trigger.payload.pop("pending_platform", None)

        # Remove the message from the trigger to avoid duplication
        trigger.next_action_description = desc[:idx]

        logger.debug(f"[TRIGGER] Extracted pending user message for session {session_id}: {message[:50]}...")
        return message, platform

    # =================================================================
    # MERGE HELPERS
    # =================================================================
    def _merge_ready_triggers(self, ready: List[Trigger]) -> List[Trigger]:
        grouped = defaultdict(list)
        for trig in ready:
            grouped[trig.session_id].append(trig)

        result = []
        for session_id, triggers in grouped.items():
            logger.debug(f"[MERGE READY] Merging {len(triggers)} triggers for session={session_id}")
            result.append(self._merge_trigger_group(session_id, triggers))

        return result

    def _merge_trigger_group(self, session_id: Optional[str], triggers: List[Trigger]) -> Trigger:
        logger.debug(f"[MERGE GROUP] session={session_id}, count={len(triggers)}")
        triggers.sort(key=lambda t: (t.priority, t.fire_at))

        combined_payload: Dict[str, Any] = {}
        combined_desc: OrderedDict[str, None] = OrderedDict()
        priority = triggers[0].priority
        fire_at = triggers[0].fire_at

        for trig in triggers:
            priority = min(priority, trig.priority)
            fire_at = min(fire_at, trig.fire_at)

            desc = (trig.next_action_description or "").strip()
            if desc and desc not in combined_desc:
                combined_desc[desc] = None

            combined_payload.update(trig.payload)

        merged_desc = "\n\n".join(combined_desc.keys()) or triggers[0].next_action_description

        merged = Trigger(
            fire_at=fire_at,
            priority=priority,
            next_action_description=merged_desc,
            payload=combined_payload,
            session_id=session_id,
        )

        logger.debug(f"[MERGE RESULT] session={session_id}, fire_at={fire_at}, priority={priority}")
        return merged
