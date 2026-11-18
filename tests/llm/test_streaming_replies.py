# -*- coding: utf-8 -*-
"""Streaming decision replies.

Streaming may change only how a reply is delivered:

* a streamed call sends the same request (plus the transport's stream
  fields), reads the same usage, and records the same session history as an
  unstreamed one, so the provider's cached prefix is untouched;
* the sink gets the reply's text as it arrives, and a stopped reply raises
  LLMStreamAborted without joining the history or counting as a failure;
* the reply parser finds the reasoning and each action the moment its
  object closes, and ReplyStream starts the actions that may run alongside
  others while the reply is still being written;
* a reply whose actions already started is never asked for again.
"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.action.reply_stream import ReplyParser, ReplyStream
from agent_core.core.impl.llm.streaming import (
    LLMStreamAborted,
    StreamRestarted,
    StreamSink,
    current_sink,
    streaming_to,
)

from .golden.conftest import GOLDEN_SYSTEM_PROMPT

TASK = "task-stream"
CALL = "action_selection"


def _chunks(text: str, size: int = 7) -> List[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


class _Collect(StreamSink):
    def __init__(self, cancel_after: int = 0) -> None:
        self.cancelled = False
        self.parts: List[str] = []
        self.begins = 0
        self._cancel_after = cancel_after

    def on_begin(self) -> None:
        self.begins += 1

    def on_text(self, delta: str) -> None:
        self.parts.append(delta)
        if self._cancel_after and len(self.parts) >= self._cancel_after:
            self.cancelled = True


# ─────────────────── streaming fakes (both modes, same text) ───────────────────


def _reply(turn: int) -> str:
    return json.dumps(
        {
            "reasoning": f"turn {turn} \u00e9 \"q\"",
            "actions": [{"action_name": "end_turn", "parameters": {}}],
        }
    )


class _OpenAI:
    def __init__(self) -> None:
        self.payloads: List[Dict[str, Any]] = []
        self.turn = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.turn += 1
        text = _reply(self.turn)
        usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            prompt_tokens_details=SimpleNamespace(cached_tokens=60),
        )
        stream = kwargs.pop("stream", False)
        options = kwargs.pop("stream_options", None)
        self.payloads.append(copy.deepcopy(kwargs))
        if not stream:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=text), finish_reason="stop"
                    )
                ],
                usage=usage,
            )
        assert options == {"include_usage": True}
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        index=0,
                        delta=SimpleNamespace(content=piece),
                        finish_reason=None,
                    )
                ],
                usage=None,
            )
            for piece in _chunks(text)
        ]
        chunks.append(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        index=0, delta=SimpleNamespace(content=None), finish_reason="stop"
                    )
                ],
                usage=None,
            )
        )
        chunks.append(SimpleNamespace(choices=[], usage=usage))
        return iter(chunks)


class _Anthropic:
    def __init__(self) -> None:
        self.payloads: List[Dict[str, Any]] = []
        self.turn = 0
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)

    def _message(self):
        self.turn += 1
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=_reply(self.turn))],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=40,
                output_tokens=10,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=60,
            ),
        )

    def _create(self, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs))
        return self._message()

    def _stream(self, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs))
        message = self._message()
        events = [
            SimpleNamespace(type="text", text=piece)
            for piece in _chunks(message.content[0].text)
        ]

        class _Manager:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def __iter__(self_inner):
                return iter(events)

            def get_final_message(self_inner):
                return message

        return _Manager()


class _Bedrock:
    def __init__(self) -> None:
        self.payloads: List[Dict[str, Any]] = []
        self.turn = 0

    def converse(self, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs))
        self.turn += 1
        return {
            "output": {"message": {"content": [{"text": _reply(self.turn)}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 40, "outputTokens": 10, "cacheReadInputTokens": 60},
        }

    def converse_stream(self, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs))
        self.turn += 1
        events = [{"messageStart": {"role": "assistant"}}]
        events += [
            {"contentBlockDelta": {"delta": {"text": piece}, "contentBlockIndex": 0}}
            for piece in _chunks(_reply(self.turn))
        ]
        events += [
            {"messageStop": {"stopReason": "end_turn"}},
            {
                "metadata": {
                    "usage": {
                        "inputTokens": 40,
                        "outputTokens": 10,
                        "cacheReadInputTokens": 60,
                    }
                }
            },
        ]
        return {"stream": iter(events)}


class _GeminiHTTP:
    """Stands in for the requests module the Gemini client posts with."""

    def __init__(self) -> None:
        self.payloads: List[Dict[str, Any]] = []
        self.turn = 0

    def post(self, url, headers=None, json=None, timeout=None, params=None, stream=False):  # noqa: A002
        self.payloads.append({"url": url.split(":")[-1], "body": copy.deepcopy(json)})
        self.turn += 1
        text = _reply(self.turn)
        usage = {
            "totalTokenCount": 110,
            "promptTokenCount": 100,
            "candidatesTokenCount": 10,
            "cachedContentTokenCount": 60,
        }
        if not stream:
            body = {
                "candidates": [
                    {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": usage,
            }
            return SimpleNamespace(ok=True, raise_for_status=lambda: None, json=lambda: body)
        assert params == {"alt": "sse"}
        pieces = _chunks(text)
        lines = []
        for i, piece in enumerate(pieces):
            chunk = {"candidates": [{"content": {"parts": [{"text": piece}]}}]}
            if i == len(pieces) - 1:
                chunk["candidates"][0]["finishReason"] = "STOP"
                chunk["usageMetadata"] = usage
            lines += ["data: " + __import__("json").dumps(chunk), ""]
        return SimpleNamespace(
            ok=True,
            raise_for_status=lambda: None,
            iter_lines=lambda decode_unicode=True: iter(lines),
            close=lambda: None,
        )


def _interface(monkeypatch, provider: str):
    """An LLMInterface for ``provider`` over a fake that serves both modes."""
    from agent_core.core.models.factory import ModelFactory
    import agent_core.core.impl.llm.interface as interface_mod

    ctx: Dict[str, Any] = {
        "provider": provider,
        "model": {"openai": "gpt-5.2", "anthropic": "claude-sonnet-4-6",
                  "bedrock": "us.anthropic.claude-sonnet-4-6", "gemini": "gemini-2.5-pro"}[provider],
        "client": None,
        "gemini_client": None,
        "anthropic_client": None,
        "bedrock_client": None,
        "remote_url": None,
        "byteplus": None,
        "initialized": True,
        "auth_mode": "api_key",
    }
    if provider == "openai":
        fake = ctx["client"] = _OpenAI()
    elif provider == "anthropic":
        fake = ctx["anthropic_client"] = _Anthropic()
    elif provider == "bedrock":
        fake = ctx["bedrock_client"] = _Bedrock()
    else:
        from agent_core.core.llm import google_gemini_client as gemini_mod

        fake = _GeminiHTTP()
        monkeypatch.setattr(gemini_mod, "requests", fake)
        ctx["gemini_client"] = gemini_mod.GeminiClient(api_key="k")
    monkeypatch.setattr(ModelFactory, "create", staticmethod(lambda **kw: dict(ctx)))
    iface = interface_mod.LLMInterface(provider=provider, model=ctx["model"])
    iface.create_session_cache(TASK, CALL, GOLDEN_SYSTEM_PROMPT)
    return iface, fake


def _three_turns(iface, sink=None) -> List[str]:
    replies = []
    for i in range(1, 4):
        with streaming_to(sink):
            replies.append(
                iface.generate_response_with_session(TASK, CALL, f"turn {i} events")
            )
    return replies


@pytest.mark.parametrize("provider", ["openai", "anthropic", "bedrock", "gemini"])
def test_a_streamed_session_sends_and_keeps_exactly_what_an_unstreamed_one_does(
    monkeypatch, provider
):
    plain, plain_fake = _interface(monkeypatch, provider)
    plain_replies = _three_turns(plain)

    streamed, streamed_fake = _interface(monkeypatch, provider)
    sink = _Collect()
    streamed_replies = _three_turns(streamed, sink)

    # The same requests (Gemini: the same body, to streamGenerateContent).
    if provider == "gemini":
        assert [p["body"] for p in streamed_fake.payloads] == [
            p["body"] for p in plain_fake.payloads
        ]
        assert {p["url"] for p in streamed_fake.payloads} == {"streamGenerateContent"}
    else:
        assert streamed_fake.payloads == plain_fake.payloads
    # The same replies and the same session history: the cached prefix of
    # every following request is the one the unstreamed session builds.
    assert streamed_replies == plain_replies
    assert streamed._session_histories == plain._session_histories
    # The same usage (the cache readout and the fold budget read it).
    assert streamed.last_request(TASK, CALL).cached_tokens == plain.last_request(
        TASK, CALL
    ).cached_tokens > 0
    assert streamed.last_input_tokens(TASK, CALL) == plain.last_input_tokens(TASK, CALL)
    # The sink saw every reply as it streamed.
    assert "".join(sink.parts) == "".join(plain_replies)
    assert sink.begins == 3


def test_the_chatgpt_subscription_stream_hands_its_text_to_the_sink():
    from agent_core.core.models.chatgpt_subscription_client import _consume_stream

    events = [SimpleNamespace(type="response.output_text.delta", delta=p) for p in ("{\"a\"", ": 1}")]
    events.append(SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None)))
    sink = _Collect()
    with streaming_to(sink):
        bundle = _consume_stream(iter(events))
    assert bundle["text"] == '{"a": 1}' == "".join(sink.parts)
    assert sink.begins == 1


def test_the_claude_code_partial_lines_carry_the_reply_text():
    from agent_core.core.models.claude_code_client import _text_delta

    line = {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}},
    }
    thinking = {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "x"}},
    }
    assert _text_delta(line) == "hi"
    assert _text_delta(thinking) == "" and _text_delta({"type": "result"}) == ""


def test_a_stopped_reply_joins_no_history_and_is_no_provider_failure(monkeypatch):
    iface, _ = _interface(monkeypatch, "openai")
    _three_turns(iface)
    before = copy.deepcopy(iface._session_histories)

    sink = _Collect(cancel_after=2)
    with pytest.raises(LLMStreamAborted):
        with streaming_to(sink):
            iface.generate_response_with_session(TASK, CALL, "stopped turn")
    assert iface._session_histories == before
    assert iface.consecutive_failures == 0
    assert not iface.session_turn_recorded(TASK, CALL)


def test_a_second_request_for_a_reply_already_acted_on_is_refused():
    stream_attempt = _attempt()
    stream_attempt._begin()
    stream_attempt._work_started = True
    with pytest.raises(StreamRestarted):
        stream_attempt._begin()


def test_a_retry_inside_the_call_replaces_the_text_so_far():
    attempt = _attempt()
    attempt._begin()
    attempt._feed('{"reasoning": "first')
    attempt._begin()
    attempt._feed('{"reasoning": "second"}')
    assert attempt.parser.reasoning() == "second"


def _attempt():
    async def make():
        return ReplyStream(session_id="s").begin_attempt()

    return asyncio.run(make())


# ─────────────────────────── the reply parser ───────────────────────────

REPLY = json.dumps(
    {
        "reasoning": "Check two things, then answer. Braces { } and \"quotes\" stay text.",
        "actions": [
            {"action_name": "web_search", "parameters": {"query": "a {b}"}},
            {"action_name": "read_file", "parameters": {"file_path": "C:\\x\\y.md"}},
            {"action_name": "send_message", "parameters": {"message": "Line 1\nLine 2 \u00e9 \ud83d\ude00"}},
        ],
    }
)


def test_the_parser_finds_each_action_the_moment_its_object_closes():
    parser = ReplyParser()
    closed_at = {}
    for i, ch in enumerate(REPLY):
        for index in parser.feed(ch):
            closed_at[index] = i
    expected = json.loads(REPLY)
    assert [r.obj for r in parser.actions] == expected["actions"]
    # Each closes on its own closing brace, before the reply ends.
    for index, at in closed_at.items():
        assert REPLY[at] == "}"
    assert closed_at[0] < closed_at[1] < closed_at[2] < len(REPLY) - 1
    assert parser.reasoning() == expected["reasoning"] and parser.closed


def test_the_partial_view_grows_with_the_reply():
    parser = ReplyParser()
    seen_messages = []
    for ch in REPLY:
        parser.feed(ch)
        if len(parser.actions) == 3:
            view = parser.action_view(parser.actions[2])
            seen_messages.append(view["params"].get("message", ""))
    final = json.loads(REPLY)["actions"][2]["parameters"]["message"]
    assert seen_messages[-1] == final
    # Never shrinks: each partial is a prefix of the final text.
    assert all(final.startswith(m) for m in seen_messages)


def test_the_parser_skips_a_fence_and_think_block_and_stops_at_the_first_object():
    parser = ReplyParser()
    text = (
        '<think>plan {"not": "this"}</think>```json\n'
        + REPLY
        + '\n```{"reasoning": "chained", "actions": [{"action_name": "x", "parameters": {}}]}'
    )
    for piece in _chunks(text, 5):
        parser.feed(piece)
    assert [r.obj["action_name"] for r in parser.actions] == [
        "web_search",
        "read_file",
        "send_message",
    ]


# ─────────────────────────── early starts ───────────────────────────


def _reply_stream(classify, started, published, logged):
    def start(decision):
        started.append(decision)

        async def run():
            return {"status": "success"}

        return asyncio.ensure_future(run())

    return ReplyStream(
        session_id="s",
        publish=published.append,
        start_action=start,
        classify=classify,
        log_reasoning=lambda text, item: logged.append((text, item)),
    )


def _feed_in_thread(attempt, text):
    for piece in _chunks(text, 3):
        attempt.sink.on_text(piece)


def test_complete_actions_start_while_the_reply_is_still_being_written():
    async def go():
        started, published, logged = [], [], []
        stream = _reply_stream(lambda a: "run", started, published, logged)
        attempt = stream.begin_attempt()
        cut = REPLY.index('{"action_name": "send_message"')
        await asyncio.to_thread(_feed_in_thread, attempt, REPLY[:cut])
        await asyncio.sleep(0.2)
        names_mid_reply = [d["action_name"] for d in started]
        await asyncio.to_thread(_feed_in_thread, attempt, REPLY[cut:])
        await asyncio.sleep(0.2)
        return stream, attempt, started, published, logged, names_mid_reply

    stream, attempt, started, published, logged, mid = asyncio.run(go())
    assert mid == ["web_search", "read_file"]
    assert [d["action_name"] for d in started] == ["web_search", "read_file", "send_message"]
    assert all(d["_run_id"] == attempt.run_id_for(i) for i, d in enumerate(started))
    # The reasoning is recorded once, before the first action, with its row id.
    assert logged == [(json.loads(REPLY)["reasoning"], attempt.reasoning_id)]
    assert stream.reasoning_logged and attempt.has_started
    update = [p for p in published if p["phase"] == "update"][-1]
    assert update["reasoning"]["done"] is True
    assert [a["name"] for a in update["actions"]] == ["web_search", "read_file"]
    assert update["messages"][0]["text"].startswith("Line 1\nLine 2")


def test_an_action_that_must_run_alone_stops_early_starts():
    kinds = {"web_search": "block", "read_file": "run", "send_message": "run"}

    async def go():
        started, published, logged = [], [], []
        stream = _reply_stream(lambda a: kinds[a["action_name"]], started, published, logged)
        attempt = stream.begin_attempt()
        await asyncio.to_thread(_feed_in_thread, attempt, REPLY)
        await asyncio.sleep(0.2)
        return started

    assert asyncio.run(go()) == []


def test_a_stopped_turn_ends_the_reply_and_cancels_what_it_started():
    async def go():
        started, published, logged = [], [], []
        stream = _reply_stream(lambda a: "run", started, published, logged)
        attempt = stream.begin_attempt()
        await asyncio.to_thread(_feed_in_thread, attempt, REPLY[: REPLY.index('{"action_name": "read_file"')])
        await asyncio.sleep(0.1)
        await stream.abort(cancel_actions=True)
        return attempt, published

    attempt, published = asyncio.run(go())
    assert attempt.sink.cancelled
    assert published[-1]["phase"] == "end"
    assert published[-1]["keep"] == [attempt.run_id_for(0)]


# ─────────────────────────── the router ───────────────────────────


class _Stream:
    synced = False

    def has_session_sync(self, call_type):
        return self.synced

    def sync_marker(self, call_type):
        return None

    def get_event_count(self):
        return 0

    def set_reply_in_history(self, call_type, decision):
        self.reply = decision

    def unsynced_reason(self, call_type):
        return "first"

    def mark_delivered(self, *args):
        pass


class _Context:
    def make_prompt(self, **kwargs):
        return "BASE", ""

    def get_session_state(self, session_id=None):
        return "S"

    def get_event_stream(self, session_id=None, up_to=None):
        return "E"

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        pass

    def reset_event_stream_sync(self, call_type, session_id=None, reason="reset"):
        pass


class _StreamingLLM:
    """Streams each reply to the call's sink (as a transport does), then
    returns it or raises."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

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

    async def generate_response_with_session_async(self, task_id, call_type, user_prompt, system_prompt_for_new_session, prompt_name=None, call_metadata=None):
        self.calls += 1
        text, error = self.replies.pop(0)
        sink = current_sink()
        if sink is not None:
            sink.on_begin()
            for piece in _chunks(text, 4):
                sink.on_text(piece)
        await asyncio.sleep(0.05)  # the loop runs the stream's callbacks
        if error is not None:
            raise error
        return text


def _router(monkeypatch, llm, library_kinds):
    stream = _Stream()
    manager = SimpleNamespace(get_stream_by_id=lambda session_id: stream)
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: manager)
    library = SimpleNamespace(
        retrieve_action=lambda name: SimpleNamespace(
            name=name, parallelizable=library_kinds.get(name, True), mode="ALL"
        )
    )
    router = router_module.ActionRouter(library, llm, _Context())
    monkeypatch.setattr(router, "_decision_inputs", lambda session_id: ("S", "INSTR"))
    return router, stream


def _select(router, started):
    async def go():
        def start(decision):
            started.append(decision["action_name"])

            async def run():
                return {"status": "success"}

            return asyncio.ensure_future(run())

        reply_stream = ReplyStream(
            session_id="s1",
            start_action=start,
            classify=router.early_start_kind,
        )
        decisions = await router.select_action_in_session("q", session_id="s1", reply_stream=reply_stream)
        return decisions, reply_stream

    return asyncio.run(go())


CUT_OFF = REPLY[: REPLY.index('{"action_name": "send_message"')]


def test_a_reply_cut_off_after_its_actions_started_is_not_asked_again(monkeypatch):
    llm = _StreamingLLM([(CUT_OFF, None)])
    router, stream = _router(monkeypatch, llm, {})
    started = []
    decisions, reply_stream = _select(router, started)

    assert llm.calls == 1  # no retry: it would run them a second time
    assert started == ["web_search", "read_file"]
    assert [d["action_name"] for d in decisions] == ["web_search", "read_file"]
    assert all(d["_started"] and d["_run_id"] for d in decisions)
    assert reply_stream.started_tasks(decisions) and len(reply_stream.started_tasks(decisions)) == 2


def test_a_provider_error_after_actions_started_keeps_them(monkeypatch):
    llm = _StreamingLLM([(CUT_OFF, RuntimeError("connection reset"))])
    router, _ = _router(monkeypatch, llm, {})
    started = []
    decisions, _ = _select(router, started)
    assert llm.calls == 1
    assert [d["action_name"] for d in decisions] == ["web_search", "read_file"]


def test_a_must_run_alone_action_after_started_ones_is_dropped_with_a_reason(monkeypatch):
    reply = json.dumps(
        {
            "reasoning": "r",
            "actions": [
                {"action_name": "web_search", "parameters": {"query": "x"}},
                {"action_name": "wait", "parameters": {"seconds": 5}},
            ],
        }
    )
    llm = _StreamingLLM([(reply, None)])
    router, _ = _router(monkeypatch, llm, {"wait": False})
    started = []
    decisions, _ = _select(router, started)
    assert started == ["web_search"]
    ran, dropped = decisions
    assert ran["_started"] and "_error" not in ran
    assert dropped["action_name"] == "wait" and "already started" in dropped["_error"]
    assert dropped["_run_id"]


def test_without_early_starts_the_batch_is_validated_as_before(monkeypatch):
    reply = json.dumps(
        {
            "reasoning": "r",
            "actions": [
                {"action_name": "wait", "parameters": {}},
                {"action_name": "web_search", "parameters": {"query": "x"}},
            ],
        }
    )
    llm = _StreamingLLM([(reply, None)])
    router, _ = _router(monkeypatch, llm, {"wait": False})
    started = []
    decisions, _ = _select(router, started)
    assert started == []  # "wait" came first and must run alone
    kept = [d for d in decisions if "_error" not in d]
    assert [d["action_name"] for d in kept] == ["wait"]
    assert all(d.get("_run_id") for d in decisions)
