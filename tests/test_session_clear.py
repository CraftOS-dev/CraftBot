# -*- coding: utf-8 -*-
"""/clear starts a session over as a new session.

It used to clear only the conversation on screen plus the event stream and
todos: the session kept its loaded skills, token totals, title, NOTE.md and
EVENT.md (both named in every prompt), the LLM interface kept its history
(the cleanup called a method that does not exist), and a run in flight
carried on. These tests pin what a clear resets and what it must not touch:
other sessions' streams and caches shared between sessions.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agent_core.core.impl.event_stream.manager import EventStreamManager
from agent_core.core.impl.llm import LLMCallType
from agent_core.core.impl.llm.interface import LLMInterface, RequestUsage
from agent_core.core.impl.session.manager import SessionManager
from agent_core.core.session import MAIN_SESSION_ID, Session, SessionType
from agent_core.core.state.session import StateSession
from app.models.factory import ModelFactory

ACTION = LLMCallType.ACTION_SELECTION


def _llm(provider="grok", model="grok-4.3"):
    ctx = {
        "provider": provider,
        "model": model,
        "client": object(),
        "gemini_client": None,
        "remote_url": None,
        "byteplus": None,
        "anthropic_client": None,
        "bedrock_client": None,
        "initialized": True,
        "auth_mode": "api_key",
    }
    with patch.object(ModelFactory, "create", return_value=ctx):
        return LLMInterface(provider=provider, model=model, api_key="k", base_url="")


def _manager(tmp_path, llm=None, own_streams=True):
    streams = EventStreamManager(llm=None)
    manager = SessionManager(
        event_stream_manager=streams,
        llm_interface=llm,
        context_engine=SimpleNamespace(
            make_decision_system_prompt=lambda session_id=None: "SYSTEM"
        ),
        workspace_root=tmp_path,
        on_stream_create=(
            (lambda sid, wd: streams.create_stream(sid, wd)) if own_streams else None
        ),
    )
    return manager, streams


def _talked(manager, streams, llm, session):
    """A session mid-conversation: events, todos, a skill, LLM history."""
    stream = streams.get_stream_by_id(session.id)
    stream.log("action_end", "old work " + "x " * 50)
    stream.head_summary = "SUMMARY OF OLD WORK"
    manager.update_todos(session.id, [{"content": "Collect: old", "status": "pending"}])
    session.selected_skills = ["old-skill"]
    session.total_input_tokens = 5000
    session.title = "Weather in Fukuoka"
    if llm is not None:
        key = f"{session.id}:{ACTION}"
        llm._session_histories[key] = [{"role": "user", "content": "old"}]
        llm._last_input_tokens[key] = 5000
        llm._last_requests[key] = RequestUsage(
            5000, 4000, time.time(), "grok", "grok-4.3"
        )


def test_a_cleared_session_starts_over_as_a_new_one(tmp_path):
    llm = _llm()
    manager, streams = _manager(tmp_path, llm)
    session = manager.create_session()
    _talked(manager, streams, llm, session)
    properties_before = StateSession.get(session.id).agent_properties
    try:
        assert manager.clear_session(session.id)

        stream = streams.get_stream_by_id(session.id)
        assert stream.tail_events == [] and stream.head_summary is None
        assert session.todos == [] and session.selected_skills == []
        assert session.total_input_tokens == 0
        assert session.title == "New chat"  # titled again from its next request
        assert StateSession.get(session.id).agent_properties is not properties_before
        # The LLM forgot the conversation but still serves it on the session path.
        key = f"{session.id}:{ACTION}"
        assert key not in llm._session_histories
        assert llm.last_input_tokens(session.id, ACTION) is None
        assert llm.last_request(session.id, ACTION) is None
        assert llm.has_session_cache(session.id, ACTION)
    finally:
        StateSession.end(session.id)


def test_a_clear_keeps_the_sessions_identity(tmp_path):
    manager, streams = _manager(tmp_path)
    session = manager.restore_session(
        Session.from_dict(
            {
                "id": "lui_app",
                "type": SessionType.AGENT_APP,
                "title": "Command Center",
                "agent_app_project_id": "9a07529e",
                "reasoning_effort": "high",
            }
        )
    )
    streams.create_stream(session.id, Path(session.workspace_dir))
    try:
        manager.clear_session(session.id)
        assert session.title == "Command Center"  # only chats are retitled
        assert session.agent_app_project_id == "9a07529e"
        assert session.reasoning_effort == "high"
    finally:
        StateSession.end(session.id)


def test_a_clear_never_touches_another_sessions_stream(tmp_path):
    # get_stream_by_id falls back to the main stream for a session with none.
    manager, streams = _manager(tmp_path, own_streams=False)
    streams.get_main_stream().log("action_end", "main's own work")
    session = manager.create_session()
    try:
        manager.clear_session(session.id)
        assert streams.get_main_stream().tail_events
    finally:
        StateSession.end(session.id)


def test_a_clear_keeps_caches_other_sessions_share(tmp_path):
    # Gemini's explicit cache is keyed by system prompt, shared by every
    # session: deleting it would cost all of them their cached prefix.
    llm = _llm()
    deleted = []
    llm._gemini_cache_manager = SimpleNamespace(
        invalidate_cache=lambda *a: deleted.append(a)
    )
    llm.provider = "gemini"
    llm.create_session_cache("s1", ACTION, "SYSTEM")
    llm.restart_session("s1")
    assert deleted == []


# ─────────────────────────── workspace files ───────────────────────────


def test_a_clear_resets_the_files_named_in_every_prompt(tmp_path):
    from app.session.session_manager import _NOTE_SCRATCHPAD_HEADER
    from app.session.session_manager import SessionManager as AppSessionManager

    streams = EventStreamManager(llm=None)
    manager = AppSessionManager(event_stream_manager=streams)
    manager.workspace_root = tmp_path  # never the real agent workspace
    manager._on_session_persist = None  # never the real session storage
    session = manager.create_session()
    workspace = Path(session.workspace_dir)
    try:
        (workspace / "NOTE.md").write_text("old plan", encoding="utf-8")
        (workspace / "EVENT.md").write_text("old events", encoding="utf-8")
        (workspace / "EVENT_UNPROCESSED.md").write_text("for memory", encoding="utf-8")
        (workspace / "report.pdf").write_bytes(b"user file")

        assert manager.clear_session(session.id)

        assert (workspace / "NOTE.md").read_text(
            encoding="utf-8"
        ) == _NOTE_SCRATCHPAD_HEADER
        assert (workspace / "EVENT.md").read_text(encoding="utf-8") == ""
        # Long-term memory still learns from the cleared conversation.
        assert (workspace / "EVENT_UNPROCESSED.md").read_text(
            encoding="utf-8"
        ) == "for memory"
        assert (workspace / "report.pdf").read_bytes() == b"user file"
    finally:
        StateSession.end(session.id)


# ─────────────────────────── the agent entry ───────────────────────────


def test_a_run_in_flight_is_stopped_before_the_clear_and_the_reset_is_saved():
    from app.agent_base import AgentBase

    calls = []

    async def request_run_stop(session_id):
        calls.append(("stop", session_id))
        return True

    agent = SimpleNamespace(
        busy_sessions={"s1"},
        request_run_stop=request_run_stop,
        session_manager=SimpleNamespace(
            clear_session=lambda session_id: calls.append(("clear", session_id)) or True
        ),
        # The saved LLM state goes too, or a restart would bring it back.
        _persist_llm_session=lambda session_id: calls.append(("save", session_id)),
    )
    assert asyncio.run(AgentBase.clear_session(agent, "s1"))
    assert calls == [("stop", "s1"), ("clear", "s1"), ("save", "s1")]

    calls.clear()
    agent.busy_sessions = set()
    asyncio.run(AgentBase.clear_session(agent, "s1"))
    assert calls == [("stop", "s1"), ("clear", "s1"), ("save", "s1")]


def test_the_main_session_keeps_its_title(tmp_path):
    manager, _ = _manager(tmp_path)
    main = manager.ensure_main()
    try:
        manager.clear_session(MAIN_SESSION_ID)
        assert main.title == "Main"
    finally:
        StateSession.end(MAIN_SESSION_ID)


@pytest.mark.parametrize("active", [False, True])
def test_clear_settles_runtime_work_even_without_a_busy_marker(tmp_path, active):
    from app.agent_base import AgentBase
    from app.triggers import TriggerService, TriggerSource, TriggerSpec
    from app.triggers.runtime import SessionRuntimeManager
    from app.triggers.store import TriggerStore

    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def react(trigger):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        runtime = SessionRuntimeManager(react)
        store = TriggerStore(db_path=str(tmp_path / "clear-triggers.db"))
        service = TriggerService(store, runtime)
        agent = SimpleNamespace(
            busy_sessions=set(), session_runtime=runtime,
            _emit_run_state=Mock(), _notify_mini_browser=Mock(),
            session_manager=SimpleNamespace(clear_session=Mock(return_value=True)),
            _persist_llm_session=Mock(),
        )
        agent.request_run_stop = MethodType(AgentBase.request_run_stop, agent)
        runtime.set_stop_finalizer(AsyncMock())
        await runtime.start()
        try:
            async def emit(sid, source, future=True):
                return await service.emit(TriggerSpec(session_id=sid, source=source,
                    description="Synthetic clear regression", fire_at=time.time() + 60 if future else None))
            if active:
                await emit("target", TriggerSource.USER_MESSAGE, future=False)
                await asyncio.wait_for(started.wait(), 2)
            continuation = await emit("target", TriggerSource.RUN_CONTINUATION)
            other = await emit("other", TriggerSource.RUN_CONTINUATION)
            scheduled = await emit("target", TriggerSource.SCHEDULED)
            assert await AgentBase.clear_session(agent, "target")
            row = store.get(continuation.trigger_id)
            assert (row["status"], row["resolution"]) == ("DONE", "cancelled")
            assert cancelled.is_set() == active
            assert store.get(other.trigger_id)["status"] == "PENDING"
            assert store.get(scheduled.trigger_id)["status"] == "PENDING"
            agent.session_manager.clear_session.assert_called_once_with("target")
            agent._persist_llm_session.assert_called_once_with("target")
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_clear_cancels_a_claimed_turn_waiting_for_capacity(tmp_path):
    from app.agent_base import AgentBase
    from app.triggers import TriggerService, TriggerSource, TriggerSpec
    from app.triggers.runtime import SessionRuntimeManager
    from app.triggers.store import TriggerStore

    async def scenario():
        running = asyncio.Event()
        claimed = asyncio.Event()
        release = asyncio.Event()
        executed = []

        async def react(trigger):
            executed.append(trigger.session_id)
            if trigger.session_id == "other":
                running.set()
                await release.wait()

        runtime = SessionRuntimeManager(react, max_concurrent_turns=1)
        store = TriggerStore(db_path=str(tmp_path / "waiting.db"))
        service = TriggerService(store, runtime)
        original_claim = service.claim

        def claim(trigger):
            original_claim(trigger)
            if trigger.session_id == "target":
                claimed.set()

        service.claim = claim
        finalized = AsyncMock()
        runtime.set_stop_finalizer(finalized)
        agent = SimpleNamespace(
            session_runtime=runtime, _emit_run_state=Mock(),
            _notify_mini_browser=Mock(),
            session_manager=SimpleNamespace(clear_session=Mock(return_value=True)),
            _persist_llm_session=Mock(),
        )
        agent.request_run_stop = MethodType(AgentBase.request_run_stop, agent)
        await runtime.start()
        try:
            async def emit(sid):
                return await service.emit(TriggerSpec(
                    session_id=sid, source=TriggerSource.USER_MESSAGE,
                    description="Capacity regression",
                ))

            other = await emit("other")
            await asyncio.wait_for(running.wait(), 2)
            target = await emit("target")
            await asyncio.wait_for(claimed.wait(), 2)
            assert await AgentBase.clear_session(agent, "target")
            assert store.get(target.trigger_id)["status"] == "DONE"
            assert store.get(other.trigger_id)["status"] == "CLAIMED"
            finalized.assert_awaited_once_with("target")
            assert executed == ["other"]
            release.set()
            # A fresh request in the cleared chat must still execute.
            fresh = await emit("target")
            for _ in range(100):
                if store.get(fresh.trigger_id)["status"] == "DONE":
                    break
                await asyncio.sleep(.01)
            assert store.get(fresh.trigger_id)["status"] == "DONE"
            assert executed == ["other", "target"]
        finally:
            release.set()
            await runtime.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("unwind", ["cancel", "return", "raise"])
@pytest.mark.parametrize("cancel_requester", [False, True])
def test_concurrent_stops_join_settlement_before_resetting_context(tmp_path, monkeypatch, unwind, cancel_requester):
    from app.agent_base import AgentBase
    from app.triggers import TriggerService, TriggerSource, TriggerSpec
    from app.triggers.runtime import SessionRuntimeManager
    from app.triggers.store import TriggerStore

    async def scenario():
        import threading

        running = asyncio.Event()
        cancelled = asyncio.Event()
        release_turn = asyncio.Event()
        kill_started = asyncio.Event()
        release_kill = threading.Event()
        loop = asyncio.get_running_loop()

        def kill(sid):
            assert sid == "target"
            loop.call_soon_threadsafe(kill_started.set)
            assert release_kill.wait(3)

        monkeypatch.setattr(
            "agent_core.core.impl.action.cancellation.kill_session_processes", kill
        )

        async def react(trigger):
            running.set()
            try:
                await release_turn.wait()
            except asyncio.CancelledError:
                cancelled.set()
                if unwind == "return":
                    return
                if unwind == "raise":
                    raise RuntimeError("Tool failed during cancellation")
                raise

        runtime = SessionRuntimeManager(react)
        store = TriggerStore(db_path=str(tmp_path / "racing.db"))
        service = TriggerService(store, runtime)
        finalized = AsyncMock()
        runtime.set_stop_finalizer(finalized)
        agent = SimpleNamespace(
            session_runtime=runtime, _emit_run_state=Mock(),
            _notify_mini_browser=Mock(),
            session_manager=SimpleNamespace(clear_session=Mock(return_value=True)),
            _persist_llm_session=Mock(),
        )
        agent.request_run_stop = MethodType(AgentBase.request_run_stop, agent)
        await runtime.start()
        tasks = []
        try:
            row = await service.emit(TriggerSpec(
                session_id="target", source=TriggerSource.USER_MESSAGE,
                description="Finish while process shutdown is pending",
            ))
            await asyncio.wait_for(running.wait(), 2)
            tasks.append(asyncio.create_task(AgentBase.clear_session(agent, "target")))
            await asyncio.wait_for(kill_started.wait(), 2)
            release_turn.set()
            # Cancellation must be requested before waiting for OS shutdown;
            # otherwise this turn finishes normally and loses the stop signal.
            await asyncio.wait_for(cancelled.wait(), .5)
            tasks.append(asyncio.create_task(runtime.request_stop("target")))
            await asyncio.sleep(0)
            assert not any(task.done() for task in tasks)
            if cancel_requester:
                tasks[0].cancel()
                with pytest.raises(asyncio.CancelledError):
                    await tasks[0]
                assert not tasks[1].done()
                finalized.assert_not_awaited()
            agent.session_manager.clear_session.assert_not_called()
            release_kill.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
            assert results[1] is True
            if cancel_requester:
                assert isinstance(results[0], asyncio.CancelledError)
                assert await AgentBase.clear_session(agent, "target")
            else:
                assert results[0] is True
            assert store.get(row.trigger_id)["status"] == "DONE"
            finalized.assert_awaited_once_with("target")
            agent.session_manager.clear_session.assert_called_once_with("target")
        finally:
            release_kill.set()
            release_turn.set()
            await runtime.stop()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


def test_clear_does_not_reset_context_after_a_stop_timeout(tmp_path, monkeypatch):
    from app.agent_base import AgentBase
    from app.triggers import TriggerService, TriggerSource, TriggerSpec
    from app.triggers.runtime import SessionRuntimeManager
    from app.triggers.store import TriggerStore

    async def scenario():
        started = asyncio.Event()
        unwinding = asyncio.Event()
        release = asyncio.Event()
        cancellations = []

        async def react(trigger):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellations.append(trigger.session_id)
                unwinding.set()
                await release.wait()
                raise

        runtime = SessionRuntimeManager(react)
        store = TriggerStore(db_path=str(tmp_path / "timeout.db"))
        service = TriggerService(store, runtime)
        finalized = AsyncMock()
        runtime.set_stop_finalizer(finalized)
        agent = SimpleNamespace(
            session_runtime=runtime, _emit_run_state=Mock(),
            _notify_mini_browser=Mock(),
            session_manager=SimpleNamespace(clear_session=Mock(return_value=True)),
            _persist_llm_session=Mock(),
        )
        agent.request_run_stop = MethodType(AgentBase.request_run_stop, agent)
        monkeypatch.setattr("app.triggers.runtime.STOP_SETTLE_TIMEOUT_S", .02)
        await runtime.start()
        try:
            row = await service.emit(TriggerSpec(session_id="target",
                source=TriggerSource.USER_MESSAGE, description="Slow tool cleanup"))
            await asyncio.wait_for(started.wait(), 2)
            with pytest.raises(asyncio.TimeoutError):
                await AgentBase.clear_session(agent, "target")
            assert unwinding.is_set()
            agent.session_manager.clear_session.assert_not_called()
            agent._persist_llm_session.assert_not_called()
            finalized.assert_not_awaited()
            assert store.get(row.trigger_id)["status"] == "CLAIMED"
            release.set()
            assert await AgentBase.clear_session(agent, "target")
            assert cancellations == ["target"]
            finalized.assert_awaited_once_with("target")
            assert store.get(row.trigger_id)["status"] == "DONE"
        finally:
            release.set()
            await runtime.stop()

    asyncio.run(scenario())


def test_clear_command_orders_storage_and_preserves_other_chat(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.ui_layer.adapters.browser_adapter import BrowserChatComponent
    from app.ui_layer.adapters.base import InterfaceAdapter
    from app.ui_layer.commands.builtin.clear import ClearCommand
    from app.ui_layer.components.types import ChatMessage
    from app.ui_layer.events.event_bus import EventBus
    from app.ui_layer.events.event_types import UIEvent, UIEventType
    from app.usage.chat_storage import ChatStorage, StoredChatMessage

    storage = ChatStorage(db_path=str(tmp_path / "chat.db"))
    storage.insert_message(StoredChatMessage(message_id="other", session_id="other",
        sender="agent", style="agent", content="Keep me", timestamp=1))
    insert_started = threading.Event()
    release_insert = threading.Event()
    original_insert = storage.insert_message

    def insert(message):
        insert_started.set()
        assert release_insert.wait(3)
        original_insert(message)

    monkeypatch.setattr(storage, "insert_message", insert)
    monkeypatch.setattr("app.usage.get_chat_storage", lambda: storage)
    actions = Mock()
    monkeypatch.setattr("app.usage.get_action_storage", lambda: actions)
    adapter = SimpleNamespace(_broadcast=AsyncMock(), broadcast_session_cleared=AsyncMock())
    chat = BrowserChatComponent.__new__(BrowserChatComponent)
    chat._storage = storage
    chat._db = ThreadPoolExecutor(max_workers=1)
    chat._messages = []
    chat._trim_at = 100
    chat._adapter = adapter
    adapter.chat_component = chat
    controller = SimpleNamespace(
        agent=SimpleNamespace(clear_session=AsyncMock(return_value=True)),
        active_adapter=adapter, event_bus=EventBus(),
    )
    command = ClearCommand(controller)
    command.emit_message = Mock()

    async def scenario():
        release_ui = asyncio.Event()
        release_other = asyncio.Event()
        other_pending = asyncio.Event()

        async def delayed_message(label, message, style, session_id=None, **kwargs):
            if session_id == "other":
                other_pending.set()
                await release_other.wait()
                return
            await release_ui.wait()
            await chat.append_message(ChatMessage(sender="agent", style="agent",
                content="Delayed old event", message_id="delayed", timestamp=3,
                session_id="target"))

        # Use the actual synchronous adapter handler, which schedules the
        # asynchronous display task returned to the bus for ownership.
        display_adapter = SimpleNamespace(_display_chat_message=delayed_message)
        controller.event_bus.subscribe(UIEventType.SYSTEM_MESSAGE,
            lambda event: InterfaceAdapter._handle_system_message(display_adapter, event))
        for sid in ("target", "other"):
            controller.event_bus.emit(UIEvent(type=UIEventType.SYSTEM_MESSAGE,
                task_id=sid, data={"message": "Old event"}))
        await asyncio.wait_for(other_pending.wait(), 2)
        append = asyncio.create_task(chat.append_message(ChatMessage(
            sender="agent", style="agent", content="Old work", message_id="old",
            timestamp=2, session_id="target")))
        try:
            assert await asyncio.to_thread(insert_started.wait, 2)
            clear = asyncio.create_task(command.execute([], session_id="target"))
            # Release only after the command has reached its first await.
            asyncio.get_running_loop().call_soon(release_ui.set)
            asyncio.get_running_loop().call_soon(release_insert.set)
            result, _ = await asyncio.wait_for(asyncio.gather(clear, append), 2)
            assert result.success
            assert storage.get_message_count("target") == 0
            assert storage.get_message_count("other") == 1
            assert chat.get_messages() == []
            actions.clear_items.assert_called_once_with("target")
            adapter.broadcast_session_cleared.assert_awaited_once_with("target")
            command.emit_message.assert_called_once_with(
                "Conversation cleared.", "system", session_id="target")
            controller.agent.clear_session.return_value = False
            actions.reset_mock()
            adapter.broadcast_session_cleared.reset_mock()
            command.emit_message.reset_mock()
            assert not (await command.execute([], session_id="missing")).success
            actions.clear_items.assert_not_called()
            adapter.broadcast_session_cleared.assert_not_awaited()
            command.emit_message.assert_not_called()
        finally:
            release_ui.set()
            release_other.set()
            release_insert.set()
            await append
            await controller.event_bus.drain("other")

    try:
        asyncio.run(scenario())
    finally:
        chat._db.shutdown(wait=True)


def test_fresh_work_waits_for_parked_run_finalization_and_context_reset(tmp_path):
    from app.agent_base import AgentBase
    from app.triggers import TriggerService, TriggerSource, TriggerSpec
    from app.triggers.runtime import SessionRuntimeManager
    from app.triggers.store import TriggerStore

    async def scenario():
        finalizing = asyncio.Event()
        release = asyncio.Event()
        claimed = asyncio.Event()
        executed = asyncio.Event()
        reset = Mock(return_value=True)

        async def finalize(sid):
            finalizing.set()
            await release.wait()

        async def react(trigger):
            reset.assert_called_once_with("target")
            executed.set()

        runtime = SessionRuntimeManager(react)
        store = TriggerStore(db_path=str(tmp_path / "parked.db"))
        service = TriggerService(store, runtime)
        original_claim = service.claim

        def claim(trigger):
            original_claim(trigger)
            claimed.set()

        service.claim = claim
        runtime.set_stop_finalizer(finalize)
        agent = SimpleNamespace(session_runtime=runtime, _emit_run_state=Mock(),
            _notify_mini_browser=Mock(), _persist_llm_session=Mock(),
            session_manager=SimpleNamespace(clear_session=reset))
        agent.request_run_stop = MethodType(AgentBase.request_run_stop, agent)
        await runtime.start()
        clear = None
        try:
            await service.emit(TriggerSpec(session_id="target",
                source=TriggerSource.RUN_CONTINUATION, description="Parked run",
                fire_at=time.time() + 60))
            clear = asyncio.create_task(AgentBase.clear_session(agent, "target"))
            await asyncio.wait_for(finalizing.wait(), 2)
            await service.emit(TriggerSpec(session_id="target",
                source=TriggerSource.USER_MESSAGE, description="Fresh request"))
            await asyncio.wait_for(claimed.wait(), 2)
            await asyncio.sleep(0)
            reset.assert_not_called()
            assert not executed.is_set()
            release.set()
            assert await asyncio.wait_for(clear, 2)
            await asyncio.wait_for(executed.wait(), 2)
        finally:
            release.set()
            await runtime.stop()
            if clear is not None:
                await clear

    asyncio.run(scenario())
