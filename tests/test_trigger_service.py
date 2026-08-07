# -*- coding: utf-8 -*-
"""Tests for TriggerService (durable front door) against a fake runtime —
emit/dedup, claim/ack/nack, crash-restart rehydration, and session cleanup."""

import asyncio
import time

from agent_core.core.session import MAIN_SESSION_ID
from agent_core.core.trigger import Trigger

from app.triggers import TriggerService, TriggerSpec, TriggerSource
from app.triggers.store import TriggerStore


def run(coro):
    return asyncio.run(coro)


class FakeRuntime:
    """Stands in for SessionRuntimeManager: collects dispatched triggers."""

    def __init__(self):
        self.dispatched = []
        self.removed_sessions = []
        self.service = None

    def bind_service(self, service):
        self.service = service

    async def dispatch(self, trig: Trigger) -> None:
        self.dispatched.append(trig)

    async def remove_session(self, session_id: str) -> None:
        self.removed_sessions.append(session_id)


def make_stack(tmp_path, name="sessions.db"):
    store = TriggerStore(db_path=str(tmp_path / name))
    runtime = FakeRuntime()
    service = TriggerService(store, runtime)
    return store, runtime, service


def spec(**overrides):
    kwargs = dict(
        source=TriggerSource.SCHEDULED,
        description="do the thing",
        priority=50,
        session_id="s1",
        payload={"type": "scheduled"},
    )
    kwargs.update(overrides)
    return TriggerSpec(**kwargs)


class TestEmit:
    def test_emit_persists_then_dispatches(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            assert not result.deduped
            row = store.get(result.trigger_id)
            assert row["status"] == "PENDING"
            assert row["session_id"] == "s1"
            assert len(runtime.dispatched) == 1
            trig = runtime.dispatched[0]
            assert trig.id == result.trigger_id
            assert trig.session_id == "s1"
            assert trig.source == TriggerSource.SCHEDULED.value

        run(scenario())

    def test_emit_defaults_to_main_session(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec(session_id=None))
            assert store.get(result.trigger_id)["session_id"] == MAIN_SESSION_ID
            assert runtime.dispatched[0].session_id == MAIN_SESSION_ID

        run(scenario())

    def test_dedup_key_blocks_double_dispatch(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            r1 = await service.emit(spec(dedup_key="scheduled-once:abc"))
            r2 = await service.emit(spec(dedup_key="scheduled-once:abc"))
            assert not r1.deduped
            assert r2.deduped
            assert r2.trigger_id == r1.trigger_id
            # second emit never reached the runtime
            assert len(runtime.dispatched) == 1

        run(scenario())

    def test_settled_row_does_not_block_refire(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            r1 = await service.emit(spec(dedup_key="k"))
            trig = runtime.dispatched[0]
            service.claim(trig)
            await service.ack(trig)
            r2 = await service.emit(spec(dedup_key="k"))
            assert not r2.deduped
            assert r2.trigger_id != r1.trigger_id
            assert len(runtime.dispatched) == 2

        run(scenario())


class TestClaimAckNack:
    def test_claim_ack_transitions(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            trig = runtime.dispatched[0]
            service.claim(trig)
            assert store.get(result.trigger_id)["status"] == "CLAIMED"
            await service.ack(trig)
            assert store.get(result.trigger_id)["status"] == "DONE"

        run(scenario())

    def test_nack_retries_with_backoff_and_redispatches(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            trig = runtime.dispatched[0]
            service.claim(trig)
            before = time.time()
            await service.nack(trig, "RuntimeError: kaboom")

            row = store.get(result.trigger_id)
            assert row["status"] == "PENDING"
            assert row["not_before"] > before
            assert "kaboom" in row["last_error"]
            # re-dispatched with the backoff floor as its fire time
            assert len(runtime.dispatched) == 2
            assert runtime.dispatched[1].id == result.trigger_id
            assert runtime.dispatched[1].fire_at >= before

        run(scenario())

    def test_backoff_grows_per_attempt(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            delays = []
            for _ in range(3):
                trig = runtime.dispatched[-1]
                service.claim(trig)
                before = time.time()
                await service.nack(trig, "boom")
                row = store.get(result.trigger_id)
                if row["status"] != "PENDING":
                    break
                delays.append(row["not_before"] - before)
            assert len(delays) >= 2
            assert delays[1] > delays[0]  # exponential growth

        run(scenario())

    def test_dead_letter_after_max_attempts(self, tmp_path):
        from app.triggers.service import MAX_ATTEMPTS

        store, runtime, service = make_stack(tmp_path)
        dead = []
        service.set_dead_letter_handler(lambda trig, err: dead.append((trig, err)))

        async def scenario():
            result = await service.emit(spec())
            for attempt in range(MAX_ATTEMPTS + 1):
                trig = runtime.dispatched[-1]
                service.claim(trig)
                await service.nack(trig, f"boom {attempt}")
                if store.get(result.trigger_id)["status"] == "DEAD":
                    break

            row = store.get(result.trigger_id)
            assert row["status"] == "DEAD"
            assert row["attempts"] == MAX_ATTEMPTS
            assert len(dead) == 1
            assert dead[0][0].id == result.trigger_id

            # dead rows do not rehydrate
            store2, runtime2, service2 = make_stack(tmp_path)
            assert await service2.rehydrate() == 0
            assert runtime2.dispatched == []

        run(scenario())

    def test_ack_without_row_id_is_noop(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            trig = Trigger(
                fire_at=time.time(),
                priority=3,
                next_action_description="legacy",
                session_id="legacy-session",
            )
            service.claim(trig)  # must not raise
            await service.ack(trig)  # must not raise
            assert store.count_by_status() == {}

        run(scenario())


class TestCrashRecovery:
    def test_crash_while_pending_rehydrates_once(self, tmp_path):
        async def scenario():
            store, runtime, service = make_stack(tmp_path)
            result = await service.emit(spec())
            # crash: process dies with the trigger still PENDING

            store2, runtime2, service2 = make_stack(tmp_path)  # restart
            requeued = await service2.rehydrate()
            assert requeued == 1
            assert len(runtime2.dispatched) == 1
            trig = runtime2.dispatched[0]
            assert trig.id == result.trigger_id

            service2.claim(trig)
            await service2.ack(trig)

            # a second restart must not re-deliver settled work
            store3, runtime3, service3 = make_stack(tmp_path)
            assert await service3.rehydrate() == 0
            assert runtime3.dispatched == []

        run(scenario())

    def test_crash_mid_react_reclaims_claimed(self, tmp_path):
        async def scenario():
            store, runtime, service = make_stack(tmp_path)
            result = await service.emit(spec())
            service.claim(runtime.dispatched[0])
            assert store.get(result.trigger_id)["status"] == "CLAIMED"
            # crash: no ack — row orphaned CLAIMED

            store2, runtime2, service2 = make_stack(tmp_path)  # restart
            requeued = await service2.rehydrate()
            assert requeued == 1
            trig = runtime2.dispatched[0]
            assert trig.id == result.trigger_id
            service2.claim(trig)
            await service2.ack(trig)
            assert store2.get(result.trigger_id)["status"] == "DONE"
            assert store2.get(result.trigger_id)["attempts"] == 2

        run(scenario())

    def test_boot_reemit_hits_rehydrated_dedup(self, tmp_path):
        # Double-boot can't double-fire: the rehydrated row blocks the
        # boot-time re-emit via the dedup index.
        async def scenario():
            store, runtime, service = make_stack(tmp_path)
            await service.emit(spec(dedup_key="scheduled-once:42"))
            # crash before consumption

            store2, runtime2, service2 = make_stack(tmp_path)
            await service2.rehydrate()
            result = await service2.emit(spec(dedup_key="scheduled-once:42"))
            assert result.deduped
            assert len(runtime2.dispatched) == 1

        run(scenario())

    def test_stale_rows_are_settled_not_refired(self, tmp_path):
        async def scenario():
            store, runtime, service = make_stack(tmp_path)
            old_id, _ = store.insert(
                source="scheduled",
                description="ancient",
                fire_at=time.time() - 25 * 3600,
            )
            requeued = await service.rehydrate()
            assert requeued == 0
            assert runtime.dispatched == []
            row = store.get(old_id)
            assert row["status"] == "DONE"
            assert row["resolution"] == "stale"

        run(scenario())

    def test_overdue_rows_get_catch_up_note(self, tmp_path):
        async def scenario():
            store, runtime, service = make_stack(tmp_path)
            store.insert(
                source="scheduled",
                description="late task",
                fire_at=time.time() - 600,
                session_id="s1",
            )
            await service.rehydrate()
            trig = runtime.dispatched[0]
            assert "NOTE:" in trig.next_action_description
            assert trig.payload.get("is_catch_up") is True

        run(scenario())

    def test_rehydrated_orphan_session_delivers_to_main(self, tmp_path):
        async def scenario():
            store, runtime, service = make_stack(tmp_path)
            store.insert(
                source="scheduled",
                description="orphan",
                fire_at=time.time(),
                session_id=None,
            )
            await service.rehydrate()
            assert runtime.dispatched[0].session_id == MAIN_SESSION_ID

        run(scenario())


class TestSessionCleanup:
    def test_cancel_sessions_settles_rows_and_removes_lane(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec(session_id="doomed"))
            await service.cancel_sessions(["doomed"])
            row = store.get(result.trigger_id)
            assert row["resolution"] == "cancelled"
            assert runtime.removed_sessions == ["doomed"]
            # cancelled rows never rehydrate
            store2, runtime2, service2 = make_stack(tmp_path)
            assert await service2.rehydrate() == 0

        run(scenario())

    def test_on_evicted_supersedes_or_cancels(self, tmp_path):
        # The lifecycle-listener path: a queue discarding triggers unconsumed
        # settles their rows (supersede when replaced, cancel otherwise).
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            r1 = await service.emit(spec(description="old"))
            r2 = await service.emit(spec(description="new"))
            old_trig, new_trig = runtime.dispatched

            service.on_evicted([old_trig], new_trig)
            row = store.get(r1.trigger_id)
            assert row["status"] == "DONE"
            assert row["resolution"] == "superseded"
            assert row["superseded_by"] == r2.trigger_id

            service.on_evicted([new_trig], None)
            assert store.get(r2.trigger_id)["resolution"] == "cancelled"

        run(scenario())

    def test_clear_all_wipes_store(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            await service.emit(spec())
            service.clear_all()
            assert store.count_by_status() == {}

        run(scenario())
