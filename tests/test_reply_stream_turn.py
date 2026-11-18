# -*- coding: utf-8 -*-
"""The turn side of a streamed reply (AgentBase + the UI transform).

* Actions start before the reply ends only on turns no whole-batch check
  can refuse after the fact.
* Actions that started early finish within the turn, and their outputs
  join the batch's.
* The rows and the message shown while the reply was written become the
  real ones: the reasoning row and the chat message carry the streamed ids.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_core.core.event_stream.event import Event, EventType


def _agent(isolated=False):
    from app.agent_base import AgentBase

    agent = AgentBase.__new__(AgentBase)
    agent.session_manager = SimpleNamespace(
        get=lambda sid: SimpleNamespace(isolated_app_task=isolated)
    )
    return agent


def _trigger(payload=None, is_self=False):
    from app.agent_base import TriggerData

    return TriggerData(
        query="q", session_id="main", payload=payload or {}, is_self_message=is_self
    )


def test_ordinary_turns_start_actions_early():
    assert _agent()._early_start_allowed(_trigger(), "main")


@pytest.mark.parametrize(
    "agent_kwargs,trigger_kwargs",
    [
        ({"isolated": True}, {}),
        ({}, {"payload": {"integration_type": "telegram_bot"}, "is_self": False}),
    ],
)
def test_turns_a_batch_check_could_refuse_wait_for_the_whole_reply(agent_kwargs, trigger_kwargs):
    assert not _agent(**agent_kwargs)._early_start_allowed(_trigger(**trigger_kwargs), "main")


def test_an_agent_app_task_waits_for_the_whole_reply():
    from app.agent_app.framework_commands import task_authority

    token = task_authority.set(SimpleNamespace(active=True))
    try:
        assert not _agent()._early_start_allowed(_trigger(), "main")
    finally:
        task_authority.reset(token)


def test_started_actions_finish_in_the_turn_and_join_its_outputs(monkeypatch):
    from app.agent_base import AgentBase
    import app.agent_base as agent_module

    monkeypatch.setattr(agent_module, "STATE", SimpleNamespace(event_stream=""))
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)
        return [{"status": "success", "action": "rest"}]

    agent = SimpleNamespace(
        session_manager=SimpleNamespace(get=lambda sid: None),
        action_manager=SimpleNamespace(execute_actions_parallel=execute),
        _merge_action_outputs=lambda results: results,
    )

    async def go():
        async def early():
            await asyncio.sleep(0.01)
            return {"status": "success", "action": "early"}

        started = [asyncio.ensure_future(early())]
        return await AgentBase._execute_actions(
            agent,
            [(SimpleNamespace(name="read_file"), {"file_path": "x"})],
            _trigger(),
            "",
            "main",
            run_ids=["run-1"],
            started=started,
        )

    outputs = asyncio.run(go())
    assert [o["action"] for o in outputs] == ["early", "rest"]
    assert calls[0]["run_ids"] == ["run-1"]


def test_a_reply_whose_actions_all_started_needs_no_batch(monkeypatch):
    from app.agent_base import AgentBase

    agent = SimpleNamespace(_merge_action_outputs=lambda results: results)

    async def go():
        async def early():
            return {"status": "success"}

        return await AgentBase._execute_actions(
            agent, [], _trigger(), "", "main", started=[asyncio.ensure_future(early())]
        )

    assert asyncio.run(go()) == [{"status": "success"}]


def _event(**kwargs):
    return Event(
        message="m",
        kind="k",
        severity="INFO",
        ts=datetime(2026, 11, 18, tzinfo=timezone.utc),
        **kwargs,
    )


def test_the_streamed_reasoning_row_and_message_become_the_real_ones():
    from app.ui_layer.events.transformer import EventTransformer

    reasoning = EventTransformer.transform(
        _event(event_type=EventType.REASONING, action_id="s:reasoning:abc"), "s"
    )
    assert reasoning.data["reasoning_id"] == "s:reasoning:abc"
    message = EventTransformer.transform(
        _event(event_type=EventType.AGENT_MESSAGE, action_id="run-7"), "s"
    )
    assert message.data["client_id"] == "run-7"
    # Without a streamed id, the old ids are unchanged.
    plain = EventTransformer.transform(_event(event_type=EventType.REASONING), "s")
    assert plain.data["reasoning_id"].startswith("s:reasoning:")


def test_a_message_sent_by_an_action_carries_its_run_id():
    from agent_core.core.impl.action.context import current_action_run_id
    from app.state.state_manager import StateManager

    logged = []
    manager = StateManager.__new__(StateManager)
    manager.event_stream_manager = SimpleNamespace(log=lambda *a, **kw: logged.append(kw))
    manager.bump_event_stream = lambda: None
    token = current_action_run_id.set("run-9")
    try:
        manager.record_agent_message("hello", session_id="s")
    finally:
        current_action_run_id.reset(token)
    assert logged[0]["action_id"] == "run-9"
