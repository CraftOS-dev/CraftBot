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
        InterfaceType.LLM: "claude-sonnet-4-6",
        InterfaceType.VLM: "claude-sonnet-4-6",
        InterfaceType.EMBEDDING: None,  # Anthropic does not provide native embedding models
    },
    "byteplus": {
        InterfaceType.LLM: "kimi-k2-250905",
        InterfaceType.VLM: "seed-1-6-250915",
        InterfaceType.EMBEDDING: "skylark-embedding-vision-250615",
    },
    "remote": {
        InterfaceType.LLM: "llama3",
        InterfaceType.VLM: "llava-v1.6",
        InterfaceType.EMBEDDING: "nomic-embed-text",
    },
}
