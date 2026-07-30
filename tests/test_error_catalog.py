# -*- coding: utf-8 -*-
"""
Backend error-catalogue primitives (agent_core/core/errors.py) and the
app-layer codebook (app/errors/codebook.py).
"""

import pytest

from agent_core.core.errors import (
    ErrorAction,
    ErrorCategory,
    ErrorInfo,
    Severity,
    is_transient,
    redact,
)
from app.errors import CatalogError, make_error


def test_error_info_to_dict_serializes_enums():
    info = ErrorInfo(
        category=ErrorCategory.AUTH,
        code="TEST_AUTH",
        title="t",
        message="m",
        severity=Severity.CRITICAL,
        actions=[ErrorAction(label="Open settings", action="open_settings_model")],
    )
    d = info.to_dict()
    assert d["category"] == "auth"
    assert d["severity"] == "critical"
    assert d["actions"][0]["label"] == "Open settings"


def test_error_info_is_transient_property():
    assert ErrorInfo(category=ErrorCategory.AUTH, code="c", title="t", message="m").is_transient is False
    assert ErrorInfo(category=ErrorCategory.SERVER, code="c", title="t", message="m").is_transient is True


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.AUTH,
        ErrorCategory.CREDIT,
        ErrorCategory.QUOTA,
        ErrorCategory.MODEL,
        ErrorCategory.BLOCKED,
        ErrorCategory.BAD_REQUEST,
    ],
)
def test_fail_fast_categories_are_not_transient(category):
    assert is_transient(category) is False


@pytest.mark.parametrize(
    "category",
    [ErrorCategory.RATE_LIMIT, ErrorCategory.SERVER, ErrorCategory.CONNECTION, ErrorCategory.UNKNOWN],
)
def test_transient_categories_are_transient(category):
    assert is_transient(category) is True


def test_redact_strips_paths_emails_urls_ips():
    raw = (
        "Failed reading /home/user/secret.py for user@example.com "
        "at https://internal.host/api from 10.0.0.5"
    )
    out = redact(raw)
    assert "/home/user/secret.py" not in out
    assert "user@example.com" not in out
    assert "internal.host" not in out
    assert "10.0.0.5" not in out
    assert "[REDACTED]" in out


def test_redact_truncates_long_text():
    raw = "x" * 1000
    out = redact(raw, max_length=50)
    assert len(out) == 53  # 50 chars + "..."
    assert out.endswith("...")


def test_make_error_round_trip():
    info = make_error("CONFIG_NO_API_KEY", provider="OpenRouter")
    assert info.category is ErrorCategory.CONFIG
    assert info.code == "CONFIG_NO_API_KEY"
    assert "OpenRouter" in info.message
    assert info.actions[0].action == "open_settings_model"


def test_make_error_unknown_code_raises():
    with pytest.raises(KeyError):
        make_error("NOT_A_REAL_CODE")


def test_make_error_missing_template_arg_raises():
    with pytest.raises(KeyError):
        make_error("CONFIG_NO_API_KEY")  # missing provider=


def test_catalog_error_message_matches_info():
    info = make_error("CONNECTION_TIMEOUT", target="example.com")
    err = CatalogError(info)
    assert str(err) == info.message
    assert err.info is info


def test_llm_error_info_gets_auto_derived_code():
    from agent_core.core.impl.llm.errors import classify_llm_error

    info = classify_llm_error(RuntimeError("boom"))
    assert info.code == "LLM_UNKNOWN"
    assert info.category is ErrorCategory.UNKNOWN


def test_llm_consecutive_failure_error_uses_immediate_message_when_flagged():
    from agent_core.core.impl.llm.errors import (
        LLMConsecutiveFailureError,
        MSG_FAILED_IMMEDIATELY,
    )

    err = LLMConsecutiveFailureError(1, is_immediate=True)
    assert MSG_FAILED_IMMEDIATELY in str(err)
