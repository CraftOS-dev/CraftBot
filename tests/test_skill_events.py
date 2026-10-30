# -*- coding: utf-8 -*-
"""Skills are delivered as events in the session's stream (prompt audit T2).

A skill's instructions used to be rendered inside the <session> block, which
sits ahead of the event stream in the cached prompt, so every use_skill /
unload_skill (and every workflow run's skill) reset the session history and
resent the whole prompt. They now enter the stream as one event when the
skill is loaded. These tests pin:

* load and unload log one event each; nothing above the stream changes, so
  the next decision continues the history with a delta;
* a fold keeps a loaded skill's newest instructions verbatim (never
  summarized), however many folds happen; unloaded or superseded
  instructions are dropped, and the token count stays exact;
* instructions are never turned into a pointer, survive persistence, and
  never show in the chat;
* a session whose stream lacks a loaded skill's instructions (saved before
  this change) gets them at boot, once.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agent_core.core.event_stream.event import Event, EventRecord, EventType
from agent_core.core.impl.event_stream.event_stream import (
    EventStream,
    get_cached_token_count,
)
from agent_core.core.impl.event_stream.manager import EventStreamManager
from agent_core.core.impl.llm import LLMCallType
from agent_core.core.impl.session.manager import SessionManager
from agent_core.core.impl.skill.manager import skill_manager
from agent_core.core.state.session import StateSession

ACTION = LLMCallType.ACTION_SELECTION
INSTRUCTIONS = {
    "deep-research": "Plan the research. Cite every source. " * 20,
    "pdf": "Use pypdf to read and write PDF files. " * 20,
}


class _SummaryLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.prompts = []

    def generate_response(self, user_prompt=None, **kwargs):
        self.prompts.append(user_prompt)
        return "SUMMARY"


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        skill_manager,
        "get_skill_instructions",
        lambda names, max_tokens=None: "\n\n".join(
            f"## Skill: {n}\n\n{INSTRUCTIONS[n]}" for n in names if n in INSTRUCTIONS
        ),
    )
    llm = _SummaryLLM()
    streams = EventStreamManager(llm=llm)
    manager = SessionManager(
        event_stream_manager=streams,
        workspace_root=tmp_path,
        on_stream_create=lambda sid, wd: streams.create_stream(sid, None),
    )
    created = []

    def new_session(**kwargs):
        session = manager.create_session(**kwargs)
        created.append(session.id)
        return session, streams.get_stream_by_id(session.id)

    yield SimpleNamespace(
        manager=manager, streams=streams, llm=llm, new_session=new_session
    )
    for sid in created:
        StateSession.end(sid)


def _skill_events(stream, event_type=EventType.SKILL_INSTRUCTIONS):
    return [r for r in stream.tail_events if r.event.event_type is event_type]


def _fill(stream, events=300):
    for i in range(events):
        stream.log("action_end", f"action {i} produced output " + "x " * 50)
    stream.mark_delivered()


def _fold(stream):
    return stream.summarize_by_LLM(keep_tokens=200)


# ── load and unload ──────────────────────────────────────────────────────────


def test_loading_a_skill_logs_its_instructions_once(sessions):
    session, stream = sessions.new_session()
    sessions.manager.add_skill(session.id, "deep-research")
    sessions.manager.add_skill(session.id, "deep-research")  # already loaded

    (event,) = _skill_events(stream)
    assert event.event.skill_name == "deep-research"
    assert INSTRUCTIONS["deep-research"].strip() in event.event.message
    assert "until it is unloaded" in event.event.message
    assert stream.loaded_skills() == ["deep-research"]


def test_unloading_logs_a_marker_and_a_reload_logs_again(sessions):
    session, stream = sessions.new_session()
    sessions.manager.add_skill(session.id, "pdf")
    sessions.manager.remove_skill(session.id, "pdf")
    sessions.manager.remove_skill(session.id, "pdf")  # not loaded any more

    assert len(_skill_events(stream, EventType.SKILL_UNLOADED)) == 1
    assert stream.loaded_skills() == []
    sessions.manager.add_skill(session.id, "pdf")
    assert len(_skill_events(stream)) == 2 and stream.loaded_skills() == ["pdf"]


def test_preloaded_skills_bring_their_instructions(sessions):
    session, stream = sessions.new_session(selected_skills=["pdf"])
    assert [r.event.skill_name for r in _skill_events(stream)] == ["pdf"]


def test_the_session_block_no_longer_lists_skills(sessions):
    from agent_core.core.impl.context.engine import ContextEngine

    session, _ = sessions.new_session()
    sessions.manager.add_skill(session.id, "deep-research")
    block = ContextEngine(state_manager=None).get_session_state(session.id)
    assert "deep-research" not in block and "Cite every source" not in block


# ── folds ────────────────────────────────────────────────────────────────────


def test_a_loaded_skill_survives_every_fold_verbatim(sessions):
    session, stream = sessions.new_session()
    sessions.manager.add_skill(session.id, "deep-research")
    original = _skill_events(stream)[0].event.message

    for _ in range(3):
        _fill(stream)
        assert _fold(stream) > 0

    (kept,) = _skill_events(stream)
    assert kept.event.message == original
    assert stream.tail_events[0] is kept  # at the front of what was kept
    # Never part of what was summarized.
    assert sessions.llm.prompts and not any(
        "Cite every source" in p for p in sessions.llm.prompts
    )
    assert stream.to_prompt_snapshot().count("Cite every source") == 20


def test_an_unloaded_skill_leaves_with_the_next_fold(sessions):
    session, stream = sessions.new_session()
    sessions.manager.add_skill(session.id, "pdf")
    sessions.manager.remove_skill(session.id, "pdf")
    _fill(stream)
    _fold(stream)
    assert _skill_events(stream) == []
    assert "Use pypdf" not in stream.to_prompt_snapshot()


def test_superseded_instructions_leave_and_the_newest_stays(sessions):
    session, stream = sessions.new_session()
    sessions.manager.add_skill(session.id, "pdf")
    sessions.manager.remove_skill(session.id, "pdf")
    sessions.manager.add_skill(session.id, "pdf")
    newest = _skill_events(stream)[-1]
    _fill(stream)
    _fold(stream)
    assert _skill_events(stream) == [newest]


def test_the_token_count_stays_exact_across_folds(sessions):
    session, stream = sessions.new_session()
    sessions.manager.add_skill(session.id, "pdf")
    sessions.manager.add_skill(session.id, "deep-research")
    sessions.manager.remove_skill(session.id, "pdf")
    for _ in range(2):
        _fill(stream)
        _fold(stream)
        assert stream._total_tokens == sum(
            get_cached_token_count(r) for r in stream.tail_events
        )
    assert stream.loaded_skill_tokens() == get_cached_token_count(
        _skill_events(stream)[0]
    )


def test_long_instructions_are_never_turned_into_a_pointer(tmp_path):
    stream = EventStream(llm=None, temp_dir=tmp_path)
    text = "step " * 5000  # well over the 16k-character inline cap
    stream.log(
        "skill_instructions",
        text,
        event_type=EventType.SKILL_INSTRUCTIONS,
        skill_name="big",
    )
    stream.log("action_end", "y " * 9000)  # an ordinary event is externalized
    assert stream.tail_events[-2].event.message == text.strip()
    assert stream.tail_events[-1].event.message != ("y " * 9000).strip()


# ── persistence, chat, boot ──────────────────────────────────────────────────


def test_skill_events_survive_persistence():
    event = Event(
        message="m",
        kind="skill_instructions",
        severity="INFO",
        event_type=EventType.SKILL_INSTRUCTIONS,
        skill_name="pdf",
    )
    restored = EventRecord.from_dict(
        json.loads(json.dumps(EventRecord(event=event).to_dict()))
    )
    assert restored.event.skill_name == "pdf"
    assert restored.event.event_type is EventType.SKILL_INSTRUCTIONS


def test_skill_events_never_show_in_the_chat():
    from app.ui_layer.events.transformer import EventTransformer

    for event_type in (EventType.SKILL_INSTRUCTIONS, EventType.SKILL_UNLOADED):
        event = Event(message="m", kind="k", severity="INFO", event_type=event_type)
        assert event_type in EventTransformer._DISPATCH
        assert EventTransformer.transform(event) is None


def test_boot_gives_a_loaded_skill_its_instructions_once(sessions):
    session, stream = sessions.new_session()
    session.selected_skills.append("pdf")  # saved before skills were events
    assert _skill_events(stream) == []

    sessions.manager.restore_skill_instructions()
    sessions.manager.restore_skill_instructions()
    assert [r.event.skill_name for r in _skill_events(stream)] == ["pdf"]


# ── the session history continues ────────────────────────────────────────────


class _StreamContext:
    def __init__(self, stream):
        self.stream = stream

    def make_prompt(self, **kwargs):
        return "BASE", ""

    def get_event_stream_delta(self, call_type, session_id=None, up_to=None):
        delta, has_delta = self.stream.get_delta_events(call_type, up_to=up_to)
        return (delta, True) if has_delta else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        self.stream.mark_session_synced(call_type, up_to=up_to)

    def reset_event_stream_sync(self, call_type, session_id=None, reason="reset"):
        self.stream.reset_session_sync(call_type, reason=reason)


class _LLM:
    def __init__(self):
        self.sent = []

    def has_session_cache(self, task_id, call_type):
        return True

    def fits_context(self, *args):
        return True

    def reset_session_history(self, task_id, call_type):
        pass

    def checkpoint_session(self, *args):
        pass

    def session_turn_recorded(self, task_id, call_type):
        return True

    async def generate_response_with_session_async(
        self, task_id, call_type, user_prompt, system_prompt_for_new_session, **kw
    ):
        self.sent.append({"user": user_prompt, "metadata": kw.get("call_metadata")})
        return '{"reasoning": "r", "actions": [{"action_name": "end_turn", "parameters": {}}]}'


def test_loading_a_skill_continues_the_history(sessions, monkeypatch):
    from agent_core.core.impl.action import router as router_module

    session, stream = sessions.new_session()
    stream.log("user message", "research this")
    manager = SimpleNamespace(get_stream_by_id=lambda sid: stream)
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: manager)
    llm = _LLM()
    router = router_module.ActionRouter(None, llm, _StreamContext(stream))

    def decide():
        return asyncio.run(
            router._prompt_for_decision(
                "FULL",
                is_task=True,
                session_id=session.id,
                render_prompt=lambda up_to=None: stream.to_prompt_snapshot(up_to=up_to),
                instructions="INSTR",
            )
        )

    decide()
    sessions.manager.add_skill(session.id, "deep-research")
    decide()

    first, after_load = llm.sent
    assert first["metadata"]["request"] == "full"
    assert after_load["metadata"] == {"request": "delta"}  # no new history
    assert "Skill 'deep-research' loaded" in after_load["user"]
