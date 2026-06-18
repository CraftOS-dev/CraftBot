# -*- coding: utf-8 -*-
"""
Token counting utilities using tiktoken.

Provides a cached tokenizer and token counting functions used
across agent_core and app layers.
"""

import tiktoken

# Ensure tiktoken extension encodings (cl100k_base, etc.) are registered.
# Required for tiktoken >= 0.12 and PyInstaller frozen builds.
try:
    import tiktoken_ext.openai_public  # noqa: F401
except ImportError:
    pass

_tokenizer = None


def _get_tokenizer():
    """Get or create the tiktoken tokenizer (cached for performance)."""
    global _tokenizer
    if _tokenizer is None:
        try:
            _tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # Fallback: use o200k_base if cl100k_base is unavailable
            _tokenizer = tiktoken.get_encoding("o200k_base")
    return _tokenizer


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string using tiktoken."""
    if not text:
        return 0
    return len(_get_tokenizer().encode(text))


def billable_tokens(response: dict) -> int:
    """Tokens that should count toward the per-task ``token_count`` limit.

    The conversation context is re-sent on every turn, so the provider reports
    a large ``input_tokens`` each call — but the bulk of that is cache reads of
    bytes we already paid for on previous turns. Charging the full input on
    every turn drains the task token budget in a handful of turns even though
    almost no *new* work is being done. We therefore bill only the uncached
    portion: ``tokens_used - cached_tokens`` (clamped at 0).

    This is for the *limit* counter only — display/attribution totals still
    record true usage (including cache reads) via the usage-reporting hooks.

    Args:
        response: A processed response dict carrying ``tokens_used`` and,
            optionally, ``cached_tokens`` (defaults to 0 when absent).
    """
    used = int(response.get("tokens_used", 0) or 0)
    cached = int(response.get("cached_tokens", 0) or 0)
    return max(0, used - cached)
