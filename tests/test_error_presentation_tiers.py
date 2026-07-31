# -*- coding: utf-8 -*-
"""
Presentation-tier split for react-loop errors (app/agent_base.py):

- "Minor" tier: a recognized, user-actionable failure (bad key, no credits,
  misconfigured provider) — shown as a short, calm message. Signaled by
  either an `LLMConsecutiveFailureError.last_error_info` or a
  `ClassifiedError` (agent_core/core/errors.py) anywhere in the exception
  chain.
- "Critical" tier: anything unclassified — a genuine bug/crash — shown with
  full raw detail.

Also covers the action router's message cleanup: it used to leak an
"Unable to generate action decision on attempt N:" wrapper (with a
duplicated trailing period) into the user-facing text; it now raises a
`ClassifiedError` with a clean message instead.
"""

import asyncio

import pytest

from agent_core.core.errors import ClassifiedError, ErrorCategory, ErrorInfo, Severity
from agent_core.core.impl.action.router import ActionRouter
from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError, LLMErrorInfo
from app.agent_base import AgentBase
from app.errors import CatalogError, make_error


# ─── ClassifiedError / CatalogError ────────────────────────────────────────


def test_classified_error_carries_info_and_message():
    info = ErrorInfo(category=ErrorCategory.CONFIG, code="X", title="t", message="m")
    err = ClassifiedError(info)
    assert err.info is info
    assert str(err) == "m"


def test_catalog_error_is_a_classified_error():
    info = make_error("CONFIG_NO_API_KEY", provider="OpenRouter")
    err = CatalogError(info)
    assert isinstance(err, ClassifiedError)
    assert err.info is info


# ─── AgentBase._classify_react_error ───────────────────────────────────────


def test_classify_react_error_fatal_with_classified_info():
    info = LLMErrorInfo(category=ErrorCategory.AUTH, title="t", message="m", provider="p")
    exc = LLMConsecutiveFailureError(1, last_error_info=info, is_immediate=True)

    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(exc)

    assert is_fatal is True
    assert fatal_exc is exc
    assert classified_info is info


def test_classify_react_error_fatal_without_classified_info():
    """A fatal error with no classified info (e.g. classification itself
    raised) must still be recognized as fatal, but with no info — the
    caller falls back to the critical/unclassified presentation."""
    exc = LLMConsecutiveFailureError(1)

    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(exc)

    assert is_fatal is True
    assert fatal_exc is exc
    assert classified_info is None


def test_classify_react_error_non_fatal_classified_error_in_chain():
    """A ClassifiedError raised (e.g. by the action router after its own
    retry budget is exhausted) must be recognized as minor-tier, not fatal —
    even when chained under an outer exception."""
    info = ErrorInfo(category=ErrorCategory.UNKNOWN, code="X", title="t", message="clean message")
    try:
        try:
            raise ClassifiedError(info)
        except ClassifiedError as inner:
            raise RuntimeError("outer wrapper") from inner
    except RuntimeError as outer:
        is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(outer)

    assert is_fatal is False
    assert fatal_exc is None
    assert classified_info is info


def test_classify_react_error_unclassified_exception():
    """A bare, unrecognized exception (a genuine bug) must fall through to
    critical/unclassified — no fatal flag, no classified info."""
    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(
        KeyError("something broke")
    )

    assert is_fatal is False
    assert fatal_exc is None
    assert classified_info is None


def test_critical_fallback_info_is_critical_severity():
    info = AgentBase._critical_fallback_info("KeyError: 'boom'")
    assert info.severity is Severity.CRITICAL
    assert info.category is ErrorCategory.INTERNAL
    assert "boom" in info.message


# ─── Action router: clean message, no attempt-number leakage ──────────────


class _FakeContextEngine:
    def make_prompt(self, **kwargs):
        return "system prompt", None


class _FakeLLMInterface:
    """Always fails with the same RuntimeError, like an uninitialized client."""

    provider = "anthropic"
    model = "test-model"

    async def generate_response_async(self, system_prompt, user_prompt, prompt_name=None):
        raise RuntimeError("Anthropic client was not initialised.")


def test_router_wraps_persistent_llm_failure_as_classified_error():
    router = ActionRouter(
        action_library=object(),
        llm_interface=_FakeLLMInterface(),
        context_engine=_FakeContextEngine(),
    )

    with pytest.raises(ClassifiedError) as exc_info:
        asyncio.run(router._prompt_for_decision("do something"))

    info = exc_info.value.info
    # No "Unable to generate action decision on attempt N:" wrapper, and no
    # duplicated period from concatenating the original "...initialised."
    # with the appended hint.
    assert "attempt" not in info.message.lower()
    assert ".." not in info.message
    assert info.message == (
        "Anthropic client was not initialised. Check LLM configuration, "
        "API credentials, and service availability."
    )
