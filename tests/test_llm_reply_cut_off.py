# -*- coding: utf-8 -*-
"""A reply the provider cut off at the output limit is reported as cut off.

Every transport reads its provider's stop reason into the result's
``cut_off``, and the interface hands it on with the reply text (LLMReply),
so the action router can warn the agent through its event stream.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_core.core.impl.llm.interface import LLMInterface, LLMReply
from agent_core.core.impl.llm.transports import (
    anthropic_messages,
    bedrock_converse,
    byteplus_responses,
    chat_completions,
)
from agent_core.core.llm.google_gemini_client import GeminiClient


def _iface(provider, **clients):
    return SimpleNamespace(
        provider=provider,
        model="m",
        temperature=0.0,
        max_tokens=8000,
        _call_log_to_db=lambda *args, **kwargs: None,
        _report_usage_async=lambda *args, **kwargs: None,
        _bedrock_model_supports_caching=lambda: False,
        **clients,
    )


def _openai(finish_reason):
    choice = SimpleNamespace(
        message=SimpleNamespace(content='{"a": 1}'), finish_reason=finish_reason
    )
    usage = SimpleNamespace(
        prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None
    )
    create = lambda **kwargs: SimpleNamespace(choices=[choice], usage=usage)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return chat_completions.generate_openai(
        _iface("openai", client=client), None, "u", reasoning=None
    )


def _anthropic(stop_reason):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text='{"a": 1}')],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response))
    return anthropic_messages.generate(
        _iface("anthropic", _anthropic_client=client), None, "u", reasoning=None
    )


def _bedrock(stop_reason):
    response = {
        "output": {"message": {"content": [{"text": '{"a": 1}'}]}},
        "stopReason": stop_reason,
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }
    client = SimpleNamespace(converse=lambda **kwargs: response)
    return bedrock_converse.generate(
        _iface("bedrock", _bedrock_client=client), None, "u", reasoning=None
    )


@pytest.mark.parametrize(
    "call, limit, finished",
    [
        (_openai, "length", "stop"),
        (_anthropic, "max_tokens", "end_turn"),
        (_bedrock, "max_tokens", "end_turn"),
    ],
)
def test_transports_report_a_reply_stopped_at_the_output_limit(call, limit, finished):
    assert call(limit)["cut_off"] is True
    assert call(finished)["cut_off"] is False


def test_a_chat_completion_without_a_finish_reason_is_not_cut_off():
    assert _openai(None)["cut_off"] is False


def test_gemini_reports_max_tokens():
    assert GeminiClient._cut_off({"candidates": [{"finishReason": "MAX_TOKENS"}]})
    assert not GeminiClient._cut_off({"candidates": [{"finishReason": "STOP"}]})
    assert not GeminiClient._cut_off({})


@pytest.mark.parametrize(
    "result, cut_off",
    [
        (
            {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
            True,
        ),
        (
            {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}},
            False,
        ),
        ({"status": "completed"}, False),
        ({"choices": [{"finish_reason": "length"}]}, True),
        ({"choices": [{"finish_reason": "stop"}]}, False),
    ],
)
def test_byteplus_reports_both_response_shapes(result, cut_off):
    assert byteplus_responses._byteplus_cut_off(result) is cut_off


@pytest.mark.parametrize("cut_off", [True, False])
def test_the_interface_hands_the_flag_on_with_the_reply(cut_off):
    llm = LLMInterface(provider="openai", model="m", deferred=True)
    reply = llm._finalize_session_response(
        {"content": '{"a": 1}', "cut_off": cut_off}, log_response=False
    )
    assert isinstance(reply, LLMReply)
    assert reply == '{"a": 1}' and reply.cut_off is cut_off
