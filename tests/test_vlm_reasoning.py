# -*- coding: utf-8 -*-
"""Vision requests follow each model's reasoning rule.

The VLM paths send no reasoning parameter (the provider's default applies),
but a model's rule in agent_core/core/models/reasoning.py still decides
whether the request may carry a temperature and how much output room it
needs. Claude Sonnet 5.5 rejects a non-default temperature and always
thinks, so its requests drop the temperature and get the reasoning output
cap; a model without a rule keeps the request it always had.
"""

from types import SimpleNamespace
from typing import Any, Dict

import pytest

from agent_core.core.impl.vlm.interface import VLMInterface

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _Capture:
    """Records the keyword arguments of the one call it receives."""

    def __init__(self, response: Any) -> None:
        self.kwargs: Dict[str, Any] = {}
        self._response = response

    def __call__(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self._response


def _iface(provider: str, model: str) -> VLMInterface:
    iface = VLMInterface.__new__(VLMInterface)
    iface.provider = provider
    iface.model = model
    iface.temperature = 0.5
    iface._report_usage_async = lambda *a, **kw: None
    return iface


def _anthropic(provider: str, model: str):
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    create = _Capture(
        SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], usage=usage)
    )
    iface = _iface(provider, model)
    iface._anthropic_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    iface._anthropic_describe_bytes(PNG, None, "describe")
    return create.kwargs


def _bedrock(model: str):
    converse = _Capture(
        {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }
    )
    iface = _iface("bedrock", model)
    iface._bedrock_client = SimpleNamespace(converse=converse)
    iface._bedrock_describe_bytes(PNG, None, "describe")
    return converse.kwargs


def _chat(provider: str, model: str):
    create = _Capture(
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None
            ),
        )
    )
    iface = _iface(provider, model)
    iface.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    iface._openai_describe_bytes(PNG, None, "describe")
    return create.kwargs


def test_anthropic_model_without_a_rule_keeps_its_request():
    kwargs = _anthropic("anthropic", "claude-3-5-sonnet-20241022")
    assert kwargs["max_tokens"] == 2048
    assert kwargs["extra_body"] == {"temperature": 0.5}
    assert "thinking" not in kwargs and "output_config" not in kwargs


def test_anthropic_sonnet_55_drops_temperature_and_gets_reasoning_room():
    kwargs = _anthropic("anthropic", "claude-sonnet-5-5")
    assert "extra_body" not in kwargs
    assert kwargs["max_tokens"] > 2048
    # Provider default: no reasoning parameter is sent.
    assert "thinking" not in kwargs and "output_config" not in kwargs


def test_anthropic_model_that_does_not_think_by_default_keeps_temperature():
    kwargs = _anthropic("anthropic", "claude-sonnet-4-6")
    assert kwargs["max_tokens"] == 2048
    assert kwargs["extra_body"] == {"temperature": 0.5}


@pytest.mark.parametrize(
    "model", ["us.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-5-5"]
)
def test_bedrock_sonnet_55_drops_temperature_and_gets_reasoning_room(model):
    kwargs = _bedrock(model)
    assert "temperature" not in kwargs["inferenceConfig"]
    assert kwargs["inferenceConfig"]["maxTokens"] > 2048
    assert "additionalModelRequestFields" not in kwargs


def test_bedrock_model_without_a_rule_keeps_its_request():
    kwargs = _bedrock("anthropic.claude-3-5-sonnet-20241022-v2:0")
    assert kwargs["inferenceConfig"] == {"maxTokens": 2048, "temperature": 0.5}
    assert "additionalModelRequestFields" not in kwargs


def test_openrouter_sonnet_55_drops_temperature_and_gets_reasoning_room():
    kwargs = _chat("openrouter", "anthropic/claude-sonnet-5.5")
    assert "temperature" not in kwargs
    assert kwargs["max_tokens"] > 2048
    assert "extra_body" not in kwargs


def test_chat_model_without_a_rule_keeps_its_request():
    kwargs = _chat("together", "deepseek-ai/DeepSeek-V4.1-Flash")
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 2048


def test_chat_reasoning_cap_uses_the_profile_field_name():
    # gpt-oss reasons by default (cap 32000, under Groq's 32768 limit), and
    # Groq takes max_completion_tokens.
    kwargs = _chat("groq", "openai/gpt-oss-120b")
    assert kwargs["max_completion_tokens"] == 32000
    assert "max_tokens" not in kwargs
