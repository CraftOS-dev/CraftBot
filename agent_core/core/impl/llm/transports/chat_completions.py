# -*- coding: utf-8 -*-
"""Chat Completions transport (Phase 2 extraction from interface.py).

Covers every OpenAI-compatible provider (openai, minimax, deepseek,
moonshot, grok, openrouter, glm, fugu — including the ChatGPT-subscription
translator client, which keeps the same call surface) plus the Ollama
native ``/api/generate`` path (wire "ollama").

Bodies moved VERBATIM from LLMInterface._generate_openai and
LLMInterface._generate_ollama; ``self`` rewired to ``iface``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

import requests

from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import get_cache_config, get_cache_metrics
from agent_core.core.impl.llm.errors import classify_llm_error, provider_display_name
from agent_core.core.models.registry import (
    get_registry as _get_registry,
    supports_prompt_cache_key as _supports_pck,
)
from agent_core.core.models.provider_config import (
    OMIT_TEMPERATURE as _OMIT_TEMPERATURE,
    resolve_temperature as _resolve_temperature,
)
from agent_core.utils.logger import logger

# Some reasoning models (e.g. MiniMax M2.x by default) inline their
# chain-of-thought in the message content wrapped in <think>...</think>
# instead of a separate reasoning_content field. Strip it so the downstream
# JSON-action parser sees only the answer. Non-greedy + DOTALL.
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_reasoning_tags(text: Optional[str]) -> str:
    return _THINK_RE.sub("", text or "").strip()


@profile("llm_openai_call", OperationCategory.LLM)
def generate_openai(
    iface,
    system_prompt: str | None,
    user_prompt: str,
    call_type: Optional[str] = None,
    messages_override: Optional[List[Dict[str, Any]]] = None,
    json_mode: bool = True,
) -> Dict[str, Any]:
    """Generate response using OpenAI with automatic prompt caching.

    OpenAI's prompt caching is automatic for prompts ≥1024 tokens:
    - No code changes required to enable caching
    - Cached tokens are returned in usage.prompt_tokens_details.cached_tokens
    - 50% discount on cached input tokens
    - Cache retention: 5-10 minutes (up to 1 hour during off-peak)
    - Using prompt_cache_key influences routing for better cache hit rates

    Args:
        system_prompt: The system prompt.
        user_prompt: The user prompt for this request.
        call_type: Optional call type for cache routing (e.g., "reasoning", "action_selection").
                   When provided, generates a prompt_cache_key to improve cache hit rates
                   when alternating between different call types.
        messages_override: Optional pre-built multi-turn messages list. Used
            by the OpenRouter-via-Claude session path to send a growing
            conversation history so the upstream Anthropic model can cache
            the accumulating prefix via OR's cache_control field. When set,
            it's sent verbatim — system_prompt is still passed in for cache-
            key derivation but the request body uses messages_override.

    Cache hits are logged when cached_tokens > 0 in the response.
    """
    token_count_input = token_count_output = 0
    cached_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None
    config = get_cache_config()
    cache_type = f"automatic_{call_type}" if call_type else "automatic"

    try:
        if not iface.client:
            # No API key configured (or client construction failed) —
            # shared by openai/minimax/deepseek/moonshot/grok/openrouter/
            # glm/fugu, all of which route through this method. Without
            # this guard, `iface.client.chat...` below raises a bare
            # "'NoneType' object has no attribute 'chat'" — matches the
            # explicit "client was not initialised" pattern already used
            # for Anthropic/Gemini/Bedrock, so it classifies as CONFIG
            # and fails fast instead of a confusing crash.
            raise RuntimeError(
                f"{provider_display_name(iface.provider)} client was not initialised."
            )
        if messages_override is not None:
            messages: List[Dict[str, Any]] = messages_override
        else:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

        # Build request kwargs. Temperature follows the provider's policy
        # (resolve_temperature): most providers send the caller's value, but
        # OpenAI and Kimi/Moonshot profiles omit the field entirely — their
        # reasoning/thinking models reject an explicit temperature, and the
        # server default is valid for every model (docs/
        # PROVIDER_SETTINGS_UX_FIX.md; provider_config.fixed_temperature).
        request_kwargs: Dict[str, Any] = {
            "model": iface.model,
            "messages": messages,
        }
        _profile = _get_registry().get(iface.provider)
        _temp = _resolve_temperature(_profile, iface.temperature)
        if _temp is not _OMIT_TEMPERATURE:
            request_kwargs["temperature"] = _temp

        # Output tokens: cap the VALUE to the provider's output limit (several
        # providers — NVIDIA, Cerebras, Together, Groq — 400 rather than clamp
        # when it's exceeded), and pick the FIELD NAME per provider policy
        # (profile.uses_max_completion_tokens: OpenAI/Cerebras/MiniMax/Groq
        # take 'max_completion_tokens'; everyone else legacy 'max_tokens').
        _max_tokens_value = iface.max_tokens
        if _profile is not None and _profile.max_output_tokens:
            _max_tokens_value = min(_max_tokens_value, _profile.max_output_tokens)
        uses_max_completion_tokens = (
            _profile is not None and _profile.uses_max_completion_tokens
        )
        if uses_max_completion_tokens:
            request_kwargs["max_completion_tokens"] = _max_tokens_value
        else:
            request_kwargs["max_tokens"] = _max_tokens_value

        # Enforce JSON output where the provider accepts json_object.
        # Perplexity (only text/json_schema) and LM Studio reject/ignore it,
        # so their profiles opt out and rely on prompt-instructed JSON (the
        # request messages already instruct JSON). See _profile above.
        # Gated on the caller's json_mode too: forcing json_object onto a
        # prose prompt is out-of-contract — OpenAI rejects it (messages must
        # mention JSON) and DeepSeek degenerates into whitespace-only output
        # that reads as an empty response.
        if json_mode and (_profile is None or _profile.supports_json_object):
            request_kwargs["response_format"] = {"type": "json_object"}

        # Build provider-specific cache hints in extra_body.
        # - prompt_cache_key (OpenAI/DeepSeek/OpenRouter/Grok): improves
        #   prefix-cache routing stickiness across alternating call types.
        #   Grok DOES honor it — verified empirically: without a key a
        #   repeated identical prefix intermittently missed (routing bounced
        #   to a cold node); with prompt_cache_key the same prefix stayed a
        #   consistent hit. The old code skipped grok on a stale assumption.
        # - cache_control (OpenRouter routing to Anthropic Claude only): Anthropic
        #   prompt caching is opt-in. OpenRouter accepts a top-level cache_control
        #   field and applies it to the last cacheable block automatically. For
        #   OpenAI/DeepSeek/Gemini upstreams via OpenRouter, caching is automatic
        #   on the upstream side, so cache_control would be ignored — we only set
        #   it when the slug is Anthropic-routed.
        extra_body: Dict[str, Any] = {}

        long_enough = system_prompt and len(system_prompt) >= config.min_cache_tokens

        # prompt_cache_key pins requests with the same key to the same
        # cache node (sticky routing), so a repeated stable prefix stays a
        # HIT instead of bouncing to cold nodes. It is sent for ANY
        # long-enough prompt — including the agent's main sessionless
        # reasoning loop (call_type=None), whose 32k-char system prompt is
        # byte-identical every turn yet was getting 0% cache because we only
        # sent the key on call_type-tagged (session) calls. The key is
        # hash(system_prompt), which is stable across turns, so identical
        # system prompts route together. Opt-in per profile: some
        # OpenAI-compatible endpoints reject unknown top-level fields.
        if long_enough and _supports_pck(iface.provider):
            prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
            cache_key = f"{call_type}_{prompt_hash}" if call_type else prompt_hash
            extra_body["prompt_cache_key"] = cache_key
            logger.debug(f"[OPENAI] Using prompt_cache_key: {cache_key}")

        if iface.provider == "openrouter" and long_enough:
            model_lower_for_cache = (iface.model or "").lower()
            # OpenRouter slugs are "<provider>/<model>". Anthropic Claude routes
            # are the only ones requiring opt-in cache_control. Detect by either
            # the slug prefix or the "claude" substring (some aliases like
            # "anthropic/claude-3.5-sonnet:beta" still match).
            if (
                model_lower_for_cache.startswith("anthropic/")
                or "claude" in model_lower_for_cache
            ):
                cache_control: Dict[str, Any] = {"type": "ephemeral"}
                if call_type:
                    # 1-hour TTL keeps caches alive across alternating call types
                    # (mirrors the Anthropic-direct path).
                    cache_control["ttl"] = "1h"
                extra_body["cache_control"] = cache_control
                logger.debug(
                    f"[OPENROUTER] Anthropic cache_control: {cache_control} (model={iface.model})"
                )

        if extra_body:
            request_kwargs["extra_body"] = extra_body

        # In ChatGPT subscription mode the ``iface.client`` is a
        # ChatGPTSubscriptionClient that re-routes chat.completions
        # calls through the Responses API (the only surface the
        # chatgpt.com/backend-api/codex backend exposes). Call-site
        # stays unchanged.
        response = iface.client.chat.completions.create(**request_kwargs)
        if not response.choices:
            raise ValueError(f"Provider returned no choices (model={iface.model!r})")
        content = _strip_reasoning_tags(response.choices[0].message.content)
        token_count_input = response.usage.prompt_tokens
        token_count_output = response.usage.completion_tokens

        # Extract cached tokens. Empirically ALL the OpenAI-compatible
        # upstreams we use — including grok (xAI) — report cached tokens
        # under usage.prompt_tokens_details.cached_tokens. Grok does NOT
        # return the top-level prompt_cache_hit_tokens field (verified: it
        # is always absent), so the old grok-specific read reported 0 even
        # on real cache hits. Read the nested field first, then fall back
        # to the legacy top-level field for any provider that still uses it.
        # Cached-token field varies by provider (verified against docs). Read
        # in priority order so automatic prompt caching is COUNTED everywhere:
        #   1. usage.prompt_tokens_details.cached_tokens — OpenAI/OpenRouter/
        #      Grok/GLM/Cerebras/Qwen/Perplexity/MiniMax/Mistral (OpenAI-style)
        #   2. usage.cached_tokens (flat)               — Together (non-reasoning
        #      models), legacy Qwen
        #   3. usage.prompt_cache_hit_tokens (top-level) — DeepSeek
        # (Fireworks reports cached tokens only via a response HEADER, and
        #  HF-router / hosted NVIDIA NIM don't report them at all — those stay
        #  0% in metrics even though the provider may still cache server-side.)
        prompt_tokens_details = getattr(response.usage, "prompt_tokens_details", None)
        if prompt_tokens_details:
            cached_tokens = getattr(prompt_tokens_details, "cached_tokens", 0) or 0
        if not cached_tokens:
            cached_tokens = getattr(response.usage, "cached_tokens", 0) or 0
        if not cached_tokens:
            cached_tokens = getattr(response.usage, "prompt_cache_hit_tokens", 0) or 0

        # Record cache metrics
        provider_label = iface.provider  # "openai", "grok", "deepseek", etc.
        metrics = get_cache_metrics()
        if cached_tokens > 0:
            logger.info(
                f"[CACHE] {provider_label} {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache"
            )
            metrics.record_hit(
                provider_label,
                cache_type,
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
            # Caching should have been attempted (prompt long enough)
            # This is a miss - either first call or cache expired
            metrics.record_miss(
                provider_label, cache_type, total_tokens=token_count_input
            )

        status = "success"
    except Exception as exc:
        exc_obj = exc
        logger.debug(f"Error calling OpenAI API: {exc}")

    total_tokens = token_count_input + token_count_output

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
        cached_tokens=cached_tokens or 0,
    )

    # Report usage. service_type stays "llm_openai" (the request shape) but
    # provider attributes to the actual upstream so dashboards split out
    # OpenRouter / DeepSeek / Grok separately.
    iface._report_usage_async(
        "llm_openai",
        iface.provider,
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
        # Include error details for better diagnostics
        error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
        result["error"] = error_str
        # Classify once and stash the LLMErrorInfo object so the outer
        # `_generate_response_sync` can attach it to the consecutive-
        # failure exception. Without this, providers that go through
        # this path (OpenAI, OpenRouter, Grok, DeepSeek, MiniMax,
        # Moonshot) would surface a bare "Aborted after N consecutive
        # failures." with no cause when they fail. The classifier is
        # wrapped in try/except so it can never break the error path.
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


@profile("llm_ollama_call", OperationCategory.LLM)
def generate_ollama(
    iface, system_prompt: str | None, user_prompt: str, json_mode: bool = True
) -> Dict[str, Any]:
    token_count_input = token_count_output = 0
    total_tokens = 0
    status = "failed"
    content: Optional[str] = None
    exc_obj: Optional[Exception] = None

    try:
        payload = {
            "model": iface.model,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": iface.temperature,
            },
        }
        # JSON grammar only for calls whose prompt instructs JSON —
        # Ollama's format=json on a prose prompt degenerates into
        # whitespace/brace spam.
        if json_mode:
            payload["format"] = "json"
        if system_prompt:
            payload["system"] = system_prompt
        url: str = f"{iface.remote_url.rstrip('/')}/api/generate"
        response = requests.post(url, json=payload, timeout=600)
        response.raise_for_status()
        result = response.json()

        content = result.get("response", "").strip()
        token_count_input = result.get("prompt_eval_count", 0)
        token_count_output = result.get("eval_count", 0)
        total_tokens = token_count_input + token_count_output
        status = "success"
    except Exception as exc:
        exc_obj = exc
        logger.debug(f"Error calling Ollama API: {exc}")

    iface._call_log_to_db(
        system_prompt,
        user_prompt,
        content if content is not None else str(exc_obj),
        status,
        token_count_input,
        token_count_output,
    )

    # Report usage (no caching for Ollama)
    iface._report_usage_async(
        "llm_ollama", "remote", iface.model, token_count_input, token_count_output, 0
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
