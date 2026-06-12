# -*- coding: utf-8 -*-
"""Phase 5 tests: retry with backoff, dead-letter surfacing, and GC for the
trigger store + activity ledger."""

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from agent_core.core.impl.trigger.queue import TriggerQueue

from app.triggers import TriggerService, TriggerSpec, TriggerSource
from app.triggers.activity_log import ActivityLog, ActivityLogGuard
from app.triggers.service import BACKOFF_BASE_SECONDS, MAX_ATTEMPTS
from app.triggers.store import TriggerStore


def run(coro):
    return asyncio.run(coro)


def make_stack(tmp_path):
    store = TriggerStore(db_path=str(tmp_path / "sessions.db"))
    queue = TriggerQueue()
    service = TriggerService(store, queue)
    return store, queue, service


def spec(**overrides):
    kwargs = dict(
        source=TriggerSource.SCHEDULED,
        description="do the thing",
        priority=50,
        session_id="s1",
    )
    kwargs.update(overrides)
    return TriggerSpec(**kwargs)


def age_row(db_path, row_id, hours, table="triggers", key_col="id"):
    """Backdate a row's updated_at so GC sees it as old."""
    old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE {table} SET updated_at = ? WHERE {key_col} = ?", (old, row_id)
        )
        conn.commit()


class TestRetryWithBackoff:
    def test_nack_requeues_with_backoff(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            trig = await asyncio.wait_for(service.next(), timeout=2)
            before = time.time()
            await service.nack(trig, "boom")

            row = store.get(result.trigger_id)
            assert row["status"] == "PENDING"
            assert row["not_before"] >= before + BACKOFF_BASE_SECONDS - 1
            assert "boom" in row["last_error"]
            # re-enqueued with the backoff as its fire time
            triggers = await queue.list_triggers()
            assert len(triggers) == 1
            assert triggers[0].fire_at >= before + BACKOFF_BASE_SECONDS - 1

        run(scenario())

    def test_backoff_grows_per_attempt(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            result = await service.emit(spec())
            delays = []
            for _ in range(3):
                # force the queued retry due now so next() returns it
                with sqlite3.connect(store._db_path) as conn:
                    conn.execute(
                        "UPDATE triggers SET fire_at = ?, not_before = NULL "
                        "WHERE id = ?",
                        (time.time() - 1, result.trigger_id),
                    )
                    conn.commit()
                await queue.fire("s1")
                trig = await asyncio.wait_for(service.next(), timeout=2)
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
        store, queue, service = make_stack(tmp_path)
        dead = []
        service.set_dead_letter_handler(lambda trig, err: dead.append((trig, err)))

        async def scenario():
            result = await service.emit(spec())
            for attempt in range(MAX_ATTEMPTS + 1):
                with sqlite3.connect(store._db_path) as conn:
                    conn.execute(
                        "UPDATE triggers SET fire_at = ? WHERE id = ?",
                        (time.time() - 1, result.trigger_id),
                    )
                    conn.commit()
                await queue.fire("s1")
                trig = await asyncio.wait_for(service.next(), timeout=2)
                await service.nack(trig, f"boom {attempt}")
                row = store.get(result.trigger_id)
                if row["status"] == "DEAD":
                    break

            row = store.get(result.trigger_id)
            assert row["status"] == "DEAD"
            assert row["attempts"] == MAX_ATTEMPTS
            assert len(dead) == 1
            assert dead[0][0].id == result.trigger_id
            # dead rows do not rehydrate
            store2, queue2, service2 = make_stack(tmp_path)
            assert await service2.rehydrate() == 0

        run(scenario())


class TestTriggerStoreGC:
    def test_old_settled_rows_removed_active_kept(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            done = await service.emit(spec(session_id="a"))
            trig = await asyncio.wait_for(service.next(), timeout=2)
            await service.ack(trig)
            pending = await service.emit(spec(session_id="b"))

            age_row(store._db_path, done.trigger_id, hours=8 * 24)
            age_row(store._db_path, pending.trigger_id, hours=8 * 24)

            removed = store.gc(ttl_hours=7 * 24)
            assert removed == 1
            assert store.get(done.trigger_id) is None
            assert store.get(pending.trigger_id) is not None  # active never GC'd

        run(scenario())

    def test_recent_settled_rows_survive(self, tmp_path):
        store, queue, service = make_stack(tmp_path)

        async def scenario():
            done = await service.emit(spec())
            trig = await asyncio.wait_for(service.next(), timeout=2)
            await service.ack(trig)
            assert store.gc(ttl_hours=7 * 24) == 0
            assert store.get(done.trigger_id) is not None

        run(scenario())


class TestActivityLogGC:
    def test_stale_intent_downgraded_and_old_rows_removed(self, tmp_path):
        db = str(tmp_path / "sessions.db")
        log = ActivityLog(db_path=db)
        guard = ActivityLogGuard(log)

        d_old_intent = guard.begin("send_gmail", {"to": "a@x.com"}, "t1")
        d_old_done = guard.begin("send_gmail", {"to": "b@x.com"}, "t1")
        guard.complete(d_old_done.idem_key, "success", {"status": "success"})
        d_fresh = guard.begin("send_gmail", {"to": "c@x.com"}, "t1")

        age_row(db, d_old_intent.idem_key, 8 * 24, "activity_log", "idem_key")
        age_row(db, d_old_done.idem_key, 31 * 24, "activity_log", "idem_key")

        log.gc(intent_ttl_hours=7 * 24, done_ttl_hours=30 * 24)

        # week-old INTENT no longer blocks: downgraded to FAILED → retake allowed
        assert log.get(d_old_intent.idem_key)["status"] == "FAILED"
        retry = guard.begin("send_gmail", {"to": "a@x.com"}, "t1")
        assert retry.proceed
        # month-old DONE removed; fresh INTENT untouched
        assert log.get(d_old_done.idem_key) is None
        assert log.get(d_fresh.idem_key)["status"] == "INTENT"
