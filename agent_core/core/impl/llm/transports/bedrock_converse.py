# -*- coding: utf-8 -*-
"""Bedrock Converse transport (Phase 2 extraction from interface.py).

Body moved VERBATIM from LLMInterface._generate_bedrock; ``self`` rewired to
``iface``. Cache capability detection (`_bedrock_model_supports_caching`)
stays on LLMInterface — the session dispatcher and this transport share it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import get_cache_config, get_cache_metrics
from agent_core.core.impl.llm.errors import classify_llm_error
from agent_core.utils.logger import logger


@profile("llm_bedrock_call", OperationCategory.LLM)
def generate(
    iface,
    system_prompt: str | None,
    user_prompt: str,
    call_type: Optional[str] = None,
    messages: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Generate response via AWS Bedrock Converse API with prompt caching.

    Converse is the unified Bedrock API across Claude / Llama / Titan /
    Mistral. cachePoint markers are inserted only for models that support
    it (Anthropic Claude family) — other models would reject the request.

    Args:
        system_prompt: The system prompt.
        user_prompt: The user prompt for this request.
        call_type: Optional call type for cache labelling.
        messages: Optional pre-built multi-turn messages list. When provided
            (from the session-cache path), the caller has already placed a
            `cachePoint` block at the end of the last assistant content —
            that captures the entire growing prefix. In that mode we do
            NOT also put a cachePoint in the system block (only one is
            needed and placing it in messages lets the cache grow with the
            conversation). When messages is None, falls back to a fresh
            single-turn call with cachePoint on the system block.
    """
    token_count_input = token_count_output = 0
    total_tokens = 0
    cached_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None
    config = get_cache_config()
    cache_type = f"cachepoint_{call_type}" if call_type else "cachepoint"

    try:
        if not iface._bedrock_client:
            raise RuntimeError("Bedrock client was not initialised.")

        # Multi-turn path: caller provided pre-built messages with cachePoint
        # already placed on the last assistant message (if any). Single-turn
        # path: build a fresh user-only message list.
        multi_turn = messages is not None
        converse_messages = (
            messages
            if multi_turn
            else [{"role": "user", "content": [{"text": user_prompt}]}]
        )

        converse_kwargs: Dict[str, Any] = {
            "modelId": iface.model,
            "messages": converse_messages,
            "inferenceConfig": {
                "temperature": iface.temperature,
                "maxTokens": iface.max_tokens,
            },
        }

        if system_prompt:
            # When messages already carry a cachePoint (multi-turn first
            # call having a history assistant), don't double up by adding
            # another in the system block — Bedrock would still accept it
            # but a redundant checkpoint wastes a slot (max 4 per request).
            msgs_have_cachepoint = multi_turn and any(
                any("cachePoint" in block for block in msg.get("content", []))
                for msg in converse_messages
            )
            use_system_cache = bool(
                call_type
                and len(system_prompt) >= config.min_cache_tokens
                and iface._bedrock_model_supports_caching()
                and not msgs_have_cachepoint
            )
            if use_system_cache:
                converse_kwargs["system"] = [
                    {"text": system_prompt},
                    {"cachePoint": {"type": "default"}},
                ]
            else:
                converse_kwargs["system"] = [{"text": system_prompt}]

        response = iface._bedrock_client.converse(**converse_kwargs)

        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", []) or []
        content = "".join(
            block.get("text", "") for block in content_blocks if "text" in block
        ).strip()

        usage = response.get("usage", {}) or {}
        token_count_input = int(usage.get("inputTokens", 0) or 0)
        token_count_output = int(usage.get("outputTokens", 0) or 0)

        if iface._bedrock_model_supports_caching():
            # Official Converse response uses `cacheReadInputTokens` /
            # `cacheWriteInputTokens` (no "Count" suffix) per the API
            # reference. The "...TokenCount" variants are tolerated as a
            # defensive fallback in case older SDK builds expose them.
            cache_read = int(
                usage.get("cacheReadInputTokens")
                or usage.get("cacheReadInputTokenCount")
                or 0
            )
            cache_write = int(
                usage.get("cacheWriteInputTokens")
                or usage.get("cacheWriteInputTokenCount")
                or 0
            )
            # Bedrock's `inputTokens` EXCLUDES cache activity, unlike the
            # Anthropic API where input covers the full prompt. Normalize
            # to the Anthropic shape — input = full prompt, cached = reads
            # only — so downstream `input - cached` display math holds for
            # every provider.
            token_count_input += cache_read + cache_write
            cached_tokens = cache_read

            metrics = get_cache_metrics()
            if cache_read > 0:
                logger.info(
                    f"[CACHE] Bedrock {cache_type} cache hit: "
                    f"{cache_read}/{token_count_input} tokens from cache"
                )
                metrics.record_hit(
                    "bedrock",
                    cache_type,
                    cached_tokens=cache_read,
                    total_tokens=token_count_input,
                )
            elif cache_write > 0:
                logger.info(
                    f"[CACHE] Bedrock {cache_type} cache created: "
                    f"{cache_write} tokens cached"
                )
                metrics.record_miss(
                    "bedrock", cache_type, total_tokens=token_count_input
                )
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                metrics.record_miss(
                    "bedrock", cache_type, total_tokens=token_count_input
                )

        total_tokens = token_count_input + token_count_output

        status = "success"

    except Exception as exc:  # pragma: no cover
        exc_obj = exc
        logger.debug(f"Error calling Bedrock Converse API: {exc}")

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
        cached_tokens=cached_tokens or 0,
    )

    iface._report_usage_async(
        "llm_bedrock",
        "bedrock",
        iface.model,
        token_count_input,
        token_count_output,
        cached_tokens,
    )

    result = {
        "tokens_used": total_tokens or 0,
        "cached_tokens": cached_tokens,
    }
    if exc_obj:
        error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
        result["error"] = error_str
        try:
            result["error_info_obj"] = classify_llm_error(
                exc_obj, provider=iface.provider, model=iface.model
            )
        except Exception:
            pass
        result["content"] = ""
    else:
        result["content"] = content or ""
    return result
