"""Standard return-envelope types for craftos_integrations.

Most client methods (and the helpers in ``helpers.http``) return one of two shapes:

  - **Success**: ``{"ok": True, "result": <any>}``
  - **Failure**: ``{"error": <str>, "details": <any>}`` — ``details`` is optional.

These are the runtime shapes — using these aliases as return annotations is a
type-check hint only, not a runtime check.

Three integrations (Slack, Telegram Bot, Notion) intentionally diverge: their
file-private call helpers return the raw API body on success so callers can
read flat fields like ``result["channels"]`` directly. Those still return
``Dict[str, Any]`` and are documented in their respective files.
"""

from __future__ import annotations

from typing import Any, TypedDict, Union

try:
    from typing import NotRequired  # 3.11+
except ImportError:
    from typing_extensions import NotRequired  # type: ignore[assignment]


class Ok(TypedDict):
    ok: bool  # always True for the Ok shape
    result: Any


class Err(TypedDict):
    error: str
    details: NotRequired[Any]


Result = Union[Ok, Err]
