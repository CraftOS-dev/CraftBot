# -*- coding: utf-8 -*-
"""Anthropic Messages transport (Phase 2 extraction from interface.py).

Body moved VERBATIM from LLMInterface._generate_anthropic; ``self`` rewired
to ``iface``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import get_cache_config, get_cache_metrics
from agent_core.core.impl.llm.errors import classify_llm_error
from agent_core.utils.logger import logger


@profile("llm_anthropic_call", OperationCategory.LLM)
def generate(
    iface,
    system_prompt: str | None,
    user_prompt: str,
    call_type: Optional[str] = None,
    messages: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Generate response using Anthropic with prompt caching.

    Anthropic's prompt caching uses `cache_control` markers on content blocks.
    When the system prompt is long enough (≥1024 tokens), we enable caching.

    For multi-turn sessions, pass pre-built `messages` with cache_control on the
    last assistant message. This enables prefix caching of the entire conversation
    history, not just the system prompt.

    TTL Options:
    - Default (5 minutes): Free, uses "ephemeral" type
    - Extended (1 hour): When call_type is provided, uses extended TTL for better
      cache hit rates when alternating between different call types.
      Note: Extended TTL cache writes cost 100% more, but reads are 90% cheaper.

    Args:
        system_prompt: The system prompt (cached when long enough).
        user_prompt: The user prompt for this request.
        call_type: Optional call type (e.g., "reasoning", "action_selection").
                   When provided, uses extended 1-hour TTL for better cache hit rates.
        messages: Optional pre-built messages list for multi-turn sessions.
                  When provided, used instead of building a single-turn message.

    Cache hits are logged when `cache_read_input_tokens` > 0 in the response.
    """
    token_count_input = token_count_output = 0
    total_tokens = 0
    cached_tokens = 0
    # Initialized here (not just inside the try) so the post-`except`
    # _call_log_to_db below can reference them even when the API call
    # throws before they're assigned (e.g. out-of-credits). Otherwise the
    # real provider error is masked by an UnboundLocalError.
    cache_creation = 0
    cache_read = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None
    config = get_cache_config()
    cache_type = f"ephemeral_{call_type}" if call_type else "ephemeral"

    try:
        if not iface._anthropic_client:
            raise RuntimeError("Anthropic client was not initialised.")

        # Build the message - use pre-built messages for multi-turn, or single-turn
        # Anthropic requires max_tokens; use 16384 (Claude 4 default) to avoid truncation
        message_kwargs: Dict[str, Any] = {
            "model": iface.model,
            "max_tokens": 16384,
            "messages": messages
            if messages is not None
            else [
                {"role": "user", "content": user_prompt},
            ],
        }

        if system_prompt:
            # Use caching if system prompt is long enough
            if len(system_prompt) >= config.min_cache_tokens:
                # Format system as list of content blocks with cache_control
                # Use extended 1-hour TTL when call_type is provided for better
                # cache hit rates when alternating between different call types
                cache_control: Dict[str, str] = {"type": "ephemeral"}
                if call_type:
                    # Extended TTL: cache writes cost 100% more, reads 90% cheaper
                    # Better for alternating call types where 5-minute TTL might expire
                    cache_control["ttl"] = "1h"
                    logger.debug(
                        f"[ANTHROPIC] Using 1-hour TTL for call_type: {call_type}"
                    )

                message_kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": cache_control,
                    }
                ]
            else:
                # Short prompt - use simple string format (no caching)
                message_kwargs["system"] = system_prompt

        # Always pass temperature for Anthropic (their default is 1.0, not 0.0)
        message_kwargs["temperature"] = iface.temperature

        response = iface._anthropic_client.messages.create(**message_kwargs)

        # Extract content from the response
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text
        content = content.strip()

        # Token usage from Anthropic response
        # Anthropic reports input_tokens as non-cached input only.
        # cache_creation_input_tokens: tokens written to cache (first call)
        # cache_read_input_tokens: tokens read from cache (subsequent calls)
        # Total input = input_tokens + cache_creation + cache_read
        base_input = response.usage.input_tokens
        token_count_output = response.usage.output_tokens
        cache_creation = (
            getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        )
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        token_count_input = base_input + cache_creation + cache_read
        total_tokens = token_count_input + token_count_output
        cached_tokens = cache_read

        # Record metrics
        metrics = get_cache_metrics()
        if cache_read > 0:
            logger.info(
                f"[CACHE] Anthropic {cache_type} cache hit: {cache_read}/{token_count_input} tokens from cache"
            )
            metrics.record_hit(
                "anthropic",
                cache_type,
                cached_tokens=cache_read,
                total_tokens=token_count_input,
            )
        elif cache_creation > 0:
            logger.info(
                f"[CACHE] Anthropic {cache_type} cache created: {cache_creation} tokens cached"
            )
            # Cache creation is a "miss" for the current call but sets up future hits
            metrics.record_miss(
                "anthropic", cache_type, total_tokens=token_count_input
            )
        elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
            # Caching was attempted but no cache info returned - unexpected
            metrics.record_miss(
                "anthropic", cache_type, total_tokens=token_count_input
            )

        status = "success"

    except Exception as exc:  # pragma: no cover
        exc_obj = exc
        logger.debug(f"Error calling Anthropic API: {exc}")

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
        cached_tokens=cached_tokens,  # cache_read — was MISSING (always 0)
        cache_creation_tokens=cache_creation,  # cache_write — to settle write-vs-expiry
    )

    # Report usage
    iface._report_usage_async(
        "llm_anthropic",
        "anthropic",
        iface.model,
        token_count_input,
        token_count_output,
        cached_tokens,
    )

    result = {"tokens_used": total_tokens or 0, "cached_tokens": cached_tokens}
    if exc_obj:
        error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
        result["error"] = error_str
        # Classify once and stash the LLMErrorInfo object so the
        # outer `_generate_response_sync` can put `info.message`
        # (the rich detailed string) into the RuntimeError it raises,
        # and attach the info to LLMConsecutiveFailureError at the
        # 5-failure threshold. The classifier is wrapped in try/except
        # so it can never break the error path itself.
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
