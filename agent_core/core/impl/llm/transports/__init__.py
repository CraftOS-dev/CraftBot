# -*- coding: utf-8 -*-
"""Wire-protocol transports for LLMInterface (Phase 2, FR-2).

Each transport module owns ONE wire protocol's request/response encoding,
extracted verbatim from interface.py. Transports are stateless: they receive
the live LLMInterface instance (`iface`) and read its provider context,
session buffers, cache managers, and logging/usage hooks through it — all
session state stays on LLMInterface (NFR-3 in docs/PROVIDER_LAYER_CATCHUP.md).

TRANSPORTS maps ProviderProfile.wire -> the transport's generate callable
with signature (iface, system_prompt, user_prompt, json_mode=True) -> response dict
({"content", "tokens_used", "cached_tokens"?, "error"?, "error_info_obj"?}).
Session-mode entry points with richer signatures are exposed as module
functions and called by the session dispatcher on LLMInterface.
"""

from agent_core.core.impl.llm.transports import (
    anthropic_messages,
    bedrock_converse,
    byteplus_responses,
    chat_completions,
    gemini_native,
)

TRANSPORTS = {
    "chat_completions": chat_completions.generate_openai,
    "ollama": chat_completions.generate_ollama,
    "anthropic_messages": anthropic_messages.generate,
    "bedrock_converse": bedrock_converse.generate,
    "gemini_native": gemini_native.generate,
    "byteplus_responses": byteplus_responses.generate,
}

__all__ = [
    "TRANSPORTS",
    "anthropic_messages",
    "bedrock_converse",
    "byteplus_responses",
    "chat_completions",
    "gemini_native",
]
