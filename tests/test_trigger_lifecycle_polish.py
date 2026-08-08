# -*- coding: utf-8 -*-
"""Lifecycle-polish tests: garbage collection for the trigger store and
the activity ledger. (Retry/backoff/dead-letter live in
test_trigger_service.py.)"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

from app.triggers import TriggerService, TriggerSpec, TriggerSource
from app.triggers.activity_log import ActivityLog, ActivityLogGuard
from app.triggers.store import TriggerStore


def run(coro):
    return asyncio.run(coro)


class FakeRuntime:
    def __init__(self):
        self.dispatched = []

    def bind_service(self, service):
        pass

    async def dispatch(self, trig):
        self.dispatched.append(trig)

    async def remove_session(self, session_id):
        pass


def make_stack(tmp_path):
    store = TriggerStore(db_path=str(tmp_path / "sessions.db"))
    runtime = FakeRuntime()
    service = TriggerService(store, runtime)
    return store, runtime, service


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


class TestTriggerStoreGC:
    def test_old_settled_rows_removed_active_kept(self, tmp_path):
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            done = await service.emit(spec(session_id="a"))
            trig = runtime.dispatched[0]
            service.claim(trig)
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
        store, runtime, service = make_stack(tmp_path)

        async def scenario():
            done = await service.emit(spec())
            trig = runtime.dispatched[0]
            service.claim(trig)
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
