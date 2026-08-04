# -*- coding: utf-8 -*-
"""
`classify_llm_error` (agent_core/core/impl/llm/errors.py) must recognize the
"client was not initialised" precondition failures raised by
agent_core/core/impl/llm/interface.py before any network call (no API key
configured) as `ErrorCategory.CONFIG` — a permanent local misconfiguration,
not a transient provider error — so `_register_failure` fails fast on the
first occurrence instead of burning the 5-attempt retry budget (see
tests/test_llm_fail_fast.py).

Also covers the Gemini-substring dispatch ordering: "Gemini client was not
initialised." contains "Gemini" and must not be misrouted to the
Gemini-API-shaped classifier.

Also covers `_classify_openai_compat`'s CREDIT-vs-RATE_LIMIT disambiguation:
the OpenAI SDK raises the same `RateLimitError` (HTTP 429) for both actual
rate-limiting and credit/quota exhaustion, normally split apart via the
`code == "insufficient_quota"` body field — but some accounts return 429 with
a plain-language credit message and no matching code, which used to surface
as "Rate limited... try again shortly", actively wrong advice for a
permanently out-of-funds account.
"""

import httpx
import pytest

try:
    import openai
except ImportError:  # pragma: no cover
    openai = None

from agent_core.core.errors import ErrorCategory, FAIL_FAST_CATEGORIES
from agent_core.core.impl.llm.errors import classify_llm_error


@pytest.mark.parametrize(
    "provider,message",
    [
        ("anthropic", "Anthropic client was not initialised."),
        ("gemini", "Gemini client was not initialised."),
        ("bedrock", "Bedrock client was not initialised."),
        ("openai", "OpenAI client was not initialised."),
    ],
)
def test_local_init_failure_classified_as_config(provider, message):
    info = classify_llm_error(RuntimeError(message), provider=provider)

    assert info.category is ErrorCategory.CONFIG
    assert info.category in FAIL_FAST_CATEGORIES
    assert info.message == (
        f"{message.rstrip('.')}. Check LLM configuration, API credentials, "
        f"and service availability."
    )


def test_local_init_failure_code_is_auto_derived():
    info = classify_llm_error(
        RuntimeError("Anthropic client was not initialised."), provider="anthropic"
    )
    assert info.code == "LLM_CONFIG"


def test_unrelated_runtime_error_still_falls_back_to_unknown():
    info = classify_llm_error(RuntimeError("boom"), provider="anthropic")
    assert info.category is ErrorCategory.UNKNOWN


# ─── OpenAI CREDIT vs RATE_LIMIT disambiguation ────────────────────────────


def _openai_rate_limit_error(body: dict) -> "openai.RateLimitError":
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return openai.RateLimitError(str(body), response=response, body=body)


@pytest.mark.skipif(openai is None, reason="openai SDK not installed")
def test_openai_credit_exhaustion_message_reclassified_as_credit():
    body = {
        "message": (
            "You have no credits remaining. Add credits to continue using "
            "the API at https://platform.openai.com/settings/organization/billing/."
        )
    }
    info = classify_llm_error(_openai_rate_limit_error(body), provider="openai")

    assert info.category is ErrorCategory.CREDIT
    assert info.message.startswith("Out of credits.")
    assert "Rate limited" not in info.message


@pytest.mark.skipif(openai is None, reason="openai SDK not installed")
def test_openai_genuine_rate_limit_stays_rate_limit():
    body = {"message": "Rate limit reached for requests", "code": "rate_limit_exceeded"}
    info = classify_llm_error(_openai_rate_limit_error(body), provider="openai")

    assert info.category is ErrorCategory.RATE_LIMIT


@pytest.mark.skipif(openai is None, reason="openai SDK not installed")
def test_openai_insufficient_quota_code_still_classified_as_credit():
    body = {"message": "You exceeded your current quota.", "code": "insufficient_quota"}
    info = classify_llm_error(_openai_rate_limit_error(body), provider="openai")

    assert info.category is ErrorCategory.CREDIT
