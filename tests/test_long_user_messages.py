# -*- coding: utf-8 -*-
"""
A long user message must reach the model as written (#441).

Observed in V1.4.2: a 26,014-character prompt showed in the chat, "Working..."
ran for a while, then disappeared with no reply. The event stream moved every
event over MAX_EVENT_INLINE_CHARS to a temp file, user messages included, and
kept a pointer in its place: "Action None completed. The output is too long
therefore is saved in ...". Once a session has synced, the router sends only the
stream's new events, so that pointer was all the model got of the request.

User messages now stay inline (KEEP_INLINE_EVENT_TYPES) when logged and through
both collapse paths; the context budget check decides whether they fit. These
drive the real ActionRouter and EventStream with an LLM that records what it is
sent.

See agent_core/core/impl/event_stream/event_stream.py and
agent_core/core/impl/action/router.py.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_core.core.event_stream.event import EventType
from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.action.router import ActionRouter
from agent_core.core.impl.llm.interface import LLMInterface
from agent_core.core.impl.event_stream.event_stream import (
    MAX_EVENT_INLINE_CHARS,
    EventStream,
)
from agent_core.core.impl.llm.interface import LLMContextOverflowError
from app import config as app_config
from app.agent_base import AgentBase
from app.models.factory import ModelFactory

MARKER = "END-OF-REQUEST-MARKER-7f3a"
# The size reported in #441, with a marker at the very end.
LONG = ("Context about our content operations and positioning. " * 500)[
    : 26_014 - len(MARKER)
] + MARKER
assert len(LONG) == 26_014
SESSION = "chat_441"


class _SummarizingLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        return "SUMMARY OF OLD EVENTS"


def _stream(tmp_path) -> EventStream:
    return EventStream(llm=_SummarizingLLM(), temp_dir=tmp_path / "events")


def _log_user(es: EventStream, text: str) -> None:
    # As AgentBase._log_deferred_user_messages logs it.
    es.log(
        "user message", text, event_type=EventType.USER_MESSAGE, display_message=text
    )


def _user_event(es: EventStream):
    return next(
        r for r in es.tail_events if r.event.event_type is EventType.USER_MESSAGE
    )


# --- Event stream -------------------------------------------------------------


def test_a_long_user_message_is_logged_intact(tmp_path):
    es = _stream(tmp_path)
    _log_user(es, LONG)

    rec = _user_event(es)
    assert rec.event.message == LONG
    assert rec.event.display_message == LONG
    events_dir = tmp_path / "events"
    assert not events_dir.exists() or not any(events_dir.iterdir())


def test_a_long_user_message_survives_collapsing_new_events(tmp_path):
    """The router's last resort when new events alone do not fit a request."""
    es = _stream(tmp_path)
    _log_user(es, LONG)

    assert es.collapse_undelivered_oversize() == 0
    assert _user_event(es).event.message == LONG


def test_a_long_user_message_survives_collapsing_delivered_events(tmp_path):
    """What a fold does to oversized events pinned in the tail it keeps."""
    es = _stream(tmp_path)
    _log_user(es, LONG)
    es.mark_delivered()

    with es._lock:
        assert es._collapse_oversize(list(es.tail_events)) == 0
    es.summarize_by_LLM(keep_tokens=10**6)

    assert _user_event(es).event.message == LONG


def test_large_action_output_is_still_moved_to_a_file(tmp_path):
    es = _stream(tmp_path)
    output = "row of tool output " * 2000
    es.log(
        "action_end", output, event_type=EventType.ACTION_END, action_name="run_shell"
    )

    message = es.tail_events[-1].event.message
    assert len(output) > MAX_EVENT_INLINE_CHARS
    assert message.startswith("Action run_shell completed. The output is too long")


def test_large_retrieval_output_is_still_collapsed_when_it_cannot_be_sent(tmp_path):
    """grep_files / read_file skip log-time externalization but not the last resort."""
    es = _stream(tmp_path)
    _log_user(es, LONG)
    es.log(
        "action_end",
        "matched line " * 3000,
        event_type=EventType.ACTION_END,
        action_name="read_file",
    )

    assert es.collapse_undelivered_oversize() > 0
    assert es.tail_events[-1].event.message.startswith("Action read_file completed.")
    assert _user_event(es).event.message == LONG


def test_short_user_messages_are_unchanged(tmp_path):
    es = _stream(tmp_path)
    _log_user(es, "  hello there  ")

    assert _user_event(es).event.message == "hello there"


# --- Router: what the model is sent -------------------------------------------

_DECISION = json.dumps(
    {"reasoning": "r", "actions": [{"action_name": "send_message", "parameters": {}}]}
)


class _RecordingLLM:
    """Records every user prompt the router sends; always answers one action.

    With ``window``, refuses a prompt longer than that many characters, as the
    budget check refuses one over the window in tokens."""

    def __init__(self, session_cache: bool = True, window: int | None = None):
        self.session_cache = session_cache
        self.window = window
        self.calls = 0
        self.prompts: list[str] = []

    def has_session_cache(self, task_id, call_type):
        return self.session_cache

    def fits_context(self, *args, **kwargs):
        return True

    def input_budget(self, *args, **kwargs):
        return self.window // 4 if self.window else 10**6

    def reset_session_history(self, *args):
        pass

    def checkpoint_session(self, *args):
        pass

    def _answer(self, user_prompt: str) -> str:
        self.calls += 1
        if self.window and len(user_prompt) > self.window:
            raise LLMContextOverflowError("Request does not fit the test window.")
        self.prompts.append(user_prompt)
        return _DECISION

    async def generate_response_with_session_async(
        self, task_id, call_type, user_prompt, system_prompt_for_new_session=None, **kw
    ):
        return self._answer(user_prompt)

    async def generate_response_async(self, system_prompt, user_prompt, **kw):
        return self._answer(user_prompt)


class _ContextEngine:
    """The stream accessors of the real ContextEngine, over one EventStream."""

    def __init__(self, stream: EventStream):
        self.stream = stream

    def get_session_state(self, session_id=None):
        return ""

    def make_prompt(self, user_flags=None, system_flags=None):
        return "SYSTEM PROMPT", None

    def get_event_stream(self, session_id=None):
        return self.stream.to_prompt_snapshot()

    def get_event_stream_delta(self, call_type, session_id=None):
        delta, has_delta = self.stream.get_delta_events(call_type)
        return (delta, True) if has_delta else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None):
        self.stream.mark_session_synced(call_type)

    def reset_event_stream_sync(self, call_type, session_id=None):
        self.stream.reset_session_sync(call_type)


def _router_over(es: EventStream, llm, monkeypatch) -> ActionRouter:
    """The real ActionRouter, deciding over ``es`` with ``llm``."""
    monkeypatch.setattr(
        router_module,
        "get_event_stream_manager",
        lambda: SimpleNamespace(get_stream_by_id=lambda sid: es),
    )
    router = ActionRouter(None, llm, _ContextEngine(es))
    router._get_session_compiled_actions = lambda session_id=None: []
    router._validate_parallel_actions = lambda actions, GUI_mode=False: actions
    return router


@pytest.fixture
def harness(tmp_path, monkeypatch):
    es = _stream(tmp_path)

    def build(session_cache: bool = True, llm=None):
        llm = llm or _RecordingLLM(session_cache)
        return _router_over(es, llm, monkeypatch), llm

    return es, build


def _turn(router: ActionRouter, query: str):
    return asyncio.run(router.select_action_in_session(query=query, session_id=SESSION))


def _query_for(text: str) -> str:
    """The trigger description AgentBase._handle_chat_message builds for ``text``:
    the {query} of the turn that answers it."""
    specs = []

    async def emit(spec):
        specs.append(spec)

    agent = AgentBase.__new__(AgentBase)
    agent.llm = SimpleNamespace(reset_failure_counter=lambda: None)
    agent.session_manager = SimpleNamespace(
        get=lambda sid: SimpleNamespace(agent_app_project_id=None, type=None, title="t")
    )
    agent.trigger_service = SimpleNamespace(emit=emit)
    asyncio.run(agent._handle_chat_message({"text": text, "session_id": SESSION}))
    return specs[0].description


def _user_turn(router, es, text):
    # As react() logs the message at claim time, then decides on its trigger.
    _log_user(es, text)
    return _turn(router, _query_for(text))


def test_a_new_chat_sends_the_whole_message(harness):
    es, build = harness
    router, llm = build()

    _user_turn(router, es, LONG)

    assert len(llm.prompts) == 1
    assert MARKER in llm.prompts[0]
    assert "Action None completed" not in llm.prompts[0]


def _real_llm_interface() -> LLMInterface:
    """A real LLMInterface on an OpenAI-compatible session path."""
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
    iface.create_session_cache(SESSION, "action_selection", "SYSTEM PROMPT")
    return iface


def _transport(sent: list):
    """Records each request's messages exactly as handed to the provider."""

    def generate_openai(self, system_prompt, user_prompt, messages_override=None, **kw):
        sent.append([dict(m) for m in messages_override])
        return {"content": _DECISION, "tokens_used": 1}

    return generate_openai


@pytest.mark.parametrize(
    ("message", "copies"),
    [
        # Restated in the query and quoted in the stream, as every message always was.
        ("short question " + MARKER, 2),
        # Quoted in the stream only: the query refers to it instead of repeating it.
        (LONG, 1),
    ],
    ids=["short", "long"],
)
def test_a_new_chats_request_to_the_provider_carries_the_message_once_when_long(
    harness, message, copies
):
    es, build = harness
    sent: list = []
    router, _ = build(llm=_real_llm_interface())
    settings = {
        "model": {"context_window": 128000},
        "context": {"keep_recent_tokens": 20000},
    }

    with (
        patch.object(app_config, "get_settings", return_value=settings),
        patch.object(LLMInterface, "_generate_openai", _transport(sent)),
    ):
        _user_turn(router, es, message)

    assert len(sent) == 1
    payload = "\n".join(str(m.get("content", "")) for m in sent[0])
    assert payload.count(MARKER) == copies
    assert "Action None completed" not in payload
    if copies == 1:
        assert "26,014 characters, quoted in full in the event stream above" in payload


def test_a_synced_chat_sends_the_new_message_once_and_nothing_older(harness):
    es, build = harness
    router, llm = build()
    _user_turn(router, es, "earlier question about pricing")
    es.log("agent message", "earlier answer", event_type=EventType.AGENT_MESSAGE)
    _turn(router, "Perform the next best action")

    _user_turn(router, es, LONG)

    delta = llm.prompts[-1]
    assert delta.count(MARKER) == 1
    assert "Action None completed" not in delta
    assert "earlier question about pricing" not in delta
    assert "earlier answer" not in delta


def test_a_continuation_turn_does_not_resend_a_delivered_message(harness):
    es, build = harness
    router, llm = build()
    _user_turn(router, es, LONG)
    es.log("action_end", "send_message -> ok", event_type=EventType.ACTION_END)

    _turn(router, "Perform the next best action based on the todos and event stream")

    assert MARKER not in llm.prompts[-1]
    assert "send_message -> ok" in llm.prompts[-1]


def test_a_continuation_without_a_session_cache_still_carries_the_message(harness):
    """Stateless providers re-send the whole stream every turn."""
    es, build = harness
    router, llm = build(session_cache=False)
    _user_turn(router, es, LONG)
    es.log("action_end", "send_message -> ok", event_type=EventType.ACTION_END)

    _turn(router, "Perform the next best action based on the todos and event stream")

    continuation = llm.prompts[-1]
    assert continuation.count(MARKER) == 1
    assert continuation.index(MARKER) < continuation.index("send_message -> ok")
