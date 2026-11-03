# -*- coding: utf-8 -*-
"""The decision instructions end the system prompt (prompt audit T1).

The rules and the session's <actions> list used to open the first user
message of every session history, where a provider caches them per session
only. They now end the system prompt, shared by every session of a type.
These tests pin:

* the model reads the same text in the same order: instructions end the
  system prompt, the user message starts with the session's own part;
* a session history keeps the instructions it started with, so a change in
  what renders now (the Mini Browser rule dropping) never breaks the cached
  prefix of a history in progress; a new history starts on the current ones;
* stateless requests always carry the current instructions;
* session caches register the same system prompt decisions send.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.context.engine import ContextEngine
from agent_core.core.impl.llm import LLMCallType
from agent_core.core.prompts.action import (
    SELECT_ACTION_INSTRUCTIONS,
    SELECT_ACTION_PROMPT,
    decision_system_prompt,
)

ACTION = LLMCallType.ACTION_SELECTION
DECISION = (
    '{"reasoning": "r", "actions": [{"action_name": "end_turn", "parameters": {}}]}'
)


def test_the_user_message_starts_with_the_session_part():
    assert SELECT_ACTION_INSTRUCTIONS.startswith("<rules>")
    assert SELECT_ACTION_INSTRUCTIONS.rstrip().endswith("</actions>")
    assert SELECT_ACTION_PROMPT.startswith("{session_state}")
    for tag in ("<rules>", "<actions>", "<output_format>", "<parallel_actions>"):
        assert tag not in SELECT_ACTION_PROMPT


def test_instructions_end_the_system_prompt():
    assert decision_system_prompt("BASE", "INSTR") == "BASE\n\nINSTR"
    assert decision_system_prompt("BASE", "") == "BASE"


def test_the_context_engine_builds_it_from_the_router_hook():
    engine = ContextEngine(state_manager=None)
    engine.make_prompt = lambda **kw: ("BASE", "")
    assert engine.make_decision_system_prompt("s1") == "BASE"

    seen = []

    def instructions(session_id):
        seen.append(session_id)
        return "INSTR"

    engine.set_decision_instructions_hook(instructions)
    assert engine.make_decision_system_prompt("s1") == "BASE\n\nINSTR"
    assert seen == ["s1"]


# ── the router's session path ────────────────────────────────────────────────


class _Stream:
    def __init__(self):
        self.synced = False
        self.pending = True

    def has_session_sync(self, call_type):
        return self.synced

    def sync_marker(self, call_type):
        return None

    def mark_delivered(self, *args):
        pass

    def get_event_count(self):
        return 0

    def set_reply_in_history(self, call_type, decision):
        pass

    def unsynced_reason(self, call_type):
        return "first"


class _Context:
    def __init__(self, stream):
        self.stream = stream

    def make_prompt(self, **kwargs):
        return "BASE", ""

    def get_event_stream_delta(self, call_type, session_id=None, up_to=None):
        return ("DELTA", True) if self.stream.pending else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        self.stream.synced = True
        self.stream.pending = False

    def reset_event_stream_sync(self, call_type, session_id=None, reason="reset"):
        self.stream.synced = False


class _LLM:
    def __init__(self, sessions=True):
        self.sessions = sessions
        self.sent = []

    def has_session_cache(self, task_id, call_type):
        return self.sessions

    def fits_context(self, *args):
        return True

    def reset_session_history(self, task_id, call_type):
        pass

    def checkpoint_session(self, *args):
        pass

    def session_turn_recorded(self, task_id, call_type):
        return True

    async def generate_response_with_session_async(
        self,
        task_id,
        call_type,
        user_prompt,
        system_prompt_for_new_session,
        prompt_name=None,
        call_metadata=None,
    ):
        self.sent.append((system_prompt_for_new_session, user_prompt))
        return DECISION

    async def generate_response_async(self, system_prompt, user_prompt, **kwargs):
        self.sent.append((system_prompt, user_prompt))
        return DECISION


def _router(monkeypatch, llm, stream):
    manager = SimpleNamespace(get_stream_by_id=lambda session_id: stream)
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: manager)
    return router_module.ActionRouter(None, llm, _Context(stream))


def _decide(router, instructions):
    return asyncio.run(
        router._prompt_for_decision(
            "FULL",
            is_task=True,
            session_id="s1",
            render_prompt=lambda up_to=None: "FULL",
            instructions=instructions,
        )
    )


def test_a_history_keeps_the_instructions_it_started_with(monkeypatch):
    stream, llm = _Stream(), _LLM()
    router = _router(monkeypatch, llm, stream)

    _decide(router, "RULES-A")  # first call: a new history
    stream.pending = True
    _decide(router, "RULES-B")  # the rendering changed mid-history
    assert llm.sent == [("BASE\n\nRULES-A", "FULL"), ("BASE\n\nRULES-A", "DELTA")]


def test_a_new_history_starts_on_the_current_instructions(monkeypatch):
    stream, llm = _Stream(), _LLM()
    router = _router(monkeypatch, llm, stream)

    _decide(router, "RULES-A")
    stream.synced = False  # a fold or reset: the next request starts anew
    stream.pending = True
    _decide(router, "RULES-B")
    stream.pending = True
    _decide(router, "RULES-C")
    assert llm.sent[1:] == [("BASE\n\nRULES-B", "FULL"), ("BASE\n\nRULES-B", "DELTA")]


def test_a_history_restored_after_a_restart_keeps_what_renders_then(monkeypatch):
    stream, llm = _Stream(), _LLM()
    stream.synced = True  # restored at boot: the router has seen no request yet
    router = _router(monkeypatch, llm, stream)

    _decide(router, "RULES-A")
    stream.pending = True
    _decide(router, "RULES-B")
    assert llm.sent == [("BASE\n\nRULES-A", "DELTA"), ("BASE\n\nRULES-A", "DELTA")]


def test_stateless_requests_carry_the_current_instructions(monkeypatch):
    stream, llm = _Stream(), _LLM(sessions=False)
    router = _router(monkeypatch, llm, stream)

    _decide(router, "RULES-A")
    _decide(router, "RULES-B")
    assert llm.sent == [("BASE\n\nRULES-A", "FULL"), ("BASE\n\nRULES-B", "FULL")]


# ── session cache registration ───────────────────────────────────────────────


def test_session_caches_register_the_decision_system_prompt(tmp_path):
    from agent_core.core.impl.session.manager import SessionManager
    from agent_core.core.state.session import StateSession

    registered = {}

    class _Registry:
        def create_session_cache(self, task_id, call_type, system_prompt):
            registered[(task_id, call_type)] = system_prompt
            return f"{task_id}:{call_type}"

    engine = SimpleNamespace(
        make_decision_system_prompt=lambda session_id=None: f"SYSTEM+{session_id}"
    )
    manager = SessionManager(
        event_stream_manager=None,
        llm_interface=_Registry(),
        context_engine=engine,
        workspace_root=tmp_path,
    )
    session = manager.create_session()
    try:
        assert registered[(session.id, ACTION)] == f"SYSTEM+{session.id}"
    finally:
        StateSession.end(session.id)
