# -*- coding: utf-8 -*-
"""
app.triggers.runtime

SessionRuntimeManager — one trigger queue + one serial agent loop per session.

Every session is a standalone agent lane: its triggers are processed strictly
in order by its own consumer loop, while different sessions run their turns
concurrently (bounded by a global turn semaphore so a Agent App build can't
starve the main chat, and N sessions can't stampede the LLM provider).

Durability stays in TriggerService/TriggerStore: the runtime claims a row
when its loop picks the trigger up and acks/nacks when the turn settles.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from typing import Awaitable, Callable, Dict, Optional, TYPE_CHECKING

from agent_core.core.trigger import Trigger
from agent_core.core.impl.trigger.session_queue import (
    SessionTriggerQueue,
    QueueClosed,
)
from agent_core.core.session import MAIN_SESSION_ID
from agent_core.core.state.session import StateSession
from app.triggers.sources import TriggerSource

if TYPE_CHECKING:
    from app.triggers.service import TriggerService

try:
    from app.logger import (
        logger,
        ensure_session_log_sink,
        remove_session_log_sink,
    )
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    def ensure_session_log_sink(session_id: str) -> None:  # type: ignore[misc]
        return None

    def remove_session_log_sink(session_id: str) -> None:  # type: ignore[misc]
        return None


# How many session turns may run concurrently across all sessions. Serial
# within a session is guaranteed by the per-session loop; this bounds the
# cross-session parallelism (LLM rate limits, local resource pressure).
DEFAULT_MAX_CONCURRENT_TURNS = 3

# How long a stop/clear request waits before reporting failure. Timed-out
# turns remain stopping until they actually settle; callers must not reset
# context while old work can still write to it.
STOP_SETTLE_TIMEOUT_S = 15.0

ReactFn = Callable[[Trigger], Awaitable[None]]
StopFinalizer = Callable[[str], Awaitable[None]]


class _StopSignal:
    """Marks a session whose in-flight run the user force-stopped.

    ``requested`` distinguishes a user stop from process-shutdown
    cancellation inside the consumer loop; ``settled`` is set once the
    cancelled turn has been acked and finalized, so the stop caller can
    await full shutdown (the UI's stop-spinner ends on this).
    """

    __slots__ = ("requested", "settled", "processes_stopped")

    def __init__(self) -> None:
        self.requested = False
        self.settled = asyncio.Event()
        self.processes_stopped = asyncio.Event()


# Sources that must never be folded into another trigger's turn.
EXCLUSIVE_SOURCES: frozenset[str] = frozenset({TriggerSource.AGENT_APP_CRASH_FIX.value})

# Payload keys that identify WHICH work a trigger belongs to. Unlike routing
# fields these are not interchangeable, so they are carried across a merge
# rather than silently dropped with the rest of an extra's payload.
_IDENTITY_KEYS = ("project_id", "factory_mission_id")


def _compatible_message_origins(base: Trigger, other: Trigger) -> bool:
    """Telegram turns cannot inherit another contact's account or authority."""
    left, right = base.payload or {}, other.payload or {}
    if "telegram_bot" not in (
        left.get("integration_type"),
        right.get("integration_type"),
    ):
        return True
    keys = (
        "integration_type",
        "contact_id",
        "channel_id",
        "account",
        "is_self_message",
        "auto_reply_allowed",
        "owner_authenticated",
    )
    return all(left.get(k) == right.get(k) for k in keys)


def _merge_triggers(base: Trigger, extras: list[Trigger]) -> Trigger:
    """Fold ALL due triggers into `base` for one aggregated turn.

    No priority, no source filter: everything that is due when the loop
    claims work becomes ONE turn, as a numbered checklist in arrival
    order. User-message items show the raw message text (their deferred
    stream-write entries are carried through so react() logs each one at
    turn start); other sources show their description tagged with the
    source name. The correction rule exists because the LLM otherwise
    reads a batch like "shanghai too / londong / kuala lumpur / I mean
    london*" as the user settling on the last item and drops the rest
    (observed in production). Routing fields (platform/contact/channel)
    take the most recent non-empty value; workflow skill/action-set
    lists union.
    """
    group = [base] + extras

    items: list[str] = []
    all_entries: list[dict] = []
    user_texts: list[str] = []
    # Structured record of every NON-user cause folded into this turn
    # (including the base when it isn't a user message). The merge rewrites
    # base.next_action_description into a checklist, which erases the
    # extras' typed identity — react()'s turn-cause announcer needs it back
    # as data, not prose.
    aggregated_meta: list[dict] = []
    for t in group:
        p = t.payload or {}
        entries = p.get("queued_user_messages")
        if entries:
            # Deferred user message(s): checklist shows the raw text.
            for e in entries:
                text = (e.get("display") or e.get("content") or "").strip()
                items.append(f"[user message] {text}")
                user_texts.append((e.get("content") or text).strip())
            all_entries.extend(list(entries))
        elif t.source == TriggerSource.USER_MESSAGE.value and p.get("user_message"):
            # Pre-upgrade rehydrated user-message row.
            raw = (p.get("user_message") or "").strip()
            items.append(f"[user message] {raw}")
            user_texts.append(raw)
            all_entries.append(
                {"label": "user message", "content": raw, "display": raw}
            )
        else:
            items.append(f"[{t.source}] {t.next_action_description}")
            aggregated_meta.append(
                {
                    "source": t.source,
                    "name": p.get("schedule_name")
                    or (p.get("skill_workflow") or {}).get("skill_name")
                    or "",
                    # Full instruction, for the claim-time stream write
                    # (react()._log_trigger_claim) — the checklist prose
                    # above is for the {query} block only.
                    "description": t.next_action_description,
                }
            )

    total = len(items)
    numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(items, start=1))
    base.next_action_description = (
        f"{total} triggers fired for this session and were aggregated into "
        f"this ONE turn. Address EVERY item below, in order. A later user "
        f"message supersedes an earlier one ONLY if it explicitly corrects "
        f"or withdraws that specific message; otherwise each item is "
        f"separate work.\n"
        f"{numbered}\n"
        f"Before ending the run, verify each item above was handled."
    )

    base.payload = base.payload or {}
    for t in extras:
        p = t.payload or {}
        if p.get("platform"):
            # The origin is a coherent record. Mixing a previous owner's
            # self flag/account with the latest contact grants the wrong
            # permissions or routes replies through the wrong bot.
            for key in (
                "platform",
                "contact_id",
                "contact_name",
                "channel_id",
                "channel_name",
                "account",
                "account_alias",
                "integration_type",
                "message_id",
            ):
                base.payload[key] = p.get(key, "")
            base.payload["is_self_message"] = p.get("is_self_message") is True
            base.payload["auto_reply_allowed"] = p.get("auto_reply_allowed") is True
            base.payload["owner_authenticated"] = p.get("owner_authenticated") is True
        # Work identity, not routing: without these the factory cannot tell
        # which mission this run belonged to, so it can neither close it nor
        # redispatch it (see EXCLUSIVE_SOURCES). Never overwrite the base's
        # own identity — first one in the batch wins.
        for key in _IDENTITY_KEYS:
            if p.get(key) and not base.payload.get(key):
                base.payload[key] = p[key]
        for list_key in ("workflow_skills", "workflow_action_sets"):
            incoming = p.get(list_key)
            if incoming:
                current = list(base.payload.get(list_key) or [])
                base.payload[list_key] = list(dict.fromkeys(current + list(incoming)))
    if user_texts:
        base.payload["user_message"] = "\n\n".join(user_texts)
    if all_entries:
        base.payload["queued_user_messages"] = all_entries
    if aggregated_meta:
        base.payload["aggregated_triggers"] = aggregated_meta
    return base


class SessionRuntimeManager:
    """Owns the per-session queues and their serial consumer loops."""

    def __init__(
        self,
        react: ReactFn,
        max_concurrent_turns: int = DEFAULT_MAX_CONCURRENT_TURNS,
    ) -> None:
        self._react = react
        self._queues: Dict[str, SessionTriggerQueue] = {}
        self._loops: Dict[str, asyncio.Task] = {}
        # In-flight turn task per session, so a user stop can cancel exactly
        # the current turn without killing the session's consumer loop.
        self._turns: Dict[str, asyncio.Task] = {}
        self._stops: Dict[str, _StopSignal] = {}
        self._on_stopped: Optional[StopFinalizer] = None
        self._turn_semaphore = asyncio.Semaphore(max_concurrent_turns)
        self._running = False
        self._service: Optional["TriggerService"] = None

    def bind_service(self, service: "TriggerService") -> None:
        """Attach the durable TriggerService (claim/ack/nack + row settling)."""
        self._service = service

    def set_stop_finalizer(self, finalizer: StopFinalizer) -> None:
        """Register the run-stopped hook (AgentBase._on_run_stopped)."""
        self._on_stopped = finalizer

    def is_session_active(self, session_id: str) -> bool:
        """A turn is executing right now, or triggers are queued for this
        session. The factory supervisor's structural 'is work in flight'
        check — replaces mission-id attribution bookkeeping."""
        if session_id in self._turns:
            return True
        queue = self._queues.get(session_id)
        try:
            return bool(queue and queue.pending_count() > 0)
        except Exception:
            return False

    # ─────────────────────── Lifecycle ──────────────────────────────────────

    async def start(self) -> None:
        """Start consumer loops for every queue that exists (post-rehydrate)."""
        self._running = True
        for session_id in list(self._queues.keys()):
            self._ensure_loop(session_id)
        logger.info(f"[SessionRuntime] Started ({len(self._loops)} session loop(s))")

    async def stop(self) -> None:
        """Cancel all consumer loops (shutdown). Queued triggers stay durable."""
        self._running = False
        for task in self._loops.values():
            task.cancel()
        for task in list(self._loops.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._loops.clear()
        logger.info("[SessionRuntime] Stopped")

    # ─────────────────────── Dispatch ────────────────────────────────────────

    async def dispatch(self, trig: Trigger) -> None:
        """Route a trigger into its session's queue (main when unset)."""
        session_id = trig.session_id or MAIN_SESSION_ID
        trig.session_id = session_id
        queue = self._ensure_queue(session_id)
        try:
            await queue.put(trig)
        except QueueClosed:
            # Session deleted between emit and dispatch — settle the row.
            logger.info(
                f"[SessionRuntime] Dropping trigger for deleted session {session_id}"
            )
            if self._service:
                self._service.on_evicted([trig], None)
            return
        if self._running:
            self._ensure_loop(session_id)

    def has_pending(self, session_id: str) -> bool:
        """Whether a session has queued triggers (non-blocking)."""
        queue = self._queues.get(session_id)
        return queue.has_pending() if queue else False

    # ─────────────────────── User force-stop ─────────────────────────────────

    async def request_stop(self, session_id: str) -> bool:
        """Force-stop a session's in-flight run at the user's request.

        Kills registered child processes, cancels the current turn task
        (the loop settles it: rows acked, stop finalizer called), and drops
        queued RUN_CONTINUATION triggers — a run between turns exists only
        as those rows. User messages and scheduled triggers stay queued.

        Returns True when there was a run to stop. Awaits full settlement
        (bounded by STOP_SETTLE_TIMEOUT_S) before returning, so the caller
        can treat a successful return as "everything is shut". Raises on
        timeout or process-shutdown failure instead of claiming success.
        """
        signal = self._stops.get(session_id)
        if signal is not None:
            # Repeated stop/clear requests join the same cancellation. A
            # second cancel could interrupt the first turn's cleanup.
            await asyncio.wait_for(signal.settled.wait(), STOP_SETTLE_TIMEOUT_S)
            return True
        purged = await self._purge_continuations(session_id)
        signal = self._stops.get(session_id)
        if signal is not None:
            await asyncio.wait_for(signal.settled.wait(), STOP_SETTLE_TIMEOUT_S)
            return True
        turn = self._turns.get(session_id)
        turn_inflight = turn is not None and not turn.done()

        if not turn_inflight:
            if purged:
                # Fence fresh work while the parked run's async finalizer
                # settles. Overlapping requests join this stop as well.
                signal = self._stops[session_id] = _StopSignal()
                try:
                    if self._on_stopped:
                        await self._on_stopped(session_id)
                finally:
                    self._stops.pop(session_id, None)
                    signal.settled.set()
            return bool(purged)

        signal = self._stops.setdefault(session_id, _StopSignal())
        signal.requested = True
        turn.cancel()

        # Cancel before yielding so a naturally finishing turn cannot escape
        # settlement. The consumer holds this lane until OS work is shut down.
        try:
            from agent_core.core.impl.action.cancellation import (
                kill_session_processes,
            )

            kill = asyncio.get_running_loop().run_in_executor(
                None, kill_session_processes, session_id
            )
            # A disconnected caller must not release the lane while the
            # process-kill worker can still affect this session's next run.
            kill.add_done_callback(lambda _: signal.processes_stopped.set())
            await asyncio.shield(kill)
        except Exception as e:
            signal.processes_stopped.set()
            logger.warning(f"[SessionRuntime] Process kill failed: {e}")
            raise

        try:
            await asyncio.wait_for(signal.settled.wait(), STOP_SETTLE_TIMEOUT_S)
        except asyncio.TimeoutError:
            # Keep the lane stopping: resetting context while the old turn
            # can still write would resurrect cleared work. A retry joins
            # this signal, and normal settlement still finalizes it once.
            logger.error(
                f"[SessionRuntime] Stop settlement timed out for {session_id}; "
                "the turn is still stopping."
            )
            raise
        return True

    async def _purge_continuations(self, session_id: str) -> int:
        """Drop a session's queued run-continuation triggers."""
        queue = self._queues.get(session_id)
        if queue is None:
            return 0
        return await queue.purge(
            lambda t: t.source == TriggerSource.RUN_CONTINUATION.value
        )

    async def remove_session(self, session_id: str) -> None:
        """Tear down a deleted session's queue and loop.

        Queued triggers are discarded; the queue reports them to the
        lifecycle listener so their durable rows settle.
        """
        if session_id == MAIN_SESSION_ID:
            logger.warning("[SessionRuntime] Refusing to remove the main session")
            return
        queue = self._queues.pop(session_id, None)
        if queue is not None:
            await queue.close()
        self._turns.pop(session_id, None)
        self._stops.pop(session_id, None)
        loop_task = self._loops.pop(session_id, None)
        if loop_task is not None:
            loop_task.cancel()
            try:
                await loop_task
            except (asyncio.CancelledError, Exception):
                pass
        remove_session_log_sink(session_id)

    # ─────────────────────── Internals ───────────────────────────────────────

    def _ensure_queue(self, session_id: str) -> SessionTriggerQueue:
        queue = self._queues.get(session_id)
        if queue is None:
            queue = SessionTriggerQueue(session_id)
            if self._service is not None:
                queue.set_lifecycle_listener(self._service)
            self._queues[session_id] = queue
        return queue

    def _ensure_loop(self, session_id: str) -> None:
        existing = self._loops.get(session_id)
        if existing is not None and not existing.done():
            return
        queue = self._ensure_queue(session_id)
        self._loops[session_id] = asyncio.create_task(
            self._consume(session_id, queue),
            name=f"session-loop-{session_id}",
        )

    async def _run_turn(self, session_id: str, trig: Trigger) -> None:
        signal = self._stops.get(session_id)
        if signal is not None:
            await signal.settled.wait()
        try:
            async with self._turn_semaphore:
                await self._react(trig)
        finally:
            signal = self._stops.get(session_id)
            if signal is not None and signal.requested:
                # Also settle a turn that swallowed cancellation or returned
                # while cancellation was requested.
                raise asyncio.CancelledError

    async def _consume(self, session_id: str, queue: SessionTriggerQueue) -> None:
        """The serial agent loop for one session: claim → react → settle.

        Aggregation: after claiming a trigger, everything else already due
        (it piled up while the previous turn was running) is drained and
        merged into the SAME turn, whatever its source. All merged rows are
        claimed together and settle together. The exception is
        EXCLUSIVE_SOURCES, which keep their own turn in both directions:
        they are never drained into someone else's batch, and when one is
        the claimed trigger nothing is drained into it.
        """
        # Give this session its own log folder/sink and tag every line emitted
        # during its turns with the session id, so each session's logs land in
        # logs/<run>/<session_id>/session.log.
        ensure_session_log_sink(session_id)
        _contextualize = getattr(logger, "contextualize", None)
        session_ctx = (
            _contextualize(session=session_id)
            if _contextualize is not None
            else nullcontext()
        )

        logger.info(f"[SessionRuntime] Loop started for session {session_id}")
        # Bind the session for everything its turns run (actions, sub-agents,
        # LLM calls): the LLM layer reads the session's reasoning choice
        # through this binding.
        with session_ctx, StateSession.bind(session_id):
            while self._running:
                try:
                    trig = await queue.get()
                except QueueClosed:
                    break
                except asyncio.CancelledError:
                    raise

                # Drain everything else that is due and aggregate the whole
                # batch into this one turn — except the sources that must not
                # share a turn with anything (see EXCLUSIVE_SOURCES).
                extras: list[Trigger] = []
                if trig.source in EXCLUSIVE_SOURCES:
                    logger.info(
                        f"[SessionRuntime] {trig.source} runs alone — not "
                        f"aggregating other due triggers into it ({session_id})"
                    )
                else:
                    try:
                        extras = await queue.pop_due_batch(
                            exclude_sources=EXCLUSIVE_SOURCES,
                            predicate=lambda other: _compatible_message_origins(
                                trig, other
                            ),
                        )
                    except Exception as e:
                        logger.warning(f"[SessionRuntime] Batch drain failed: {e}")
                group = [trig] + extras

                if self._service:
                    for t in group:
                        self._service.claim(t)

                if extras:
                    logger.info(
                        f"[SessionRuntime] Aggregated {len(group)} queued "
                        f"trigger(s) ({', '.join(t.source for t in group)}) "
                        f"into one turn for {session_id}"
                    )
                    trig = _merge_triggers(trig, extras)

                try:
                    # Track capacity waits too: claimed work must not start
                    # after a stop/clear simply because another lane was busy.
                    turn = asyncio.create_task(
                        self._run_turn(session_id, trig), name=f"turn-{session_id}"
                    )
                    self._turns[session_id] = turn
                    try:
                        await turn
                    finally:
                        self._turns.pop(session_id, None)
                except asyncio.CancelledError:
                    signal = self._stops.get(session_id)
                    if signal is not None and signal.requested and self._running:
                        await signal.processes_stopped.wait()
                        # User force-stop, not process shutdown: the rows were
                        # consumed by user intent — ack them (nack would
                        # redeliver and restart the very work the user
                        # killed), drop any continuation the dying turn
                        # managed to enqueue, finalize, and keep looping.
                        if self._service:
                            for t in group:
                                try:
                                    await self._service.ack(t)
                                except Exception as e:
                                    logger.warning(
                                        f"[SessionRuntime] stop ack failed: {e}"
                                    )
                        try:
                            await self._purge_continuations(session_id)
                            if self._on_stopped:
                                await self._on_stopped(session_id)
                        except Exception as e:
                            logger.error(
                                f"[SessionRuntime] Stop finalize failed for "
                                f"{session_id}: {e}",
                                exc_info=True,
                            )
                        finally:
                            self._stops.pop(session_id, None)
                            signal.settled.set()
                        continue
                    # Shutdown mid-turn: leave the rows CLAIMED — boot-time
                    # rehydration reclaims them (at-least-once delivery).
                    raise
                except Exception as e:
                    logger.error(
                        f"[SessionRuntime] Turn failed for {session_id}: {e}",
                        exc_info=True,
                    )
                    if self._service:
                        for t in group:
                            try:
                                await self._service.nack(t, str(e))
                            except Exception as nack_err:
                                logger.error(
                                    f"[SessionRuntime] nack failed: {nack_err}"
                                )
                    continue

                if self._service:
                    for t in group:
                        try:
                            await self._service.ack(t)
                        except Exception as e:
                            logger.warning(f"[SessionRuntime] ack failed: {e}")
        logger.info(f"[SessionRuntime] Loop ended for session {session_id}")
