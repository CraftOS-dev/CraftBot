# -*- coding: utf-8 -*-
"""Bedrock usage extraction must match the Anthropic shape.

Bedrock's Converse API reports `inputTokens` EXCLUSIVE of cache activity,
while the Anthropic API path reassembles input as base + creation + read.
The display layer (dashboard, /tokens) assumes `cached` is a subset of
`input` for every provider, so the Bedrock paths normalize:
input = inputTokens + cacheRead + cacheWrite, cached = cacheRead only.
"""

from typing import Any, Dict

from agent_core.core.impl.llm.interface import LLMInterface
from agent_core.core.impl.vlm.interface import VLMInterface


BEDROCK_USAGE = {
    "inputTokens": 100,  # new tokens only — AWS excludes cache activity
    "outputTokens": 50,
    "cacheReadInputTokens": 900,
    "cacheWriteInputTokens": 30,
}


class _StubBedrockClient:
    def converse(self, **kwargs) -> Dict[str, Any]:
        return {
            "output": {"message": {"content": [{"text": "hello"}]}},
            "usage": dict(BEDROCK_USAGE),
        }


def _stub_common(iface) -> Dict[str, Any]:
    """Set the attributes the bedrock call paths touch; capture usage reports."""
    reported = {}

    def _capture(
        call_kind, provider, model, input_tokens, output_tokens, cached, *a, **kw
    ):
        reported.update(input=input_tokens, output=output_tokens, cached=cached)

    iface._bedrock_client = _StubBedrockClient()
    iface.model = "anthropic.claude-3-5-sonnet-20241022-v2:0"  # caching-capable
    iface.provider = "bedrock"
    iface.temperature = 0.0
    iface.max_tokens = 1024
    iface._report_usage_async = _capture
    return reported


def test_llm_bedrock_input_includes_cache_and_cached_is_reads_only():
    iface = LLMInterface.__new__(LLMInterface)
    reported = _stub_common(iface)
    iface._call_log_to_db = lambda *a, **kw: None

    result = iface._generate_bedrock(None, "hi")

    assert "error" not in result
    # input = 100 + 900 + 30, the full prompt; cached = reads only
    assert reported == {"input": 1030, "output": 50, "cached": 900}
    assert result["cached_tokens"] == 900
    assert result["tokens_used"] == 1080  # 1030 + 50
    # the display invariant the dashboard and /tokens rely on
    assert reported["cached"] <= reported["input"]


def test_vlm_bedrock_input_includes_cache_and_cached_is_reads_only():
    iface = VLMInterface.__new__(VLMInterface)
    reported = _stub_common(iface)

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    result = iface._bedrock_describe_bytes(png, None, "describe")

    assert reported == {"input": 1030, "output": 50, "cached": 900}
    assert result["cached_tokens"] == 900
    assert result["tokens_used"] == 1080
    assert reported["cached"] <= reported["input"]
