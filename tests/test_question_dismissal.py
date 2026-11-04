"""Dismissing a question uses the same session stop as the chat stop button."""

import asyncio
import time
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent_base import AgentBase
from app.triggers import TriggerService, TriggerSource, TriggerSpec
from app.triggers.runtime import SessionRuntimeManager
from app.triggers.store import TriggerStore
from app.ui_layer.controller.ui_controller import UIController


def _controller(agent):
    controller = UIController.__new__(UIController)
    controller._agent = agent
    controller._event_bus = SimpleNamespace(emit=Mock())
    return controller


@pytest.mark.parametrize(
    "mode,session_id", [("active", "chat-a"), ("queued", None), ("idle", "chat-a")]
)
def test_dismissal_stops_its_run_without_resuming_it_or_stopping_other_sessions(
    tmp_path, mode, session_id
):
    async def scenario():
        target = session_id or "main"
        started = {sid: asyncio.Event() for sid in (target, "other")}
        cancelled = {sid: asyncio.Event() for sid in started}
        release = asyncio.Event()
        late_rows = []

        async def emit(sid, source, future=False):
            return await service.emit(
                TriggerSpec(
                    session_id=sid,
                    source=source,
                    description="Synthetic work",
                    fire_at=time.time() + 60 if future else None,
                )
            )

        async def react(trigger):
            sid = trigger.session_id
            started[sid].set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled[sid].set()
                if sid == target:
                    # Even a continuation enqueued while unwinding must not
                    # resurrect the work the user just dismissed.
                    late_rows.append(
                        await emit(sid, TriggerSource.RUN_CONTINUATION, future=True)
                    )
                raise

        runtime = SessionRuntimeManager(react)
        store = TriggerStore(db_path=str(tmp_path / "triggers.db"))
        service = TriggerService(store, runtime)
        finalized = AsyncMock()
        runtime.set_stop_finalizer(finalized)
        agent = SimpleNamespace(
            session_runtime=runtime,
            _emit_run_state=Mock(),
            _notify_mini_browser=Mock(),
            _handle_chat_message=AsyncMock(),
            event_stream_manager=SimpleNamespace(log=Mock()),
            state_manager=SimpleNamespace(bump_event_stream=Mock()),
        )
        agent.request_run_stop = MethodType(AgentBase.request_run_stop, agent)
        controller = _controller(agent)
        await runtime.start()
        try:
            other = await emit("other", TriggerSource.USER_MESSAGE)
            await asyncio.wait_for(started["other"].wait(), 2)
            active = None
            if mode == "active":
                active = await emit(target, TriggerSource.USER_MESSAGE)
                await asyncio.wait_for(started[target].wait(), 2)
            continuation = None
            if mode != "idle":
                continuation = await emit(
                    target, TriggerSource.RUN_CONTINUATION, future=True
                )
            other_continuation = await emit(
                "other", TriggerSource.RUN_CONTINUATION, future=True
            )
            # Independent future requests are preserved by the shared stop.
            scheduled = await emit(target, TriggerSource.SCHEDULED, future=True)
            message = await emit(target, TriggerSource.USER_MESSAGE, future=True)

            await asyncio.wait_for(
                controller.submit_question_answer(
                    "", "Continue?", session_id, dismissed=True
                ),
                2,
            )

            assert cancelled[target].is_set() == (mode == "active")
            assert not cancelled["other"].is_set()
            assert store.get(other.trigger_id)["status"] == "CLAIMED"
            assert store.get(other_continuation.trigger_id)["status"] == "PENDING"
            for row in (scheduled, message):
                assert store.get(row.trigger_id)["status"] == "PENDING"
            if active:
                assert store.get(active.trigger_id)["status"] == "DONE"
                assert len(late_rows) == 1
            for row in ([continuation] if continuation else []) + late_rows:
                stored = store.get(row.trigger_id)
                assert (stored["status"], stored["resolution"]) == ("DONE", "cancelled")
            assert finalized.await_count == (0 if mode == "idle" else 1)
            controller._event_bus.emit.assert_not_called()
            agent._handle_chat_message.assert_not_awaited()
            agent._notify_mini_browser.assert_called_once_with(
                "cancel_owner", target, include_children=True
            )
            assert agent.event_stream_manager.log.call_args.kwargs["task_id"] == target
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_dismissal_still_stops_when_recording_the_system_message_fails():
    agent = SimpleNamespace(
        request_run_stop=AsyncMock(return_value=True),
        event_stream_manager=SimpleNamespace(log=Mock(side_effect=OSError("disk"))),
    )
    asyncio.run(
        _controller(agent).submit_question_answer(
            "", "Continue?", "chat-a", dismissed=True
        )
    )
    agent.request_run_stop.assert_awaited_once_with("chat-a")


@pytest.mark.parametrize("answer", ["Use the first option", "   "])
def test_answering_a_question_does_not_stop_the_run(answer):
    agent = SimpleNamespace(
        request_run_stop=AsyncMock(), _handle_chat_message=AsyncMock()
    )
    controller = _controller(agent)
    asyncio.run(controller.submit_question_answer(answer, "Which option?", "chat-a"))
    agent.request_run_stop.assert_not_awaited()
    if answer.strip():
        payload = agent._handle_chat_message.call_args.args[0]
        assert payload["session_id"] == "chat-a"
        assert answer in payload["text"] and "Which option?" in payload["text"]
    else:
        agent._handle_chat_message.assert_not_awaited()
        controller._event_bus.emit.assert_not_called()
