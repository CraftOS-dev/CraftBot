# -*- coding: utf-8 -*-
"""A chat session gets one auto-title request at a time (prompt audit T13).

The first message starts a title request, and the run's end starts a
fallback one while the chat is still untitled, so a quick run had two in
flight and the last to finish won; either could also replace a title the
user had set meanwhile. These tests pin:

* a title request started while another is in flight does nothing;
* a title is only written while the chat has none;
* once a request ends, the next one may run (the fallback still works).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.agent_base import AgentBase


class _Sessions:
    def __init__(self):
        self.session = SimpleNamespace(id="c1", title="New chat")
        self.renames = []

    def get(self, session_id):
        return self.session if session_id == "c1" else None

    def rename_session(self, session_id, title):
        self.renames.append(title)
        self.session.title = title


class _SlowLLM:
    """Answers each title request once ``release`` is set."""

    def __init__(self):
        self.calls = 0
        self.release = asyncio.Event()

    async def generate_response_async(self, system_prompt=None, user_prompt=None, **kw):
        self.calls += 1
        await self.release.wait()
        return '{"title": "Trip To Lisbon"}'


def _agent():
    agent = AgentBase.__new__(AgentBase)
    agent.session_manager = _Sessions()
    agent.llm = _SlowLLM()
    agent.ui_controller = None
    agent.titling_sessions = set()
    agent.event_stream_manager = SimpleNamespace(
        get_stream_by_id=lambda sid: SimpleNamespace(
            to_prompt_snapshot=lambda **kw: "10:00:00 [user message]: plan a trip"
        )
    )
    return agent


def test_one_title_request_at_a_time():
    agent = _agent()

    async def scenario():
        first = asyncio.create_task(
            agent._auto_title_session("c1", first_request="plan a trip to Lisbon")
        )
        await asyncio.sleep(0)  # the first request is in flight
        await agent._auto_title_session("c1")  # the run-end fallback
        agent.llm.release.set()
        await first

    asyncio.run(scenario())
    assert agent.llm.calls == 1
    assert agent.session_manager.renames == ["Trip To Lisbon"]
    assert agent.titling_sessions == set()


def test_a_title_set_meanwhile_is_kept():
    agent = _agent()

    async def scenario():
        task = asyncio.create_task(
            agent._auto_title_session("c1", first_request="plan a trip to Lisbon")
        )
        await asyncio.sleep(0)
        agent.session_manager.session.title = "My trip"  # the user renames it
        agent.llm.release.set()
        await task

    asyncio.run(scenario())
    assert agent.session_manager.session.title == "My trip"
    assert agent.session_manager.renames == []


def test_the_fallback_runs_once_the_first_request_has_ended():
    agent = _agent()
    agent.llm.release.set()

    async def scenario():
        agent.session_manager.session.title = "New chat"
        await agent._auto_title_session("c1")

    asyncio.run(scenario())
    assert agent.llm.calls == 1
    assert agent.session_manager.renames == ["Trip To Lisbon"]
