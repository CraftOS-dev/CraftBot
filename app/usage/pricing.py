# -*- coding: utf-8 -*-
"""
app.usage.pricing

Single source of per-model token pricing (USD per 1M tokens) for cost +
cache-savings math, used by the prompt profiler and the dashboard metrics
collector.

Each entry has three rates:
    input   - standard (uncached) input tokens
    cached  - input tokens served from cache (provider discounts vary:
              Gemini / Anthropic cache-read ≈ 10% of input, OpenAI ≈ 50%)
    output  - output tokens

Values are approximate and drift over time — update against provider pricing
pages. Sources (2026-06): Gemini https://ai.google.dev/gemini-api/docs/pricing,
Anthropic & OpenAI public pricing.
"""

from __future__ import annotations

from typing import Dict

# Per 1M tokens, USD. Keys are matched as substrings of the model id; matching
# prefers the LONGEST (most specific) key, so e.g. "gpt-4o-mini" wins over
# "gpt-4o".
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # ─ OpenAI (cached ≈ 50% of input) ─
    "gpt-4o-mini": {"input": 0.15, "cached": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached": 1.25, "output": 10.00},
    "gpt-4-turbo": {"input": 10.00, "cached": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "cached": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "cached": 0.50, "output": 1.50},
    "o1-mini": {"input": 3.00, "cached": 1.50, "output": 12.00},
    "o1-preview": {"input": 15.00, "cached": 7.50, "output": 60.00},
    "o1": {"input": 15.00, "cached": 7.50, "output": 60.00},
    "o3-mini": {"input": 1.10, "cached": 0.55, "output": 4.40},
    # ─ Anthropic (cache-read ≈ 10% of input) ─
    "claude-opus-4": {"input": 15.00, "cached": 1.50, "output": 75.00},
    "claude-sonnet-4": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-haiku-4": {"input": 1.00, "cached": 0.10, "output": 5.00},
    "claude-3-5-sonnet": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "cached": 0.08, "output": 4.00},
    "claude-3-opus": {"input": 15.00, "cached": 1.50, "output": 75.00},
    "claude-3-sonnet": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "cached": 0.03, "output": 1.25},
    # ─ Google Gemini (cached ≈ 10% of input) ─
    "gemini-2.5-pro": {"input": 1.25, "cached": 0.125, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "cached": 0.075, "output": 2.50},
    "gemini-2.0-flash": {"input": 0.10, "cached": 0.025, "output": 0.40},
    "gemini-1.5-pro": {"input": 1.25, "cached": 0.3125, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "cached": 0.01875, "output": 0.30},
    # ─ Fallback ─
    "default": {"input": 1.00, "cached": 0.25, "output": 3.00},
}


def get_model_pricing(model: str) -> Dict[str, float]:
    """Return the pricing dict for a model via longest-substring match.

    Longest-match avoids the classic bug where "gpt-4o" shadows "gpt-4o-mini".
    Falls back to the "default" entry when nothing matches.
    """
    model_lower = (model or "").lower()
    best_key = None
    for key in MODEL_PRICING:
        if key == "default":
            continue
        if key in model_lower and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return MODEL_PRICING[best_key] if best_key else MODEL_PRICING["default"]


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> Dict[str, float]:
    """Estimate the USD cost of a call and the savings from cache reuse.

    `cached_tokens` is the subset of `input_tokens` served from cache (billed at
    the cached rate); the remainder is billed at the standard input rate.

    Returns a dict with input_cost, output_cost, total_cost, and saved (vs.
    paying the full input rate for the cached tokens).
    """
    p = get_model_pricing(model)
    cached = max(0, min(cached_tokens, input_tokens))
    uncached = input_tokens - cached

    input_cost = (uncached * p["input"] + cached * p["cached"]) / 1_000_000
    output_cost = (output_tokens * p["output"]) / 1_000_000
    saved = (cached * (p["input"] - p["cached"])) / 1_000_000

    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
        "saved": saved,
    }
