# -*- coding: utf-8 -*-
"""
`LLMInterface._register_failure` is the single chokepoint for consecutive-
failure bookkeeping (agent_core/core/impl/llm/interface.py). Non-transient
categories (auth, credit, quota, model, blocked, bad_request) must fail fast
on the very first occurrence instead of consuming the retry budget; transient
categories (rate_limit, server, connection, unknown) keep the existing
5-attempt budget.

Exercises `_register_failure` directly against a minimal stand-in carrying
just the attributes it reads/writes, rather than constructing a full
LLMInterface (which requires provider/model setup unrelated to this logic).
"""

import pytest

from agent_core.core.errors import ErrorCategory, FAIL_FAST_CATEGORIES
from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError, LLMErrorInfo
from agent_core.core.impl.llm.interface import LLMInterface

TRANSIENT_CATEGORIES = [
    ErrorCategory.RATE_LIMIT,
    ErrorCategory.SERVER,
    ErrorCategory.CONNECTION,
    ErrorCategory.UNKNOWN,
]


class _FakeInterface:
    def __init__(self):
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5


def _info(category: ErrorCategory) -> LLMErrorInfo:
    return LLMErrorInfo(category=category, title="t", message="m", provider="test")


@pytest.mark.parametrize("category", sorted(FAIL_FAST_CATEGORIES, key=lambda c: c.value))
def test_fail_fast_categories_abort_on_first_failure(category):
    fake = _FakeInterface()
    with pytest.raises(LLMConsecutiveFailureError) as exc_info:
        LLMInterface._register_failure(fake, error_info=_info(category))

    err = exc_info.value
    assert err.is_immediate is True
    assert err.failure_count == 1
    assert err.last_error_info.category is category
    # The retry counter itself is never touched for a fail-fast category.
    assert fake._consecutive_failures == 0


@pytest.mark.parametrize("category", TRANSIENT_CATEGORIES)
def test_transient_categories_keep_retry_budget(category):
    fake = _FakeInterface()
    for _ in range(4):
        LLMInterface._register_failure(fake, error_info=_info(category))  # must not raise yet
    assert fake._consecutive_failures == 4

    with pytest.raises(LLMConsecutiveFailureError) as exc_info:
        LLMInterface._register_failure(fake, error_info=_info(category))

    err = exc_info.value
    assert err.is_immediate is False
    assert err.failure_count == 5


def test_missing_error_info_defaults_to_unknown_and_retries():
    fake = _FakeInterface()
    LLMInterface._register_failure(fake, error_info=None)
    assert fake._consecutive_failures == 1


def test_fail_fast_categories_do_not_overlap_transient_set():
    assert FAIL_FAST_CATEGORIES.isdisjoint(TRANSIENT_CATEGORIES)
    # Every ErrorCategory value used by the LLM classifier is accounted for
    # by exactly one of the two buckets (UNKNOWN counts as transient).
    llm_categories = {
        ErrorCategory.AUTH,
        ErrorCategory.CREDIT,
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.QUOTA,
        ErrorCategory.MODEL,
        ErrorCategory.BAD_REQUEST,
        ErrorCategory.BLOCKED,
        ErrorCategory.SERVER,
        ErrorCategory.CONNECTION,
        ErrorCategory.UNKNOWN,
        # CONFIG: local precondition failures (e.g. "client was not
        # initialised" — no API key configured) — see
        # _classify_local_config in agent_core/core/impl/llm/errors.py.
        ErrorCategory.CONFIG,
    }
    assert FAIL_FAST_CATEGORIES | set(TRANSIENT_CATEGORIES) == llm_categories
