# -*- coding: utf-8 -*-
"""BytePlus Responses transport (Phase 2 extraction from interface.py).

Bodies moved VERBATIM from LLMInterface._generate_byteplus,
._generate_byteplus_with_prefix_cache, ._generate_byteplus_standard and
._generate_byteplus_with_session; ``self`` rewired to ``iface``. The
BytePlusCacheManager and the Responses-API content parser
(`_parse_responses_api_content`) stay owned by LLMInterface — the session
dispatcher's _process_* helpers share them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import (
    BytePlusContextOverflowError,
    get_cache_config,
    get_cache_metrics,
)
from agent_core.core.impl.llm.errors import classify_llm_error
from agent_core.utils.logger import logger


@profile("llm_byteplus_call", OperationCategory.LLM)
def generate(
    iface, system_prompt: str | None, user_prompt: str
) -> Dict[str, Any]:
    """Generate response using BytePlus with automatic prefix caching.

    Routes to prefix cache or standard API based on context.
    """
    config = get_cache_config()
    # Use prefix caching if:
    # - System prompt is provided
    # - System prompt is long enough (uses shared config)
    # - Cache manager is available
    if (
        system_prompt
        and len(system_prompt) >= config.min_cache_tokens
        and iface._byteplus_cache_manager
    ):
        return generate_with_prefix_cache(iface, system_prompt, user_prompt)

    # Standard path (no caching)
    return generate_standard(iface, system_prompt, user_prompt)


def generate_with_prefix_cache(
    iface, system_prompt: str, user_prompt: str
) -> Dict[str, Any]:
    """Use Responses API with prefix caching.

    The system prompt is cached and reused across calls with the same content.
    Only the user prompt is processed fresh each time.
    Uses previous_response_id chaining for cache hits.
    """
    token_count_input = token_count_output = 0
    total_tokens = 0
    cached_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None

    try:
        # Get response using prefix cache (creates cache on first call)
        result = iface._byteplus_cache_manager.get_or_create_prefix_cache(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=iface.temperature,
            max_tokens=iface.max_tokens,
        )

        logger.info(f"BYTEPLUS CACHED RESPONSE: {result}")

        # Parse response (Responses API format)
        content = iface._parse_responses_api_content(result)

        if not content:
            blocked_reason = _byteplus_blocked_reason(result)
            if blocked_reason:
                raise RuntimeError(
                    f"Response was blocked by the provider's content filter "
                    f"({blocked_reason})."
                )

        # Token usage from Responses API
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("input_tokens", 0))
        token_count_output = int(usage.get("output_tokens", 0))
        total_tokens = int(usage.get("total_tokens", 0)) or (
            token_count_input + token_count_output
        )

        # Log cache hit info if available and record metrics
        # Responses API uses input_tokens_details instead of prompt_tokens_details
        cached_tokens = usage.get("input_tokens_details", {}).get(
            "cached_tokens", 0
        )
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(
                f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached"
            )
            metrics.record_hit(
                "byteplus",
                "prefix",
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        else:
            # First call or cache miss
            metrics.record_miss(
                "byteplus", "prefix", total_tokens=token_count_input
            )

        status = "success"

    except requests.HTTPError as e:
        # Check if this is a cache-related error (expired, not found)
        if e.response is not None and e.response.status_code in (404, 410):
            logger.warning(f"[CACHE] Cache expired or not found, recreating: {e}")
            # Invalidate and retry once
            iface._byteplus_cache_manager.invalidate_prefix_cache(system_prompt)
            try:
                result = iface._byteplus_cache_manager.get_or_create_prefix_cache(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=iface.temperature,
                    max_tokens=iface.max_tokens,
                )
                content = iface._parse_responses_api_content(result)
                usage = result.get("usage") or {}
                token_count_input = int(usage.get("input_tokens", 0))
                token_count_output = int(usage.get("output_tokens", 0))
                total_tokens = int(usage.get("total_tokens", 0)) or (
                    token_count_input + token_count_output
                )
                status = "success"
            except Exception as retry_exc:
                exc_obj = retry_exc
                logger.error(f"[CACHE] Retry failed, falling back: {retry_exc}")
                return generate_standard(iface, system_prompt, user_prompt)
        else:
            exc_obj = e
            logger.debug(f"Error calling BytePlus Responses API: {e}")
    except Exception as exc:
        exc_obj = exc
        logger.debug(f"Error calling BytePlus Responses API: {exc}")

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
        cached_tokens=cached_tokens or 0,
    )

    # Report usage
    iface._report_usage_async(
        "llm_byteplus",
        "byteplus",
        iface.model,
        token_count_input,
        token_count_output,
        cached_tokens or 0,
    )

    result_out: Dict[str, Any] = {
        "tokens_used": total_tokens or 0,
        "cached_tokens": cached_tokens or 0,
    }
    if exc_obj:
        error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
        result_out["error"] = error_str
        try:
            result_out["error_info_obj"] = classify_llm_error(
                exc_obj, provider=iface.provider, model=iface.model
            )
        except Exception:
            pass
        result_out["content"] = ""
    else:
        result_out["content"] = content or ""
    return result_out


def generate_standard(
    iface, system_prompt: str | None, user_prompt: str
) -> Dict[str, Any]:
    """Standard BytePlus API call without caching (uses /chat/completions)."""
    token_count_input = token_count_output = 0
    total_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None

    try:
        # Build OpenAI-compatible messages array
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        url = f"{iface.byteplus_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": iface.model,
            "messages": messages,
            # Wire through sampling + output control
            "temperature": iface.temperature,
            "max_tokens": iface.max_tokens,
            # Note: response_format not supported by all BytePlus models (e.g., kimi)
            # "stream": False,  # default is non-streaming
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {iface.api_key}",
        }

        # Log the request
        logger.info(f"[BYTEPLUS STANDARD REQUEST] URL: {url}")
        logger.info(
            f"[BYTEPLUS STANDARD REQUEST] Model: {iface.model}, Temp: {iface.temperature}, MaxTokens: {iface.max_tokens}"
        )
        logger.info(f"[BYTEPLUS STANDARD REQUEST] Messages count: {len(messages)}")

        response = requests.post(url, json=payload, headers=headers, timeout=600)

        # Log response status
        logger.info(f"[BYTEPLUS STANDARD RESPONSE] Status: {response.status_code}")

        response.raise_for_status()
        result = response.json()

        logger.info(f"[BYTEPLUS STANDARD RESPONSE] Body: {result}")

        # Non-streaming content location (OpenAI-compatible)
        choices = result.get("choices", [])
        if choices:
            # choices[0].message.content is the OpenAI-compatible field
            content = (
                choices[0].get("message", {}).get("content")
                or choices[0].get("delta", {}).get("content", "")
                or ""
            ).strip()
            if not content and choices[0].get("finish_reason") == "content_filter":
                # OpenAI-compatible signal for moderation-blocked output —
                # HTTP 200 with empty content, otherwise indistinguishable
                # from a generic empty response.
                raise RuntimeError(
                    "Response was blocked by the provider's content filter."
                )

        total_tokens = int(result.get("usage", {}).get("total_tokens", 0))

        # Token usage (prompt/completion/total)
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("prompt_tokens", 0))
        token_count_output = int(usage.get("completion_tokens", 0))
        status = "success"

    except Exception as exc:  # pragma: no cover
        exc_obj = exc
        logger.debug(f"Error calling BytePlus API: {exc}")

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
    )

    # Report usage (no caching for standard path)
    iface._report_usage_async(
        "llm_byteplus",
        "byteplus",
        iface.model,
        token_count_input,
        token_count_output,
        0,
    )

    result = {"tokens_used": total_tokens or 0}
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


def generate_with_session(
    iface, task_id: str, call_type: str, user_prompt: str
) -> Dict[str, Any]:
    """Use Responses API with session caching for task/GUI calls.

    The context grows with each call as we chain responses via previous_response_id.
    Each call type has its own session to avoid polluting different prompt structures.

    If context overflow is detected, the session is automatically reset and retried
    with a fresh session containing only the system prompt and current user prompt.
    """
    token_count_input = token_count_output = 0
    total_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None
    cached_tokens = 0
    session_key = f"{task_id}:{call_type}"

    try:
        if not iface._byteplus_cache_manager.has_session(task_id, call_type):
            # The cache manager was rebuilt (e.g. a model-only Settings
            # change recreates it since BytePlus sessions are server-side
            # and model-bound), emptying its session registry — but the
            # system prompt survives a model-only reinit, so reseed a
            # fresh session instead of failing this turn outright.
            system_prompt = iface._session_system_prompts.get(session_key)
            if not system_prompt:
                raise ValueError(f"No session cache found for {session_key}")

            logger.info(
                f"[BYTEPLUS] No session cache for {session_key} — "
                f"reseeding a fresh session from the stored system prompt"
            )
            result = iface._byteplus_cache_manager.create_session_cache(
                task_id=task_id,
                call_type=call_type,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=iface.temperature,
                max_tokens=iface.max_tokens,
            )
        else:
            result = iface._byteplus_cache_manager.chat_with_session(
                task_id=task_id,
                call_type=call_type,
                user_prompt=user_prompt,
                temperature=iface.temperature,
                max_tokens=iface.max_tokens,
            )

        logger.info(f"BYTEPLUS SESSION RESPONSE: {result}")

        # Parse response (Responses API format)
        content = iface._parse_responses_api_content(result)

        # Token usage from Responses API
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("input_tokens", 0))
        token_count_output = int(usage.get("output_tokens", 0))
        total_tokens = int(usage.get("total_tokens", 0)) or (
            token_count_input + token_count_output
        )

        # Log cache info and record metrics
        # Responses API uses input_tokens_details instead of prompt_tokens_details
        cached_tokens = usage.get("input_tokens_details", {}).get(
            "cached_tokens", 0
        )
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(
                f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached"
            )
            metrics.record_hit(
                "byteplus",
                "session",
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        else:
            # First call in session or growing context
            metrics.record_miss(
                "byteplus", "session", total_tokens=token_count_input
            )

        status = "success"

    except BytePlusContextOverflowError:
        # Context exceeded maximum length - reset session and retry with fresh context
        logger.warning(
            f"[BYTEPLUS] Context overflow for {session_key}, resetting session and retrying..."
        )

        # End the overflowed session
        iface._byteplus_cache_manager.end_session(task_id, call_type)

        # Get the stored system prompt for this session
        system_prompt = iface._session_system_prompts.get(session_key)
        if not system_prompt:
            exc_obj = ValueError(
                f"Cannot reset session {session_key}: no system prompt stored"
            )
            logger.error(str(exc_obj))
        else:
            try:
                # Create a fresh session with system prompt and current user prompt
                logger.info(
                    f"[BYTEPLUS] Creating fresh session for {session_key} after overflow"
                )
                result = iface._byteplus_cache_manager.create_session_cache(
                    task_id=task_id,
                    call_type=call_type,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=iface.temperature,
                    max_tokens=iface.max_tokens,
                )

                logger.info(f"BYTEPLUS SESSION RESPONSE (after reset): {result}")

                # Parse response
                content = iface._parse_responses_api_content(result)

                # Token usage
                usage = result.get("usage") or {}
                token_count_input = int(usage.get("input_tokens", 0))
                token_count_output = int(usage.get("output_tokens", 0))
                total_tokens = int(usage.get("total_tokens", 0)) or (
                    token_count_input + token_count_output
                )

                # Record as cache miss (fresh session)
                metrics = get_cache_metrics()
                metrics.record_miss(
                    "byteplus", "session_reset", total_tokens=token_count_input
                )

                status = "success"
                logger.info(
                    f"[BYTEPLUS] Successfully recovered from context overflow for {session_key}"
                )

            except Exception as retry_exc:
                exc_obj = retry_exc
                logger.error(
                    f"Error retrying BytePlus Session API for {session_key} after reset: {retry_exc}"
                )

    except Exception as exc:
        exc_obj = exc
        logger.error(f"Error calling BytePlus Session API for {session_key}: {exc}")

    iface._call_log_to_db(
        f"[SESSION:{session_key}]",  # Mark as session call in logs with call_type
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
        cached_tokens=cached_tokens or 0,
    )

    # Report usage
    cached_tokens = 0
    if status == "success":
        usage = result.get("usage") or {} if "result" in dir() else {}
        cached_tokens = (
            usage.get("input_tokens_details", {}).get("cached_tokens", 0)
            if usage
            else 0
        )
    iface._report_usage_async(
        "llm_byteplus",
        "byteplus",
        iface.model,
        token_count_input,
        token_count_output,
        cached_tokens,
    )

    return {
        "tokens_used": total_tokens or 0,
        "content": content or "",
        "cached_tokens": cached_tokens or 0,
    }


def _byteplus_blocked_reason(result: Dict[str, Any]) -> Optional[str]:
    """Best-effort detection of content-filter/moderation blocking in a
    BytePlus Responses API result that came back with empty content but no
    HTTP-level error (status 200, `choices`/`output` just empty).

    Mirrors OpenAI's Responses API `status` / `incomplete_details.reason`
    shape, which BytePlus's docs describe this endpoint as following — not
    independently verified against a live blocked response, so this only
    fires on an unambiguous signal and otherwise returns None, leaving the
    existing generic empty-response handling untouched.
    """
    status = result.get("status")
    if status == "incomplete":
        reason = (result.get("incomplete_details") or {}).get("reason")
        if reason:
            return str(reason)
    error = result.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "").lower()
        message = str(error.get("message") or "")
        if any(k in code for k in ("content_filter", "moderation", "safety")):
            return message or code
    return None
