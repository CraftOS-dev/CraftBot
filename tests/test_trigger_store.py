# -*- coding: utf-8 -*-
"""Unit tests for the durable trigger store (issue #321, Phase 1)."""

import sqlite3
import time

from app.triggers.store import TriggerStore


def make_store(tmp_path):
    return TriggerStore(db_path=str(tmp_path / "sessions.db"))


def insert_basic(store, **overrides):
    kwargs = dict(
        source="scheduled",
        description="do the thing",
        fire_at=time.time(),
        priority=50,
        session_id="s1",
        payload={"type": "scheduled"},
        dedup_key=None,
    )
    kwargs.update(overrides)
    return store.insert(**kwargs)


class TestInsertAndDedup:
    def test_insert_creates_pending_row(self, tmp_path):
        store = make_store(tmp_path)
        row_id, created = insert_basic(store)
        assert created
        row = store.get(row_id)
        assert row["status"] == "PENDING"
        assert row["source"] == "scheduled"
        assert row["session_id"] == "s1"
        assert row["attempts"] == 0

    def test_active_dedup_key_blocks_duplicate(self, tmp_path):
        store = make_store(tmp_path)
        id1, created1 = insert_basic(store, dedup_key="scheduled-once:abc")
        id2, created2 = insert_basic(store, dedup_key="scheduled-once:abc")
        assert created1
        assert not created2
        assert id2 == id1  # existing active row returned

    def test_claimed_row_still_blocks_duplicate(self, tmp_path):
        store = make_store(tmp_path)
        id1, _ = insert_basic(store, dedup_key="k")
        store.claim([id1])
        id2, created2 = insert_basic(store, dedup_key="k")
        assert not created2
        assert id2 == id1

    def test_settled_row_does_not_block_refire(self, tmp_path):
        # A DONE resume:{task_id} must not block a re-resume after the next
        # restart — that's why dedup is a partial index over active rows.
        store = make_store(tmp_path)
        id1, _ = insert_basic(store, dedup_key="resume:t1")
        store.ack([id1])
        id2, created2 = insert_basic(store, dedup_key="resume:t1")
        assert created2
        assert id2 != id1

    def test_null_dedup_keys_never_collide(self, tmp_path):
        store = make_store(tmp_path)
        _, c1 = insert_basic(store, dedup_key=None)
        _, c2 = insert_basic(store, dedup_key=None)
        assert c1 and c2


class TestLifecycle:
    def test_claim_ack(self, tmp_path):
        store = make_store(tmp_path)
        row_id, _ = insert_basic(store)
        store.claim([row_id])
        row = store.get(row_id)
        assert row["status"] == "CLAIMED"
        assert row["attempts"] == 1
        assert row["lease_until"] is not None

        store.ack([row_id])
        row = store.get(row_id)
        assert row["status"] == "DONE"
        assert row["resolution"] == "completed"
        assert row["lease_until"] is None

    def test_fail_records_error(self, tmp_path):
        store = make_store(tmp_path)
        row_id, _ = insert_basic(store)
        store.claim([row_id])
        store.fail([row_id], error="ValueError: boom")
        row = store.get(row_id)
        assert row["status"] == "FAILED"
        assert row["resolution"] == "failed"
        assert "boom" in row["last_error"]

    def test_supersede_marks_replacement(self, tmp_path):
        store = make_store(tmp_path)
        old_id, _ = insert_basic(store)
        new_id, _ = insert_basic(store)
        store.supersede([old_id], by_id=new_id)
        row = store.get(old_id)
        assert row["status"] == "DONE"
        assert row["resolution"] == "superseded"
        assert row["superseded_by"] == new_id

    def test_cancel_sessions_settles_only_active(self, tmp_path):
        store = make_store(tmp_path)
        a, _ = insert_basic(store, session_id="s1")
        b, _ = insert_basic(store, session_id="s1")
        store.ack([b])  # already settled — must keep resolution "completed"
        c, _ = insert_basic(store, session_id="s2")

        count = store.cancel_sessions(["s1"])
        assert count == 1
        assert store.get(a)["resolution"] == "cancelled"
        assert store.get(b)["resolution"] == "completed"
        assert store.get(c)["status"] == "PENDING"


class TestBootRecovery:
    def test_reclaim_claimed(self, tmp_path):
        store = make_store(tmp_path)
        a, _ = insert_basic(store)
        b, _ = insert_basic(store)
        store.claim([a])
        store.ack([b])

        reclaimed = store.reclaim_claimed()
        assert reclaimed == 1
        assert store.get(a)["status"] == "PENDING"
        assert store.get(a)["attempts"] == 1  # attempt history preserved
        assert store.get(b)["status"] == "DONE"

    def test_load_pending_ordered_and_filtered(self, tmp_path):
        store = make_store(tmp_path)
        late, _ = insert_basic(store, fire_at=2000.0)
        early, _ = insert_basic(store, fire_at=1000.0)
        done, _ = insert_basic(store, fire_at=500.0)
        store.ack([done])

        rows = store.load_pending()
        assert [r["id"] for r in rows] == [early, late]


class TestFireMirroring:
    def test_update_for_fire_patches_active_rows(self, tmp_path):
        store = make_store(tmp_path)
        active, _ = insert_basic(store, session_id="s1", fire_at=9999999999.0)
        settled, _ = insert_basic(store, session_id="s1")
        store.ack([settled])

        updated = store.update_for_fire(
            "s1", 123.0, {"pending_user_message": "hi"}
        )
        assert updated == 1
        row = store.get(active)
        assert row["fire_at"] == 123.0
        assert '"pending_user_message": "hi"' in row["payload_json"]


class TestSchemaAndReset:
    def test_clear_all(self, tmp_path):
        store = make_store(tmp_path)
        insert_basic(store)
        insert_basic(store)
        store.clear_all()
        assert store.count_by_status() == {}

    def test_legacy_table_without_dedup_key_is_replaced(self, tmp_path):
        db_path = str(tmp_path / "sessions.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE triggers (id TEXT PRIMARY KEY, blob TEXT)")
            conn.execute("INSERT INTO triggers VALUES ('x', 'y')")
            conn.commit()

        store = TriggerStore(db_path=db_path)
        row_id, created = insert_basic(store)
        assert created
        assert store.get(row_id)["status"] == "PENDING"

    def test_reopen_preserves_rows(self, tmp_path):
        db_path = str(tmp_path / "sessions.db")
        store = TriggerStore(db_path=db_path)
        row_id, _ = insert_basic(store)

        store2 = TriggerStore(db_path=db_path)  # simulated restart
        assert store2.get(row_id)["status"] == "PENDING"
