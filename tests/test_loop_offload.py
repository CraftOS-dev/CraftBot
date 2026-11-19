# -*- coding: utf-8 -*-
"""Blocking work kept off the shared event loop.

The browser UI, every session and the background jobs share one asyncio
loop; a disk write, pip run or process kill on it froze all of them (the
UI's "busy" banner). These tests pin the work that was moved to worker
threads, and the caches and change checks that removed repeated work.

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
"""

from __future__ import annotations

import asyncio
import os
import threading
from types import SimpleNamespace

from agent_core.core.action_framework import registry
from agent_core.core.impl.action import executor
from agent_core.core.session import Session
from app.usage.action_storage import ActionStorage, StoredActionItem
from app.usage.session_storage import SessionStorage
from craftos_integrations.core.listeners import (
    FileCursorStore,
    ListenerManager,
    _Instance,
)

# ── action requirements ───────────────────────────────────────────────────


def test_requirements_are_checked_once_and_off_the_loop(monkeypatch):
    monkeypatch.setattr(executor, "_SETTLED_REQUIREMENTS", set())
    checked_on = []

    def fake_ensure(requirements, python_bin=None):
        checked_on.append(threading.get_ident())
        executor._SETTLED_REQUIREMENTS.update((python_bin, r) for r in requirements)

    async def fake_internal(*args, **kwargs):
        return {"status": "success"}

    monkeypatch.setattr(executor, "_ensure_requirements", fake_ensure)
    monkeypatch.setattr(executor, "_atomic_action_internal_async", fake_internal)
    action = SimpleNamespace(
        name="fetch",
        code="",
        mode="CLI",
        execution_mode="internal",
        timeout=5,
        requirements=["somepkg"],
    )

    async def main():
        runner = executor.ActionExecutor()
        await runner.execute_atomic_action(action, {})
        await runner.execute_atomic_action(action, {})
        return threading.get_ident()

    loop_thread = asyncio.run(main())
    assert len(checked_on) == 1, "a confirmed requirement is not checked again"
    assert checked_on[0] != loop_thread


def test_installed_distribution_is_confirmed_without_pip(monkeypatch):
    monkeypatch.setattr(executor, "_SETTLED_REQUIREMENTS", set())

    def no_pip(*args, **kwargs):
        raise AssertionError("pip must not run for an installed package")

    monkeypatch.setattr(executor.subprocess, "check_call", no_pip)
    executor._ensure_requirements(["pytest"])
    assert (None, "pytest") in executor._SETTLED_REQUIREMENTS


# ── action source ─────────────────────────────────────────────────────────


def test_action_source_is_parsed_once_per_file_version(tmp_path, monkeypatch):
    source = tmp_path / "an_action.py"
    source.write_text("def handler(x):\n    return 1\n", encoding="utf-8")
    namespace: dict = {}
    exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), namespace)
    handler = namespace["handler"]

    monkeypatch.setattr(registry, "_SOURCE_CACHE", {})
    parses = []
    strip = registry._strip_decorator
    monkeypatch.setattr(
        registry, "_strip_decorator", lambda code: parses.append(1) or strip(code)
    )

    assert "return 1" in registry._handler_source(handler)
    assert "return 1" in registry._handler_source(handler)
    assert len(parses) == 1

    # An edited action file still takes effect without a restart.
    source.write_text("def handler(x):\n    return 2\n", encoding="utf-8")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert "return 2" in registry._handler_source(handler)
    assert len(parses) == 2


# ── listener cursors ──────────────────────────────────────────────────────


def test_cursor_is_written_off_the_loop_and_only_when_it_moves(tmp_path, monkeypatch):
    store = FileCursorStore(root=tmp_path)
    writes = []
    real_set = store.set

    def recording_set(provider_id, identity, cursor):
        writes.append((threading.get_ident(), dict(cursor)))
        real_set(provider_id, identity, cursor)

    monkeypatch.setattr(store, "set", recording_set)
    manager = ListenerManager(system=None, sink=None, cursors=store)
    listener = SimpleNamespace(cursor=lambda: {"last_seen": "a"})
    instance = _Instance(
        provider_id="fakemail", identity="a@x.com", listener=listener, credential={}
    )

    async def main():
        await manager._persist_cursor(instance)
        await manager._persist_cursor(instance)  # unchanged: nothing written
        listener.cursor = lambda: {"last_seen": "b"}
        await manager._persist_cursor(instance)
        return threading.get_ident()

    loop_thread = asyncio.run(main())
    assert [cursor for _, cursor in writes] == [{"last_seen": "a"}, {"last_seen": "b"}]
    assert all(thread != loop_thread for thread, _ in writes)
    assert store.get("fakemail", "a@x.com") == {"last_seen": "b"}


# ── session storage ───────────────────────────────────────────────────────


def test_background_session_writes_keep_call_order_and_snapshot(tmp_path):
    storage = SessionStorage(db_path=str(tmp_path / "sessions.db"))
    session = Session(id="s1", title="first")
    storage.persist_session_later(session)
    session.title = "changed after the call"  # the snapshot is what lands

    storage.persist_session_later(Session(id="gone", title="x"))
    storage.remove_session_later("gone")  # after its persist: stays removed

    storage.persist_session(Session(id="s2"))  # waits for everything queued
    ids = {row["session_id"] for row in storage.get_all_sessions()}
    assert ids == {"s1", "s2"}
    assert storage.get_session("s1")["title"] == "first"


def test_session_writes_run_on_the_writer_thread(tmp_path, monkeypatch):
    storage = SessionStorage(db_path=str(tmp_path / "sessions.db"))
    threads = []
    write = storage._write_session

    def recording_write(row):
        threads.append(threading.current_thread().name)
        write(row)

    monkeypatch.setattr(storage, "_write_session", recording_write)
    storage.persist_session_later(Session(id="s1"))
    storage.persist_session(Session(id="s2"))
    assert len(threads) == 2
    assert all(name.startswith("session-db") for name in threads)


# ── activity feed storage ─────────────────────────────────────────────────


def _item(item_id: str, session_id: str = "s1") -> StoredActionItem:
    return StoredActionItem(
        id=item_id,
        name="web_search",
        status="running",
        item_type="action",
        session_id=session_id,
        created_at=1.0,
        input_data={"query": item_id},
    )


def test_background_feed_writes_keep_call_order(tmp_path):
    storage = ActionStorage(db_path=str(tmp_path / "actions.db"))
    storage.save_item_later(_item("old"))
    storage.clear_items_later("s1")  # after the save: the item stays cleared
    storage.save_item_later(_item("new"))
    storage.save_item(_item("other", session_id="s2"))  # waits for the queue
    kept = {item.id for item in storage.get_recent_items_by_session()}
    assert kept == {"new", "other"}
