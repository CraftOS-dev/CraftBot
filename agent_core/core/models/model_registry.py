# -*- coding: utf-8 -*-
"""Model registry mapping providers to default models."""

from agent_core.core.models.types import InterfaceType

MODEL_REGISTRY = {
    "openai": {
        InterfaceType.LLM: "gpt-5.2-2025-12-11",
        InterfaceType.VLM: "gpt-5.2-2025-12-11",
        InterfaceType.EMBEDDING: "text-embedding-3-small",
    },
    "gemini": {
        InterfaceType.LLM: "gemini-2.5-pro",
        InterfaceType.VLM: "gemini-2.5-pro",
        InterfaceType.EMBEDDING: "text-embedding-004",
    },
    "anthropic": {
        InterfaceType.LLM: "claude-sonnet-4-5-20250929",
        InterfaceType.VLM: "claude-sonnet-4-5-20250929",
        InterfaceType.EMBEDDING: None,  # Anthropic does not provide native embedding models
    },
    "byteplus": {
        InterfaceType.LLM: "seed-2-0-pro-260328",
        InterfaceType.VLM: "seed-2-0-pro-260328",
        InterfaceType.EMBEDDING: "skylark-embedding-vision-250615",
    },
    "minimax": {
        InterfaceType.LLM: "MiniMax-Text-01",
        InterfaceType.VLM: "MiniMax-VL-01",
        InterfaceType.EMBEDDING: None,
    },
    "deepseek": {
        InterfaceType.LLM: "deepseek-chat",
        InterfaceType.VLM: None,
        InterfaceType.EMBEDDING: None,
    },
    "moonshot": {
        InterfaceType.LLM: "kimi-k2.5",
        InterfaceType.VLM: "moonshot-v1-8k-vision-preview",
        InterfaceType.EMBEDDING: None,
    },
    "grok": {
        InterfaceType.LLM: "grok-3",
        InterfaceType.VLM: "grok-4-0709",
        InterfaceType.EMBEDDING: None,
    },
    "openrouter": {
        # OpenRouter slugs follow `<provider>/<model>` format. Default to a Claude
        # model so KV caching exercises the cache_control path on first use.
        InterfaceType.LLM: "anthropic/claude-sonnet-4.5",
        InterfaceType.VLM: "anthropic/claude-sonnet-4.5",
        InterfaceType.EMBEDDING: None,
    },
    "bedrock": {
        # Default to Claude Haiku 4.5 — best price/performance on Bedrock with
        # cachePoint support (5-min + 1-hour TTL). The `us.` prefix is the
        # cross-region inference profile, which is required because Claude 4.x
        # models reject on-demand invocations against the bare `anthropic.*`
        # ID ("Invocation of model ID ... with on-demand throughput isn't
        # supported. Retry your request with the ID or ARN of an inference
        # profile that contains this model."). The `us.anthropic.` prefix
        # still matches `_BEDROCK_CACHE_PREFIXES`, so cachePoint is exercised.
        # Users in EU / APAC regions should change `us.` to `eu.` / `ap.`.
        # Haiku 4.5 also accepts image content blocks via Converse, so it
        # doubles as the VLM default. Embedding stays on Titan.
        InterfaceType.LLM: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        InterfaceType.VLM: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        InterfaceType.EMBEDDING: "amazon.titan-embed-text-v2:0",
    },
    "craftbot": {
        # CraftBot's managed default. Same Bedrock-backed Claude Haiku 4.5 as
        # `bedrock`, but credentials come from container env (boto3 default
        # chain) and usage is forwarded to the craftbot.live dashboard. The
        # CRAFTBOT_DEFAULT_MODEL env var can override at boot — see
        # app/network_interface/bootstrap.py.
        InterfaceType.LLM: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        InterfaceType.VLM: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        InterfaceType.EMBEDDING: "amazon.titan-embed-text-v2:0",
    },
}
