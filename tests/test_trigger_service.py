# -*- coding: utf-8 -*-
"""Integration tests for TriggerService + TriggerQueue + TriggerStore
(issue #321, Phase 1) — including crash/restart simulations."""

import asyncio
import heapq
import time

from agent_core.core.trigger import Trigger
from agent_core.core.impl.trigger.queue import TriggerQueue

from app.triggers import TriggerService, TriggerSpec, TriggerSource
from app.triggers.store import TriggerStore


def run(coro):
    return asyncio.run(coro)


def make_stack(tmp_path, name="sessions.db"):
    """Real store + real queue (dummy LLM — routing never fires because every
    spec carries a session_id and the routing prompt is empty)."""
    store = TriggerStore(db_path=str(tmp_path / name))
    queue = TriggerQueue(llm=object())
    service = TriggerService(store, queue)
    return store, queue, service


def spec(**overrides):
    kwargs = dict(
        source=TriggerSource.SCHEDULED,
        description="do the thing",
        priority=50,
        session_id="s1",
        payload={"type": "scheduled"},
        skip_merge=True,
    )
    kwargs.update(overrides)
    return TriggerSpec(**kwargs)


class TestEmitNextAck:
    def test_roundtrip_transitions(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            assert not result.deduped
            assert store.get(result.trigger_id)["status"] == "PENDING"

            trig = await asyncio.wait_for(service.next(), timeout=2)
            assert trig.store_ids == [result.trigger_id]
            assert store.get(result.trigger_id)["status"] == "CLAIMED"

            await service.ack(trig)
            assert store.get(result.trigger_id)["status"] == "DONE"

        run(scenario())

    def test_nack_marks_failed(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            trig = await asyncio.wait_for(service.next(), timeout=2)
            await service.nack(trig, "RuntimeError: kaboom")
            row = store.get(result.trigger_id)
            assert row["status"] == "FAILED"
            assert "kaboom" in row["last_error"]

        run(scenario())

    def test_dedup_emit_no_double_enqueue(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            r1 = await service.emit(
                spec(dedup_key="scheduled-once:abc", session_id="a")
            )
            r2 = await service.emit(
                spec(dedup_key="scheduled-once:abc", session_id="b")
            )
            assert not r1.deduped
            assert r2.deduped
            assert r2.trigger_id == r1.trigger_id
            assert await queue.size() == 1

        run(scenario())

    def test_legacy_put_passthrough(self, tmp_path):
        # Producers not yet migrated still work; their triggers carry no
        # store rows and ack is a no-op.
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            await queue.put(
                Trigger(
                    fire_at=time.time(),
                    priority=3,
                    next_action_description="legacy",
                    session_id="legacy-session",
                ),
                skip_merge=True,
            )
            trig = await asyncio.wait_for(service.next(), timeout=2)
            assert trig.store_ids == []
            await service.ack(trig)  # must not raise
            assert store.count_by_status() == {}

        run(scenario())


class TestCrashRecovery:
    def test_crash_while_pending_rehydrates_once(self, tmp_path):
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            result = await service.emit(spec())
            # crash: process dies with the trigger still PENDING in the heap

            store2, queue2, service2 = make_stack(tmp_path)  # restart
            requeued = await service2.rehydrate()
            assert requeued == 1
            assert await queue2.size() == 1

            trig = await asyncio.wait_for(service2.next(), timeout=2)
            assert trig.store_ids == [result.trigger_id]
            await service2.ack(trig)

            # a second restart must not re-deliver settled work
            store3, queue3, service3 = make_stack(tmp_path)
            assert await service3.rehydrate() == 0

        run(scenario())

    def test_crash_mid_react_reclaims_claimed(self, tmp_path):
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            result = await service.emit(spec())
            await asyncio.wait_for(service.next(), timeout=2)
            assert store.get(result.trigger_id)["status"] == "CLAIMED"
            # crash: no ack — row orphaned CLAIMED

            store2, queue2, service2 = make_stack(tmp_path)  # restart
            requeued = await service2.rehydrate()
            assert requeued == 1
            row = store2.get(result.trigger_id)
            assert row["status"] == "CLAIMED" or row["status"] == "PENDING"
            trig = await asyncio.wait_for(service2.next(), timeout=2)
            await service2.ack(trig)
            assert store2.get(result.trigger_id)["status"] == "DONE"
            assert store2.get(result.trigger_id)["attempts"] == 2

        run(scenario())

    def test_boot_resume_emit_hits_rehydrated_dedup(self, tmp_path):
        # Double-boot can't double-resume: the rehydrated resume row blocks
        # the boot-time re-emit via the dedup index.
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            await service.emit(
                spec(
                    source=TriggerSource.RESUME,
                    dedup_key="resume:task42",
                    session_id="task42",
                )
            )
            # crash before consumption

            store2, queue2, service2 = make_stack(tmp_path)
            await service2.rehydrate()
            result = await service2.emit(
                spec(
                    source=TriggerSource.RESUME,
                    dedup_key="resume:task42",
                    session_id="task42",
                )
            )
            assert result.deduped
            assert await queue2.size() == 1

        run(scenario())


class TestEvictionSettlesRows:
    def test_same_session_replacement_supersedes(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            r1 = await service.emit(spec(description="old"))
            r2 = await service.emit(spec(description="new"))
            row = store.get(r1.trigger_id)
            assert row["status"] == "DONE"
            assert row["resolution"] == "superseded"
            assert row["superseded_by"] == r2.trigger_id
            assert await queue.size() == 1

        run(scenario())

    def test_superseded_rows_do_not_rehydrate(self, tmp_path):
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            await service.emit(spec(description="old"))
            r2 = await service.emit(spec(description="new"))
            # crash

            store2, queue2, service2 = make_stack(tmp_path)
            requeued = await service2.rehydrate()
            assert requeued == 1
            trig = await asyncio.wait_for(service2.next(), timeout=2)
            assert trig.store_ids == [r2.trigger_id]

        run(scenario())

    def test_cancel_sessions_settles_and_dequeues(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec(session_id="doomed"))
            await service.cancel_sessions(["doomed"])
            assert store.get(result.trigger_id)["resolution"] == "cancelled"
            assert await queue.size() == 0

        run(scenario())

    def test_queue_clear_cancels_rows(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            await queue.clear()
            assert store.get(result.trigger_id)["resolution"] == "cancelled"

        run(scenario())


class TestMergedTriggerAck:
    def test_merge_unions_store_ids_and_ack_settles_all(self, tmp_path):
        # put() replaces same-session triggers, so two same-session entries
        # can only coexist via internal paths — inject directly to verify the
        # merge/ack contract (a missed id would strand a row in CLAIMED).
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            id1, _ = store.insert(
                source="scheduled", description="a", fire_at=time.time()
            )
            id2, _ = store.insert(
                source="scheduled", description="b", fire_at=time.time()
            )
            for row_id, desc in ((id1, "a"), (id2, "b")):
                heapq.heappush(
                    queue._heap,
                    Trigger(
                        fire_at=time.time() - 1,
                        priority=50,
                        next_action_description=desc,
                        session_id="s1",
                        id=row_id,
                        source="scheduled",
                        store_ids=[row_id],
                    ),
                )

            trig = await asyncio.wait_for(service.next(), timeout=2)
            assert sorted(trig.store_ids) == sorted([id1, id2])
            await service.ack(trig)
            assert store.get(id1)["status"] == "DONE"
            assert store.get(id2)["status"] == "DONE"

        run(scenario())


class TestRehydrateEdges:
    def test_stale_rows_are_settled_not_refired(self, tmp_path):
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            old_id, _ = store.insert(
                source="scheduled",
                description="ancient",
                fire_at=time.time() - 25 * 3600,
            )
            requeued = await service.rehydrate()
            assert requeued == 0
            row = store.get(old_id)
            assert row["status"] == "DONE"
            assert row["resolution"] == "stale"

        run(scenario())

    def test_overdue_rows_get_catch_up_note(self, tmp_path):
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            store.insert(
                source="scheduled",
                description="late task",
                fire_at=time.time() - 600,
                session_id="s1",
            )
            await service.rehydrate()
            trig = await asyncio.wait_for(service.next(), timeout=2)
            assert "NOTE:" in trig.next_action_description
            assert trig.payload.get("is_catch_up") is True

        run(scenario())

    def test_waiting_for_reply_round_trips(self, tmp_path):
        async def scenario():
            store, queue, service = make_stack(tmp_path)
            await service.emit(
                spec(waiting_for_reply=True, fire_at=time.time() + 9999)
            )
            # crash before it fires

            store2, queue2, service2 = make_stack(tmp_path)
            await service2.rehydrate()
            triggers = await queue2.list_triggers()
            assert len(triggers) == 1
            assert triggers[0].waiting_for_reply is True

        run(scenario())


class TestFireMirroring:
    def test_fire_persists_pending_message(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec(fire_at=time.time() + 9999))
            fired = await service.fire("s1", message="hello", platform="Telegram")
            assert fired
            row = store.get(result.trigger_id)
            assert '"pending_user_message": "hello"' in row["payload_json"]
            # in-memory trigger fires now and carries the message
            trig = await asyncio.wait_for(service.next(), timeout=2)
            assert trig.payload["pending_user_message"] == "hello"

        run(scenario())
