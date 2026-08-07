# -*- coding: utf-8 -*-
"""
app.triggers.runtime

SessionRuntimeManager — one trigger queue + one serial agent loop per session.

Every session is a standalone agent lane: its triggers are processed strictly
in order by its own consumer loop, while different sessions run their turns
concurrently (bounded by a global turn semaphore so a Living UI build can't
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

# How long a user force-stop waits for the cancelled turn to settle before
# finalizing anyway. Cancellation is normally near-instant (LLM HTTP calls
# and async actions unwind at the next await); this guard only exists so a
# stuck await can never leave the UI on "stopping" forever.
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

    __slots__ = ("requested", "settled")

    def __init__(self) -> None:
        self.requested = False
        self.settled = asyncio.Event()


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
        for key in ("platform", "contact_id", "channel_id"):
            if p.get(key):
                base.payload[key] = p[key]
        if p.get("is_self_message"):
            base.payload["is_self_message"] = True
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
        can treat the return as "everything is shut".
        """
        logger.warning("Stop requested ()")
        purged = await self._purge_continuations(session_id)
        logger.warning("Purging continuations ()")
        turn = self._turns.get(session_id)
        turn_inflight = turn is not None and not turn.done()

        if not turn_inflight:
            if purged and self._on_stopped:
                # The run lived only as queued continuation rows.
                await self._on_stopped(session_id)
            return bool(purged)

        signal = self._stops.setdefault(session_id, _StopSignal())
        signal.requested = True

        # Kill real OS work first so pool threads blocked on a child process
        # unblock, then cancel the turn's await chain. Blocking kill runs in
        # a worker thread to keep the event loop free.
        try:
            from agent_core.core.impl.action.cancellation import (
                kill_session_processes,
            )

            await asyncio.get_running_loop().run_in_executor(
                None, kill_session_processes, session_id
            )
        except Exception as e:
            logger.warning(f"[SessionRuntime] Process kill failed: {e}")

        logger.warning("Cancelling turn ()")
        turn.cancel()
        try:
            await asyncio.wait_for(signal.settled.wait(), STOP_SETTLE_TIMEOUT_S)
            logger.warning("Turn settled ()")
        except asyncio.TimeoutError:
            # The turn is stuck in a non-cancellable await. Finalize anyway:
            # the UI must reach idle, and the abandoned coroutine can no
            # longer enqueue continuations once its triggers settle.
            logger.error(
                f"[SessionRuntime] Stop settlement timed out for {session_id}; "
                "finalizing forcefully."
            )
            self._stops.pop(session_id, None)
            await self._purge_continuations(session_id)
            if self._on_stopped:
                await self._on_stopped(session_id)
        return True

    async def _purge_continuations(self, session_id: str) -> int:
        """Drop a session's queued run-continuation triggers."""
        """I need to make a change here"""
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

    async def _consume(self, session_id: str, queue: SessionTriggerQueue) -> None:
        """The serial agent loop for one session: claim → react → settle.

        Aggregation: after claiming a trigger of an aggregatable source,
        any same-source triggers already due (they piled up while the
        previous turn was running) are drained and merged into the SAME
        turn. All merged rows are claimed together and settle together.
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
        with session_ctx:
            while self._running:
                try:
                    trig = await queue.get()
                except QueueClosed:
                    break
                except asyncio.CancelledError:
                    raise

                # Drain EVERYTHING else that is due — all sources — and
                # aggregate the whole batch into this one turn.
                extras: list[Trigger] = []
                try:
                    extras = await queue.pop_due_batch()
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
                    async with self._turn_semaphore:
                        # The turn runs as its own task so request_stop can
                        # cancel exactly this turn without tearing down the
                        # session loop.
                        turn = asyncio.create_task(
                            self._react(trig), name=f"turn-{session_id}"
                        )
                        self._turns[session_id] = turn
                        try:
                            await turn
                        finally:
                            self._turns.pop(session_id, None)
                except asyncio.CancelledError:
                    signal = self._stops.get(session_id)
                    if signal is not None and signal.requested and self._running:
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
