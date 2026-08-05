# -*- coding: utf-8 -*-
"""
`app/errors/envelope.py` — the shared snake_case wire-tag block used by every
non-chat error transport (action outputs, browser_adapter WS/REST, slash
commands). See app/errors/envelope.py's module docstring for the naming rule
this file exists to lock down: new envelopes are snake_case, and
`error_json_response`'s existing `error`/`error_category`/`error_code` keys
(shipped in the Phase 1 error-catalogue work) must never change shape.
"""

import json

from agent_core.core.errors import ErrorCategory, Severity
from app.errors import make_error
from app.errors.envelope import ERROR_FIELD_KEYS, error_fields, error_info_from_fields


class _MinimalInfo:
    """The minimal shape `ErrorInfoLike` requires structurally — no `code`
    or `severity` attribute at all (unlike `ErrorInfo`/`LLMErrorInfo`, which
    always have `severity` via a default). Exercises the `getattr` fallback
    in `error_fields()`."""

    def __init__(self) -> None:
        self.category = ErrorCategory.UNKNOWN
        self.title = "t"
        self.message = "m"
        self.actions = []


def test_error_field_keys_is_exact_literal():
    assert ERROR_FIELD_KEYS == {"error_category", "error_code", "error_severity"}


def test_error_fields_full_info_has_all_three_keys():
    info = make_error("CONFIG_NO_API_KEY", provider="OpenAI")
    fields = error_fields(info)
    assert set(fields) == {"error_category", "error_code", "error_severity"}
    assert fields["error_category"] == "config"
    assert fields["error_code"] == "CONFIG_NO_API_KEY"
    assert fields["error_severity"] == "error"


def test_error_fields_omits_missing_code_and_severity_not_null():
    fields = error_fields(_MinimalInfo())
    assert fields == {"error_category": "unknown"}
    assert "error_code" not in fields
    assert "error_severity" not in fields


def test_error_fields_is_always_a_subset_of_error_field_keys():
    for info in (make_error("CONNECTION_TIMEOUT", target="x"), _MinimalInfo()):
        assert set(error_fields(info)) <= ERROR_FIELD_KEYS


def test_error_info_from_fields_round_trip():
    info = make_error("VALIDATION_REQUIRED_FIELD", field="path")
    payload = {"message": info.message, **error_fields(info)}
    rebuilt = error_info_from_fields(payload)
    assert rebuilt is not None
    assert rebuilt.category is info.category
    assert rebuilt.code == info.code
    assert rebuilt.severity == info.severity
    assert rebuilt.message == info.message


def test_error_info_from_fields_returns_none_when_untagged():
    assert error_info_from_fields({"message": "plain message, no category"}) is None


def test_error_info_from_fields_prefers_message_over_error_key():
    payload = {"error_category": "auth", "message": "from message", "error": "from error"}
    info = error_info_from_fields(payload)
    assert info.message == "from message"


def test_error_info_from_fields_falls_back_to_error_key():
    payload = {"error_category": "auth", "error": "from error"}
    info = error_info_from_fields(payload)
    assert info.message == "from error"


def test_error_info_from_fields_unknown_category_degrades_to_unknown():
    info = error_info_from_fields({"error_category": "not_a_real_category", "message": "m"})
    assert info is not None
    assert info.category is ErrorCategory.UNKNOWN


def test_error_info_from_fields_bad_severity_falls_back_to_error():
    info = error_info_from_fields(
        {"error_category": "auth", "message": "m", "error_severity": "not_a_real_severity"}
    )
    assert info.severity is Severity.ERROR


def test_error_json_response_shape_unchanged():
    """Regression lock on the Phase 1 contract: `error`/`error_category`/
    `error_code` must stay byte-identical after the `error_fields()` refactor;
    `error_severity` is the one additive new key."""
    from app.errors.web import error_json_response

    info = make_error("CONNECTION_TIMEOUT", target="example.com")
    resp = error_json_response(info, status=504)
    assert resp.status == 504
    body = json.loads(resp.text)
    assert body["error"] == info.message
    assert body["error_category"] == "connection"
    assert body["error_code"] == "CONNECTION_TIMEOUT"
    assert body["error_severity"] == "error"
