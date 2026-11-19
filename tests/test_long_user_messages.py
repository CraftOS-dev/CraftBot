# -*- coding: utf-8 -*-
"""
A long user message is saved to a file and read back in full (#441).

Observed in V1.4.2: a 26,014-character prompt showed in the chat, "Working..."
ran for a while, then disappeared with no reply. The event stream saves any
event over MAX_EVENT_INLINE_CHARS to a file and keeps a pointer, and the
pointer for a user message read "Action None completed. The output is too long
therefore is saved in ...". A synced session sends only new events, so that
pointer was all the model got of the request; and read_file, which it points
to, cuts each line at 2,000 characters, so a one-paragraph prompt could not be
read back whole either.

Long user messages are still saved to a file behind a pointer, but the pointer
says what it is, and CraftBot reads the file back into the stream right after
it, in parts no fold collapses, before the turn decides. These drive the real
AgentBase claim step, ActionRouter and EventStream with an LLM that records
what it is sent; one goes through the real LLMInterface to the provider call.

See agent_core/core/impl/event_stream/event_stream.py and
AgentBase._log_deferred_user_messages in app/agent_base.py.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_core.core.event_stream.event import EventRecord, EventType
from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.action.router import ActionRouter
from agent_core.core.impl.event_stream.event_stream import (
    MAX_EVENT_INLINE_CHARS,
    USER_MESSAGE_PART_KIND,
    EventStream,
)
from agent_core.core.impl.llm.interface import LLMInterface
from agent_core.core.impl.llm import transports as _transports
from app import config as app_config
from app.agent_base import AgentBase
from app.models.factory import ModelFactory

SESSION = "chat_441"
MARKERS = ("BEGIN-MARK-7f3a", "MIDDLE-MARK-7f3a", "END-MARK-7f3a")


def long_message(tag: str = "", size: int = 26_014, sep: str = " ") -> str:
    """One paragraph (a single line) of ``size`` characters with a marker at
    its beginning, middle and end; ``tag`` makes the markers distinct."""
    begin, middle, end = (m + tag for m in MARKERS)
    body = sep.join(["Context about our content operations and positioning."] * 2000)
    text = f"{begin} {body}"
    half = size // 2
    text = f"{text[:half]} {middle} {text[half:]}"
    text = text[: size - len(end) - 1] + f" {end}"
    assert len(text) == size
    return text


LONG = long_message()  # the size reported in #441


class _SummarizingLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        return "SUMMARY OF OLD EVENTS"


def _stream(tmp_path) -> EventStream:
    return EventStream(llm=_SummarizingLLM(), temp_dir=tmp_path / "events")


def _agent_over(es: EventStream) -> AgentBase:
    """An AgentBase whose claim step writes to ``es``."""
    agent = AgentBase.__new__(AgentBase)
    agent.event_stream_manager = SimpleNamespace(
        log=lambda kind, message, task_id=None, **kw: es.log(kind, message, **kw),
        get_stream_by_id=lambda sid: es,
    )
    agent.state_manager = SimpleNamespace(bump_event_stream=lambda: None)
    return agent


def _claim(es: EventStream, *texts: str, platform=None) -> None:
    """What react() does when a user-message trigger carrying ``texts`` is
    claimed: AgentBase._log_deferred_user_messages."""
    label = f"user message from platform: {platform}" if platform else "user message"
    trigger = SimpleNamespace(
        source="user_message",
        payload={
            "platform": platform,
            "queued_user_messages": [
                {"label": label, "content": t, "display": t} for t in texts
            ],
        },
    )
    asyncio.run(_agent_over(es)._log_deferred_user_messages(trigger, SESSION))


def _parts(es: EventStream) -> list:
    return [r for r in es.tail_events if r.event.kind == USER_MESSAGE_PART_KIND]


def _part_text(rec) -> str:
    """A part's text without its header and footer lines."""
    return rec.event.message.split("\n", 1)[1].rsplit("\n", 1)[0]


# --- The stream: a typed pointer, then the whole text read back ---------------


def test_a_long_user_message_is_saved_to_a_file_behind_a_typed_pointer(tmp_path):
    es = _stream(tmp_path)
    es.log("user message", LONG, event_type=EventType.USER_MESSAGE)

    pointer = es.tail_events[-1].event
    assert len(pointer.message) < 1000
    assert pointer.message.startswith("[User message saved to a file]")
    assert "26,014 characters" in pointer.message
    assert "Action None" not in pointer.message
    assert not any(m in pointer.message for m in MARKERS)
    meta = pointer.externalized
    assert (meta["content"], meta["chars"]) == ("user_message", 26_014)
    with open(meta["path"], encoding="utf-8", newline="") as f:
        assert f.read() == LONG
    # Persisted with the stream (session storage), and loaded back.
    record = es.tail_events[-1]
    assert EventRecord.from_dict(record.to_dict()).event.externalized == meta


@pytest.mark.parametrize(
    "text",
    [
        LONG,
        long_message(size=90_004),  # one line longer than read_file can return
        long_message(sep="\r\n"),  # Windows line breaks, kept as sent
    ],
    ids=["26014-one-line", "90004-one-line", "crlf-lines"],
)
def test_claiming_it_reads_the_whole_text_back_right_after_the_pointer(tmp_path, text):
    es = _stream(tmp_path)
    _claim(es, text)

    kinds = [r.event.kind for r in es.tail_events if r.event.kind != "datetime"]
    parts = _parts(es)
    assert kinds == ["user message"] + [USER_MESSAGE_PART_KIND] * len(parts)
    assert "".join(_part_text(p) for p in parts) == text
    # No part is long enough for a fold or the router to collapse it again.
    assert all(len(p.event.message) <= MAX_EVENT_INLINE_CHARS for p in parts)
    pointer = es.tail_events[-1 - len(parts)].event
    assert f"in {len(parts)} part(s)" in pointer.message
    assert pointer.externalized["retrieved"] is True
    assert es.collapse_undelivered_oversize() == 0
    assert "".join(_part_text(p) for p in _parts(es)) == text


def test_a_pointer_a_restart_left_unread_is_read_back_by_the_next_claim(tmp_path):
    """Logged, then the app stopped before its text was read back: the next
    claim in the session reads it back too, after its own pointer."""
    es = _stream(tmp_path)
    es.log("user message", LONG, event_type=EventType.USER_MESSAGE)  # no read-back

    _claim(es, "a follow-up")

    events = [r.event for r in es.tail_events if r.event.kind != "datetime"]
    assert events[0].externalized["retrieved"] is True
    assert "".join(_part_text(p) for p in _parts(es)) == LONG
    assert [e.kind for e in events][-1] == "user message"  # the follow-up, after
    assert events[-1].message == "a follow-up"


def test_short_user_messages_stay_inline(tmp_path):
    es = _stream(tmp_path)
    _claim(es, "  hello there  ")

    assert es.tail_events[-1].event.message == "hello there"
    assert es.tail_events[-1].event.externalized is None
    assert _parts(es) == []


# --- Large action outputs: unchanged -------------------------------------------


def test_large_action_output_still_moves_to_a_file(tmp_path):
    es = _stream(tmp_path)
    output = "row of tool output " * 2000
    es.log(
        "action_end", output, event_type=EventType.ACTION_END, action_name="run_shell"
    )

    event = es.tail_events[-1].event
    assert event.message.startswith(
        "Action run_shell completed. The output is too long"
    )
    assert "'read_file'" in event.message and "'grep_files'" in event.message
    assert event.externalized["content"] == "output"
    assert _parts(es) == []  # nothing is read back for the agent


def test_retrieval_outputs_and_schemas_stay_inline_until_delivered(tmp_path):
    es = _stream(tmp_path)
    big = "matched line " * 3000
    es.log("action_end", big, event_type=EventType.ACTION_END, action_name="read_file")
    es.log("schemas", "schema " * 4000, event_type=EventType.ACTION_SCHEMAS)
    assert es.tail_events[-2].event.message == big.strip()

    # The router's last resort still collapses a retrieval output it cannot send.
    assert es.collapse_undelivered_oversize() > 0
    assert es.tail_events[-2].event.message.startswith("Action read_file completed.")
    assert es.tail_events[-1].event.message.startswith("schema schema")


def test_an_event_without_an_action_no_longer_claims_one_completed(tmp_path):
    es = _stream(tmp_path)
    pointer = es._externalize_message("x" * 20_000)  # e.g. a long agent message

    assert "Action None" not in pointer
    assert pointer.startswith("The content of this event event is too long")


def test_folding_still_summarizes_what_was_read_back(tmp_path):
    es = _stream(tmp_path)
    _claim(es, LONG)
    for text in ("done", "anything else?", "no"):  # past the pinned newest two
        es.log("agent message", text, event_type=EventType.AGENT_MESSAGE)
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=10)

    assert es.head_summary and "SUMMARY OF OLD EVENTS" in es.head_summary
    assert _parts(es) == []


# --- Router: what the model is sent ---------------------------------------------


class _ContextEngine:
    """The stream accessors of the real ContextEngine, over one EventStream."""

    def __init__(self, stream: EventStream):
        self.stream = stream

    def get_compiled_actions(self, session_id=None):
        return []

    def get_session_state(self, session_id=None):
        return ""

    def make_prompt(self, user_flags=None, system_flags=None):
        return "SYSTEM PROMPT", None

    def get_event_stream(self, session_id=None, up_to=None):
        return self.stream.to_prompt_snapshot(up_to=up_to)

    def get_event_stream_delta(self, call_type, session_id=None, up_to=None):
        delta, has_delta = self.stream.get_delta_events(call_type, up_to=up_to)
        return (delta, True) if has_delta else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        self.stream.mark_session_synced(call_type, up_to=up_to)

    def reset_event_stream_sync(self, call_type, session_id=None, reason=""):
        self.stream.reset_session_sync(call_type, reason=reason)


def _router_over(es: EventStream, llm, monkeypatch) -> ActionRouter:
    """The real ActionRouter, deciding over ``es`` with ``llm``."""
    monkeypatch.setattr(
        router_module,
        "get_event_stream_manager",
        lambda: SimpleNamespace(get_stream_by_id=lambda sid: es),
    )
    router = ActionRouter(None, llm, _ContextEngine(es))
    router._validate_parallel_actions = lambda actions, *a, **k: actions
    return router


def _query_for(text: str) -> str:
    """The trigger description AgentBase._handle_chat_message builds for
    ``text``: the {query} of the turn that answers it."""
    specs = []

    async def emit(spec):
        specs.append(spec)

    agent = AgentBase.__new__(AgentBase)
    agent.llm = SimpleNamespace(reset_failure_counter=lambda: None)
    agent.session_manager = SimpleNamespace(
        get=lambda sid: SimpleNamespace(
            id=sid, agent_app_project_id=None, type=None, title="t"
        )
    )
    agent.trigger_service = SimpleNamespace(emit=emit)
    asyncio.run(agent._handle_chat_message({"text": text, "session_id": SESSION}))
    return specs[0].description


def _turn(router: ActionRouter, query: str):
    return asyncio.run(router.select_action_in_session(query=query, session_id=SESSION))


def _user_turn(router, es, *texts):
    """A turn answering ``texts``: claimed into the stream, then decided."""
    _claim(es, *texts)
    return _turn(router, _query_for(texts[-1]))


def _real_llm_interface(session_cache: bool = True) -> LLMInterface:
    """A real LLMInterface on an OpenAI-compatible provider: session history
    (``session_cache``) or stateless requests."""
    ctx = {
        "provider": "grok",
        "model": "grok-3",
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
        iface = LLMInterface(
            provider="grok", model="grok-3", api_key="k", base_url="", max_tokens=8000
        )
    if session_cache:
        iface.create_session_cache(SESSION, "action_selection", "SYSTEM PROMPT")
    return iface


@pytest.fixture
def provider(tmp_path, monkeypatch):
    """The real router and LLMInterface over one stream. ``sent`` gets each
    request's messages exactly as handed to the provider transport, which
    answers with what it could act on: "I read the whole request" only when
    every marker arrived."""
    es = _stream(tmp_path)
    sent: list = []

    def generate_openai(self, system_prompt, user_prompt, messages_override=None, **kw):
        messages = [dict(m) for m in messages_override or []] or [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        sent.append(messages)
        whole = all(m in _payload(messages) for m in MARKERS)
        reply = "I read the whole request" if whole else "I read part of it"
        decision = {
            "reasoning": "r",
            "actions": [
                {"action_name": "send_message", "parameters": {"message": reply}}
            ],
        }
        return {"content": json.dumps(decision), "tokens_used": 1}

    monkeypatch.setattr(LLMInterface, "_generate_openai", generate_openai)
    # Stateless requests go straight to the wire transport.
    monkeypatch.setitem(_transports.TRANSPORTS, "chat_completions", generate_openai)
    settings = {
        "model": {"context_window": 128000},
        "context": {"keep_recent_tokens": 20000},
    }
    monkeypatch.setattr(app_config, "get_settings", lambda *a, **k: settings)

    def build(session_cache: bool = True):
        llm = _real_llm_interface(session_cache)
        return _router_over(es, llm, monkeypatch)

    return es, build, sent


def _payload(messages) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


def _reply(decisions) -> str:
    return decisions[0]["parameters"]["message"]


@pytest.mark.parametrize(
    ("message", "copies"),
    [
        # Restated in the query and quoted in the stream, as always.
        ("short question " + MARKERS[0], 2),
        # Read back into the stream once; the query refers to it.
        (LONG, 1),
    ],
    ids=["short", "long"],
)
def test_a_new_chat_hands_the_provider_the_whole_message(provider, message, copies):
    es, build, sent = provider
    router = build()

    _user_turn(router, es, message)

    assert len(sent) == 1
    payload = _payload(sent[0])
    present = [m for m in MARKERS if m in message]
    assert [payload.count(m) for m in present] == [copies] * len(present)
    assert "Action None completed" not in payload
    if copies == 1:
        assert "26,014-character message: its full text is in the event" in payload
        assert payload.index("[User message saved to a file]") < payload.index(
            MARKERS[0]
        )
        assert [payload.index(m) for m in MARKERS] == sorted(
            payload.index(m) for m in MARKERS
        )


def test_an_established_chat_hands_the_provider_the_whole_new_message(provider):
    """#441 itself: a synced session sends only new events. The read-back
    text is one of them, so the model gets the request, not a file path."""
    es, build, sent = provider
    router = build()
    _user_turn(router, es, "earlier question about pricing")
    es.log("agent message", "earlier answer", event_type=EventType.AGENT_MESSAGE)
    _turn(router, "Perform the next best action")

    decisions = _user_turn(router, es, LONG)

    request, new_turn = _payload(sent[-1]), str(sent[-1][-1]["content"])
    assert [request.count(m) for m in MARKERS] == [1, 1, 1]
    assert all(m in new_turn for m in MARKERS)  # in the delta, not resent history
    assert "earlier question about pricing" not in new_turn
    assert "Action None completed" not in request
    assert _reply(decisions) == "I read the whole request"


def test_a_continuation_keeps_the_message_in_history_without_resending_it(provider):
    es, build, sent = provider
    router = build()
    _user_turn(router, es, LONG)
    es.log("action_end", "send_message -> ok", event_type=EventType.ACTION_END)

    decisions = _turn(router, "Perform the next best action based on the todos")

    request, new_turn = _payload(sent[-1]), str(sent[-1][-1]["content"])
    assert [request.count(m) for m in MARKERS] == [1, 1, 1]  # the history
    assert not any(m in new_turn for m in MARKERS)
    assert "send_message -> ok" in new_turn
    assert _reply(decisions) == "I read the whole request"


def test_a_stateless_continuation_carries_the_message_once(provider):
    """Stateless providers re-send the whole stream every turn."""
    es, build, sent = provider
    router = build(session_cache=False)
    _user_turn(router, es, LONG)
    es.log("action_end", "send_message -> ok", event_type=EventType.ACTION_END)

    _turn(router, "Perform the next best action based on the todos")

    request = _payload(sent[-1])
    assert [request.count(m) for m in MARKERS] == [1, 1, 1]
    assert request.index(MARKERS[2]) < request.index("send_message -> ok")


def test_a_batch_reaches_the_provider_in_order_and_each_marker_once(provider):
    es, build, sent = provider
    router = build()
    first, second = long_message("-one"), long_message("-two", size=40_000)

    _user_turn(router, es, first, second)

    # The stream: pointer 1, its parts, pointer 2, its parts; each part
    # names the file it came from.
    events = [r.event for r in es.tail_events if r.event.kind != "datetime"]
    two = [i for i, e in enumerate(events) if e.kind == "user message"][1]
    for pointer, parts, text in (
        (0, events[1:two], first),
        (two, events[two + 1 :], second),
    ):
        path = events[pointer].externalized["path"]
        assert all(e.externalized["part_of"] == path for e in parts)
        assert "".join(_part_text(SimpleNamespace(event=e)) for e in parts) == text
    # The provider: every marker once, in order.
    request = _payload(sent[-1])
    marks = [m + tag for tag in ("-one", "-two") for m in MARKERS]
    assert [request.count(m) for m in marks] == [1] * 6
    assert [request.index(m) for m in marks] == sorted(request.index(m) for m in marks)
