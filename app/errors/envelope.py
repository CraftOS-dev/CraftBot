# -*- coding: utf-8 -*-
"""Shared wire tags for dict-shaped error envelopes.

`ErrorInfo`/`ErrorInfoLike` (agent_core/core/errors.py) is the in-process
representation of a classified error. This module is the one place that
turns it into the flat snake_case tag block every non-chat transport
(action outputs, browser_adapter WS/REST, slash-command events) uses.

Naming rule: error fields adopt the case convention of the envelope they're
embedded in, never the convention of `ErrorInfo` itself. `ChatMessage.to_dict()`
(app/ui_layer/components/types.py) is camelCase (`errorCategory`) because it
shipped that way in the Phase 1 error-catalogue work; `error_json_response`
(app/errors/web.py) is snake_case for the same reason. Every NEW envelope in
Phase 2 is snake_case, matching its neighbouring keys (`return_code`,
`content_length`, `project_id`). `ErrorInfo.to_dict()` stays snake_case too,
but it's a logging/debug serializer — never put it on a wire directly, use
`error_fields()` instead.

No `error_actions` key: nothing on the action, WS, or toast transport renders
buttons in this phase (chat bubbles get theirs from `build_error_chat_message`
instead, unchanged). Shipping a field no consumer reads is exactly how
`errorSeverity` sat dead on the ChatMessage wire after Phase 1 — don't repeat
that here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_core.core.errors import ErrorCategory, ErrorInfo, ErrorInfoLike, Severity

# Keys `error_fields()` may emit. `error_category` is the only one guaranteed
# present; `error_code`/`error_severity` are omitted when absent rather than
# emitted as null (see module docstring and error_fields' own docstring).
ERROR_FIELD_KEYS = frozenset({"error_category", "error_code", "error_severity"})


def error_fields(info: ErrorInfoLike) -> Dict[str, str]:
    """Additive snake_case tags for any dict-shaped error envelope.

    `{**payload, **error_fields(info)}` never introduces a null-valued key an
    existing consumer would have to guard against — a missing `code`/`severity`
    is simply left out.

    `code` and `severity` are NOT on the `ErrorInfoLike` Protocol (`LLMErrorInfo`
    satisfies it structurally without them), so both are read with `getattr`,
    matching the existing precedent in `error_json_response` (app/errors/web.py)
    and `build_error_chat_message` (app/ui_layer/components/error_message.py).
    """
    out: Dict[str, str] = {"error_category": getattr(info.category, "value", str(info.category))}

    code = getattr(info, "code", None)
    if code:
        out["error_code"] = code

    severity = getattr(info, "severity", None)
    severity_value = getattr(severity, "value", None) if severity is not None else None
    if severity_value:
        out["error_severity"] = severity_value

    return out


def error_info_from_fields(
    data: Dict[str, Any], *, message_keys: tuple = ("message", "error")
) -> Optional[ErrorInfo]:
    """Rebuild an `ErrorInfo` from a dict previously widened by `error_fields()`.

    Returns `None` when `data` carries no `error_category` — the caller should
    fall back to whatever untagged-payload handling it had before this existed
    (e.g. `app/ui_layer/adapters/base.py::_handle_error_message`'s legacy path).
    An unrecognized category value degrades to `ErrorCategory.UNKNOWN` rather
    than raising, since this runs on data that already crossed a boundary.
    """
    raw_category = data.get("error_category")
    if not raw_category:
        return None

    try:
        category = ErrorCategory(raw_category)
    except ValueError:
        category = ErrorCategory.UNKNOWN

    try:
        severity = Severity(data.get("error_severity") or Severity.ERROR.value)
    except ValueError:
        severity = Severity.ERROR

    message = ""
    for key in message_keys:
        value = data.get(key)
        if value:
            message = value
            break

    return ErrorInfo(
        category=category,
        code=data.get("error_code") or "",
        title=data.get("error_title") or "",
        message=message,
        severity=severity,
    )
