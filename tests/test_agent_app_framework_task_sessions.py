"""App request turns share the app chat without sharing task authority."""

import asyncio
import time
from copy import deepcopy
from unittest.mock import AsyncMock

from app.agent_app.framework_commands import task_authority
from app.triggers.runtime import SessionRuntimeManager
from app.triggers.service import TriggerService, TriggerSpec
from app.triggers.store import TriggerStore
from tests.test_agent_app_framework_bridge import prepared
from tests import test_agent_app_framework_host as host_tests

fixture = host_tests.fixture


def test_requests_wait_for_busy_chat_and_keep_the_same_session(fixture, tmp_path):
    async def check():
        host, task, body = await prepared(fixture, owner=True)
        sid = host.store.all("attachment")[0]["sessionId"]
        tasks = {"task1": deepcopy(task)}
        original = host.bridge.http_json.side_effect

        async def request(target, route, token, method="GET", body=None):
            if route.startswith("/api/_a2app/tasks/"):
                return deepcopy(tasks[route.split("/")[4]])
            return await original(target, route, token, method, body)

        host.bridge.http_json.side_effect = request
        started, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        seen = []

        async def react(trigger):
            assert trigger.session_id == sid
            authority = task_authority.get()
            if trigger.source == "user_message":
                assert authority is None
                if not started.is_set():
                    started.set()
                    await release.wait()
                seen.append("chat")
                await host.bridge.ended(sid)  # Must not settle queued requests.
            else:
                seen.append(authority.task_id)
                assert "aggregated_triggers" not in trigger.payload
                authority.outcome = "completed"
                authority.active = False
                await host.bridge.ended(sid)
            if len(seen) == 4:
                done.set()

        runtime = SessionRuntimeManager(react)
        service = TriggerService(TriggerStore(db_path=str(tmp_path / "triggers.db")), runtime)
        host.agent.trigger_service = service
        await runtime.start()
        try:
            await service.emit(TriggerSpec(source="user_message", description="Existing chat", session_id=sid))
            await asyncio.wait_for(started.wait(), 2)
            first = await host.bridge.accept(body)
            body2 = deepcopy(body)
            body2["task"]["id"] = "task2"
            tasks["task2"] = deepcopy(body2["task"])
            second = await host.bridge.accept(body2)
            await service.emit(TriggerSpec(source="user_message", description="Follow-up chat", session_id=sid))
            assert first["sessionId"] == second["sessionId"] == sid
            assert len(host.agent.session_manager.sessions) == 1
            assert seen == []  # Requests cannot run concurrently with the chat.
            release.set()
            await asyncio.wait_for(done.wait(), 4)
            assert seen == ["chat", "task1", "task2", "chat"]
            assert all(r["status"] == "completed" for r in host.store.all("delivery"))
        finally:
            release.set()
            await runtime.stop()
            await host.close()
    asyncio.run(check())


def test_task_cancellation_preserves_other_work_in_same_chat(tmp_path, monkeypatch):
    from app.agent_app import framework_host

    monkeypatch.setattr(framework_host, "_host", None)

    async def check():
        started = asyncio.Event()
        async def react(_):
            started.set()
            await asyncio.Event().wait()
        runtime = SessionRuntimeManager(react)
        runtime.set_stop_finalizer(AsyncMock())
        store = TriggerStore(db_path=str(tmp_path / "triggers.db"))
        service = TriggerService(store, runtime)
        await runtime.start()
        try:
            await service.emit(TriggerSpec(source="framework_task", description="Active request", session_id="app", payload={"framework_task_key": "a"}))
            await asyncio.wait_for(started.wait(), 2)
            rows = []
            for key in ("a", "b", None):
                rows.append(await service.emit(TriggerSpec(
                    source="run_continuation", description="Continue", session_id="app",
                    fire_at=time.time() + 60,
                    payload={"framework_task_key": key} if key else {},
                )))
            assert not await runtime.request_stop("app", framework_task_key="b")
            assert await runtime.request_stop("app", framework_task_key="a")
            assert store.get(rows[0].trigger_id)["status"] == "DONE"
            assert [store.get(row.trigger_id)["status"] for row in rows[1:]] == ["PENDING", "PENDING"]
        finally:
            await runtime.stop()
    asyncio.run(check())


def test_continuation_cannot_merge_with_another_request_or_normal_chat():
    from app.triggers.runtime import _compatible_message_origins
    from agent_core.core.trigger import Trigger

    def trigger(key):
        return Trigger(time.time(), 50, "Continue", source="run_continuation",
                       payload={"framework_task_key": key} if key else {})
    assert _compatible_message_origins(trigger("a"), trigger("a"))
    assert not _compatible_message_origins(trigger("a"), trigger("b"))
    assert not _compatible_message_origins(trigger("a"), trigger(None))
    assert not _compatible_message_origins(trigger(None), trigger("a"))
