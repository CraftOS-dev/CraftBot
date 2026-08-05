# -*- coding: utf-8 -*-
"""
Backend error-catalogue primitives (agent_core/core/errors.py) and the
app-layer codebook (app/errors/codebook.py).
"""

import string

import pytest

from agent_core.core.errors import (
    ClassifiedError,
    ErrorAction,
    ErrorCategory,
    ErrorInfo,
    Severity,
    is_transient,
    redact,
)
from app.errors import CatalogError, error_from_exception, make_error, verbatim
from app.errors.codebook import _CODEBOOK


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


def test_llm_consecutive_failure_error_auto_derives_immediate_from_count():
    """A raise site with failure_count=1 must never say "consecutive
    failures" even if it forgot to pass is_immediate=True — e.g. the hard
    per-call timeout in app/subagent/runner.py raises with count=1 and no
    last_error_info, going through this same constructor."""
    from agent_core.core.impl.llm.errors import (
        LLMConsecutiveFailureError,
        MSG_CONSECUTIVE_FAILURE,
        MSG_FAILED_IMMEDIATELY,
    )

    single = LLMConsecutiveFailureError(1)
    assert single.is_immediate is True
    assert MSG_FAILED_IMMEDIATELY in str(single)

    multiple = LLMConsecutiveFailureError(5)
    assert multiple.is_immediate is False
    assert MSG_CONSECUTIVE_FAILURE in str(multiple)


# ─── Phase 2: codebook expansion (verbatim / error_from_exception / new codes) ──


@pytest.mark.parametrize("code", sorted(_CODEBOOK.keys()))
def test_every_codebook_entry_formats_without_key_error(code):
    """Every `_CODEBOOK` template must format cleanly given exactly the
    fields it declares — derived from the template itself via
    `string.Formatter`, so this stays correct as codes are added without
    needing a hand-maintained field list here."""
    spec = _CODEBOOK[code]
    formatter = string.Formatter()
    field_names = {fname for _, fname, _, _ in formatter.parse(spec.message_template) if fname}
    kwargs = {name: f"<{name}>" for name in field_names}

    info = make_error(code, **kwargs)

    assert info.category is spec.category
    assert info.code == code
    for name in field_names:
        assert f"<{name}>" in info.message


def test_verbatim_preserves_exact_message():
    """`verbatim()` must not reword the text it's given — Tier-1 action
    sites (model-instructional strings like stream_edit.py's "old_string
    appears N times...") depend on this to retag without touching wording
    the agent relies on to self-correct."""
    text = "old_string appears 3 times in file. Either provide more context to select a unique match."
    info = verbatim(text, category=ErrorCategory.VALIDATION, code="EDIT_AMBIGUOUS_MATCH")
    assert info.message == text
    assert info.category is ErrorCategory.VALIDATION
    assert info.code == "EDIT_AMBIGUOUS_MATCH"
    assert info.actions == []


def test_verbatim_default_severity_is_error():
    info = verbatim("m", category=ErrorCategory.NOT_FOUND, code="X")
    assert info.severity is Severity.ERROR


def test_error_from_exception_returns_classified_error_info_untouched():
    """An already-`ClassifiedError` must never be re-classified — that would
    demote it toward UNKNOWN via `str(exc)`, discarding the category it
    already carries."""
    original = make_error("CONFIG_NO_API_KEY", provider="OpenAI")
    wrapped = ClassifiedError(original)
    result = error_from_exception(wrapped, code="COMMAND_FAILED", command="x")
    assert result is original


@pytest.mark.parametrize(
    "exc,expected_category",
    [
        (FileNotFoundError("boom"), ErrorCategory.NOT_FOUND),
        (PermissionError("boom"), ErrorCategory.PERMISSION),
        (IsADirectoryError("boom"), ErrorCategory.VALIDATION),
        (NotADirectoryError("boom"), ErrorCategory.VALIDATION),
        (TimeoutError("boom"), ErrorCategory.CONNECTION),
        (ConnectionError("boom"), ErrorCategory.CONNECTION),
        (ValueError("boom"), ErrorCategory.VALIDATION),
        (TypeError("boom"), ErrorCategory.VALIDATION),
        (KeyError("boom"), ErrorCategory.VALIDATION),
    ],
)
def test_error_from_exception_category_from_exception_type(exc, expected_category):
    """The exception's own type outranks the codebook code's declared
    category — FILE_READ_FAILED defaults to INTERNAL, but a real
    FileNotFoundError must still come back NOT_FOUND."""
    info = error_from_exception(exc, code="FILE_READ_FAILED", path="/some/path.txt")
    assert info.category is expected_category


def test_error_from_exception_falls_back_to_codebook_category_when_unmapped():
    class _CustomError(Exception):
        pass

    info = error_from_exception(_CustomError("boom"), code="FILE_READ_FAILED", path="/x")
    assert info.category is ErrorCategory.INTERNAL  # FILE_READ_FAILED's own declared category


def test_error_from_exception_explicit_category_wins_when_exception_type_unmapped():
    class _CustomError(Exception):
        pass

    info = error_from_exception(
        _CustomError("boom"), code="FILE_READ_FAILED", category=ErrorCategory.SERVER, path="/x"
    )
    assert info.category is ErrorCategory.SERVER


def test_error_from_exception_redacts_detail_not_semantic_kwargs():
    """`detail` is auto-filled from `str(exc)` and redacted like any other
    `detail` kwarg; `path` (a semantic, already-user-known value) must
    survive untouched — the redaction carve-out ported call sites rely on."""
    exc = FileNotFoundError("/home/user/secret.py")
    info = error_from_exception(exc, code="FILE_READ_FAILED", path="/keep/this/path.txt")
    assert "/keep/this/path.txt" in info.message
    assert "/home/user/secret.py" not in info.message


def test_error_from_exception_explicit_detail_not_overwritten():
    info = error_from_exception(ValueError("raw"), code="FILE_READ_FAILED", path="/x", detail="curated detail")
    assert "curated detail" in info.message
    assert "raw" not in info.message
