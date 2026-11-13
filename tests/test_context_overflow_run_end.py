# -*- coding: utf-8 -*-
"""
A request that cannot fit the model's context window ends the run (#441).

The router answers an overflow by folding the stream once and collapsing new
oversized events to pointers. If the request still does not fit, it raises
LLMContextOverflowError. The react loop used to show that as a red "critical"
error and queue another turn, which sends the same request again: nothing counts
those attempts (the budget check refuses before anything is sent, so neither
the LLM failure counter nor the action/token limits move). With user messages
kept inline, a message too large for the window would repeat that forever.

Now the session goes idle with one calm, actionable message carrying the token
counts, and no turn is queued. The advice follows the cause: a message the user
typed, one an integration delivered, or a conversation that has outgrown the
window. A sub-agent stops on its first overflow and reports why to its parent;
actions are unchanged.

See AgentBase._handle_react_error in app/agent_base.py.
"""

import asyncio
from types import SimpleNamespace

import pytest

from agent_core.core.event_stream.event import EventType
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.llm.interface import LLMContextOverflowError
from app.agent_base import AgentBase
from app.subagent.runner import SubAgentRunner
from tests.test_long_user_messages import (
    SESSION,
    _log_user,
    _RecordingLLM,
    _router_over,
    _stream,
    _user_turn,
)

OVERFLOW = (
    "Request of ~40213 input tokens exceeds the 28000-token budget "
    "(32000 window - 4000 reserved for output) for ollama/llama3."
)


class _Agent:
    """An AgentBase with only what _handle_react_error touches, recorded.

    ``unsent`` is what the session's stream reports setting aside, as
    (characters, tokens, platform); ``streams`` swaps in real EventStreams."""

    def __init__(
        self,
        streams: dict[str, EventStream] | None = None,
        unsent: list[tuple[int, int, str | None]] | None = None,
        budget: int | None = 28_000,
    ):
        self.agent = AgentBase.__new__(AgentBase)
        self.run_states: list[tuple[str, str]] = []
        self.triggers: list = []
        self.bubbles: list = []
        self.set_aside: list[str] = []
        streams = streams or {}

        async def emit(spec):
            self.triggers.append(spec)

        async def append_message(message):
            self.bubbles.append(message)

        def set_aside_for(sid):
            def set_aside_unsent_user_messages():
                self.set_aside.append(sid)
                return list(unsent or [])

            return set_aside_unsent_user_messages

        def get_stream_by_id(sid):
            if sid in streams:
                return streams[sid]
            return SimpleNamespace(set_aside_unsent_user_messages=set_aside_for(sid))

        def input_budget():
            if budget is None:
                raise RuntimeError("no model configured")
            return budget

        a = self.agent
        a.event_stream_manager = SimpleNamespace(
            log=lambda kind, message, **kw: None, get_stream_by_id=get_stream_by_id
        )
        a.state_manager = SimpleNamespace(bump_event_stream=lambda: None)
        a.trigger_service = SimpleNamespace(emit=emit)
        a.llm = SimpleNamespace(input_budget=input_budget)
        a.ui_controller = SimpleNamespace(
            active_adapter=SimpleNamespace(
                chat_component=SimpleNamespace(append_message=append_message)
            )
        )
        a._emit_run_state = lambda sid, state: self.run_states.append((sid, state))

    def handle(self, error: Exception, session_id: str = "chat_a") -> str:
        asyncio.run(self.agent._handle_react_error(error, session_id, {}))
        return self.bubbles[-1].content if self.bubbles else ""


def _assert_run_ended_once(agent: _Agent, session_id: str = "chat_a") -> None:
    assert agent.run_states == [(session_id, "idle")]
    assert agent.triggers == []  # nothing sends the same request again
    assert len(agent.bubbles) == 1
    assert agent.bubbles[0].style == "system"  # user-actionable, not a red crash
    assert [o.value for o in agent.bubbles[0].options] == ["open_settings_model"]
    assert agent.set_aside == [session_id]


@pytest.mark.parametrize(
    ("unsent", "says", "never_says"),
    [
        # A: the user typed a message too large for the model.
        (
            [(26_014, 20_000, None)],
            [
                "Your message (26,014 characters) is too large",
                "It was not processed",
                "Shorten it",
                # The budget check's own numbers, unchanged.
                "~40213 input tokens",
                "28000-token budget",
                "32000 window",
            ],
            ["This conversation"],
        ),
        # B: the oversized message arrived through an integration.
        (
            [(26_014, 20_000, "WhatsApp")],
            ["A message received from WhatsApp (26,014 characters)"],
            ["Shorten", "Your message"],
        ),
        # C: a continuation turn, nothing new from the user.
        (
            [],
            ["This conversation no longer fits", "Start a new chat"],
            ["Shorten", "not processed"],
        ),
        # D: history, not the short new message, is what does not fit.
        (
            [(42, 12, None)],
            [
                "This conversation no longer fits",
                "Your latest message was not processed; send it again.",
            ],
            ["Shorten"],
        ),
    ],
    ids=["typed-message", "integration-message", "continuation", "history"],
)
def test_the_advice_follows_what_did_not_fit(unsent, says, never_says):
    agent = _Agent(unsent=unsent)

    content = agent.handle(LLMContextOverflowError(OVERFLOW))

    _assert_run_ended_once(agent)
    for text in says:
        assert text in content
    for text in never_says:
        assert text not in content


def test_without_a_known_budget_the_message_size_decides():
    agent = _Agent(unsent=[(26_014, 20_000, None)], budget=None)

    assert "Your message (26,014 characters)" in agent.handle(
        LLMContextOverflowError(OVERFLOW)
    )


def test_an_overflow_under_another_exception_ends_the_run_too():
    agent = _Agent()
    try:
        try:
            raise LLMContextOverflowError(OVERFLOW)
        except LLMContextOverflowError as inner:
            raise RuntimeError("decision failed") from inner
    except RuntimeError as outer:
        agent.handle(outer)

    _assert_run_ended_once(agent)


def test_a_provider_size_rejection_without_counts_still_ends_the_run():
    agent = _Agent()

    content = agent.handle(
        LLMContextOverflowError("The prompt is too long for this model.")
    )

    _assert_run_ended_once(agent)
    assert "The prompt is too long for this model" in content


def test_repeated_overflows_never_queue_a_turn():
    """Each overflow is final for its run: nothing schedules the same request again."""
    agent = _Agent()

    for _ in range(3):
        agent.handle(LLMContextOverflowError(OVERFLOW))

    assert agent.triggers == []
    assert agent.run_states == [("chat_a", "idle")] * 3


def test_only_the_overflowing_session_is_stopped():
    agent = _Agent()

    agent.handle(LLMContextOverflowError(OVERFLOW), session_id="chat_b")

    _assert_run_ended_once(agent, "chat_b")
    assert {m.session_id for m in agent.bubbles} == {"chat_b"}


def test_other_turn_errors_still_continue_the_run():
    """Unchanged: a recoverable error is shown and the run goes on."""
    agent = _Agent()

    agent.handle(RuntimeError("Model failed"))

    assert agent.run_states == []
    assert len(agent.triggers) == 1
    assert agent.bubbles[0].style == "error"
    assert agent.set_aside == []


# --- The router gives up after one fold; the session recovers ---------------


def test_a_message_too_large_for_the_window_ends_the_run_and_the_next_one_gets_through(
    tmp_path, monkeypatch
):
    """Through the real router and stream: the overflow is raised after one fold,
    the handler ends the run once, and a shorter follow-up is answered."""
    es = _stream(tmp_path)
    llm = _RecordingLLM(window=20_000)
    router = _router_over(es, llm, monkeypatch)
    too_long = "x" * 29_990 + "TAIL-MARK"

    with pytest.raises(LLMContextOverflowError) as raised:
        _user_turn(router, es, too_long)
    assert llm.calls == 2  # the request, then once more after the fold

    agent = _Agent(streams={SESSION: es}, budget=llm.input_budget())
    content = agent.handle(raised.value, session_id=SESSION)
    assert agent.triggers == []
    assert agent.run_states == [(SESSION, "idle")]
    assert "Your message (29,999 characters) is too large" in content

    _user_turn(router, es, "Here is a shorter version of my request.")

    follow_up = llm.prompts[-1]
    assert "Here is a shorter version of my request." in follow_up
    assert "TAIL-MARK" not in follow_up
    assert "[Not processed: this message (29999 characters)" in follow_up


def test_only_unsent_user_messages_are_set_aside(tmp_path):
    es = _stream(tmp_path)
    _log_user(es, "an earlier question")
    es.mark_delivered()
    too_long = "y" * 30_000
    _log_user(es, too_long)
    es.log("action_end", "small tool result", event_type=EventType.ACTION_END)
    es.log(
        "user message from platform: WhatsApp",
        "a forwarded note",
        event_type=EventType.USER_MESSAGE,
    )

    reported = es.set_aside_unsent_user_messages()

    assert [(chars, platform) for chars, _, platform in reported] == [
        (30_000, None),
        (16, "WhatsApp"),
    ]
    assert all(tokens > 0 for _, tokens, _ in reported)
    earlier, set_aside, tool, _ = es.tail_events[-4:]
    assert earlier.event.message == "an earlier question"
    assert tool.event.message == "small tool result"
    assert set_aside.event.message.startswith(
        "[Not processed: this message (30000 characters) did not fit"
    )
    assert set_aside.event.display_message == too_long  # the chat bubble is unchanged
    saved = set_aside.event.message.split("saved in ", 1)[1].rstrip(".]")
    assert open(saved, encoding="utf-8").read() == too_long


# --- Sub-agents: stop on the first overflow and tell their parent why ---------


def test_a_subagent_overflow_ends_that_subagent_as_failed(monkeypatch):
    ended: list[tuple[str, str, str]] = []
    logged: list[str] = []
    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner.subagent_manager = SimpleNamespace(
        end=lambda sid, status, result: ended.append((sid, status, result))
    )
    runner.event_stream_manager = SimpleNamespace(
        get_stream_by_id=lambda sid: SimpleNamespace(
            mark_session_synced=lambda c: None
        ),
        log=lambda kind, message, **kw: logged.append(message),
    )
    runner.context_engine = SimpleNamespace(make_system_prompt=lambda sub: "SYSTEM")
    runner._build_user_prompt = lambda sub, stream: ("prompt", True)
    attempts = 0

    async def invoke(sub, user_prompt, system_prompt):
        nonlocal attempts
        attempts += 1
        raise LLMContextOverflowError(OVERFLOW)

    runner._invoke_llm = invoke
    sub = SimpleNamespace(id="sub_1", iterations=1)

    asyncio.run(runner._run_one_step_safely(sub))

    assert attempts == 1  # the same request cannot fit on a second try either
    assert [(sid, status) for sid, status, _ in ended] == [("sub_1", "failed")]
    result = ended[0][2]  # the parent reads why
    assert "does not fit the model's context window" in result
    assert "~40213 input tokens" in result
    assert "parseable" not in result
