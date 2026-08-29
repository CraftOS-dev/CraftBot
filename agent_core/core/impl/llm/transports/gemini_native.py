# -*- coding: utf-8 -*-
"""Gemini native transport (Phase 2 extraction from interface.py).

Body moved VERBATIM from LLMInterface._generate_gemini; ``self`` rewired to
``iface``. The GeminiCacheManager stays owned by LLMInterface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import get_cache_config, get_cache_metrics
from agent_core.core.impl.llm.errors import classify_llm_error
from agent_core.utils.logger import logger


@profile("llm_gemini_call", OperationCategory.LLM)
def generate(
    iface,
    system_prompt: str | None,
    user_prompt: str,
    call_type: Optional[str] = None,
    contents_override: Optional[List[Dict[str, Any]]] = None,
    json_mode: bool = True,
) -> Dict[str, Any]:
    """Generate response using Gemini with explicit or implicit caching.

    When call_type is provided and system_prompt is long enough, uses explicit
    caching via GeminiCacheManager. This ensures different call types (reasoning,
    action_selection, etc.) get separate caches for optimal cache hit rates.

    Without call_type, falls back to Gemini's implicit caching which may have
    lower hit rates when alternating between different prompt structures.

    Args:
        system_prompt: The system prompt (cached when using explicit caching).
        user_prompt: The user prompt for this request.
        call_type: Optional call type for cache keying (e.g., "reasoning", "action_selection").
                   When provided, enables explicit caching per call type.
        contents_override: Optional pre-built multi-turn `contents` array
            from the session-cache path. When provided, skips the
            explicit-cache code path and sends the full conversation
            history so Gemini's implicit caching catches the growing
            stable prefix automatically (caching covers more tokens with
            every turn without us needing to manage a named cache object).

    Returns:
        Dict with tokens_used, content, cached_tokens.
    """
    from app.google_gemini_client import GeminiAPIError

    # Per-call reasoning cap, set by callers that pass thinking_budget (e.g. the
    # entity-judge pipeline). Rides the shared per-call context so no transport
    # signature changes; None for every ordinary call, in which case Gemini's
    # default thinking behaviour is unchanged.
    from agent_core.core.impl.llm.interface import _llm_call_ctx

    thinking_budget = (_llm_call_ctx.get() or {}).get("thinking_budget")

    token_count_input = token_count_output = 0
    cached_tokens = 0
    total_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None
    config = get_cache_config()
    cache_type = "implicit"  # Default cache type for metrics

    try:
        if not iface._gemini_client:
            raise RuntimeError("Gemini client was not initialised.")

        # Multi-turn implicit-cache path takes precedence when provided —
        # the session-cache dispatcher accumulates history and we want
        # Gemini's automatic prefix matching to do the work.
        if contents_override is not None:
            cache_type = f"implicit_{call_type}" if call_type else "implicit"
            logger.debug(
                f"[GEMINI] Using multi-turn implicit caching "
                f"(call_type={call_type}, turns={len(contents_override)})"
            )
            result = iface._gemini_client.generate_text_multiturn(
                iface.model,
                contents=contents_override,
                system_prompt=system_prompt,
                temperature=iface.temperature,
                max_output_tokens=iface.max_tokens,
                json_mode=json_mode,
            )
        else:
            # Use explicit caching when:
            # 1. call_type is provided
            # 2. system_prompt is long enough
            # 3. cache manager is available
            # Note: GeminiCacheManager will automatically fall back to implicit
            # caching if the system prompt is below Gemini's 1024 token minimum
            # Explicit caching is only reachable from the session paths,
            # whose calls are all JSON — a prose (json_mode=False) call
            # never passes call_type, so it always lands on the
            # generate_text fallback below where json_mode is honored.
            use_explicit_cache = (
                call_type
                and system_prompt
                and len(system_prompt) >= config.min_cache_tokens
                and iface._gemini_cache_manager
            )

            if use_explicit_cache:
                cache_type = f"explicit_{call_type}"
                logger.debug(
                    f"[GEMINI] Using explicit caching for call_type: {call_type}"
                )
                result = iface._gemini_cache_manager.get_or_create_cache(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    call_type=call_type,
                    temperature=iface.temperature,
                    max_tokens=iface.max_tokens,
                )
            else:
                # Fall back to implicit caching (or no caching for short prompts)
                result = iface._gemini_client.generate_text(
                    iface.model,
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=iface.temperature,
                    max_output_tokens=iface.max_tokens,
                    json_mode=json_mode,
                    thinking_budget=thinking_budget,
                )

        # Extract response data
        content = result.get("content", "")
        total_tokens = result.get("tokens_used", 0)
        token_count_input = result.get("prompt_tokens", 0)
        token_count_output = result.get("completion_tokens", 0)
        cached_tokens = result.get("cached_tokens", 0)

        # Record cache metrics
        metrics = get_cache_metrics()
        if cached_tokens > 0:
            logger.info(
                f"[CACHE] Gemini {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache"
            )
            metrics.record_hit(
                "gemini",
                cache_type,
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
            # Caching should have been attempted (prompt long enough)
            # This is a miss - either first call or cache expired
            metrics.record_miss("gemini", cache_type, total_tokens=token_count_input)

        status = "success"
    except GeminiAPIError as exc:  # pragma: no cover
        exc_obj = exc
        logger.error(f"Gemini API rejected the prompt: {exc}")
    except Exception as exc:  # pragma: no cover
        exc_obj = exc
        logger.debug(f"Error calling Gemini API: {exc}")

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
        cached_tokens=cached_tokens,
    )

    # Report usage
    iface._report_usage_async(
        "llm_gemini",
        "gemini",
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
