# -*- coding: utf-8 -*-
"""
Shared factory for turning a classified error into a chat message.

Replaces the pattern of hand-rolling `ChatMessageOption` lists at each error
call site (previously duplicated between the LLM-fatal-error prompt and the
action/token-limit prompt) with one factory that also carries the error's
category/code/severity onto the wire so the frontend can render it
consistently (see app/ui_layer/browser/frontend/src/constants/errorCategories.ts).
"""

from __future__ import annotations

import time
from typing import List, Optional

from agent_core.core.errors import ErrorInfoLike
from app.ui_layer.components.types import ChatMessage, ChatMessageOption


def build_error_chat_message(
    info: ErrorInfoLike,
    *,
    sender: str,
    session_id: str,
    extra_options: Optional[List[ChatMessageOption]] = None,
) -> ChatMessage:
    """Build a `ChatMessage` from a classified error.

    Action buttons come from `info.actions` (e.g. "Top up credits" with a
    `url`, or "Open settings" with an `action` verb); `extra_options` appends
    further buttons unrelated to the error itself (e.g. Retry/Change Model).
    """
    options: List[ChatMessageOption] = [
        ChatMessageOption(
            label=action.label,
            value=action.action or "",
            style="primary" if action.action else "default",
            url=action.url,
        )
        for action in info.actions
    ]
    if extra_options:
        options.extend(extra_options)

    category_value = getattr(info.category, "value", str(info.category))
    code = getattr(info, "code", None)
    severity = getattr(info, "severity", None)
    severity_value = getattr(severity, "value", None) if severity is not None else None

    return ChatMessage(
        sender=sender,
        content=info.message,
        style="error",
        timestamp=time.time(),
        session_id=session_id,
        options=options or None,
        error_category=category_value,
        error_code=code,
        error_severity=severity_value,
    )


def retry_change_model_options() -> List[ChatMessageOption]:
    """Options for a fatal LLM error: retry the same request, or switch model."""
    return [
        ChatMessageOption(label="Retry", value="llm_retry", style="primary"),
        ChatMessageOption(label="Change Model", value="llm_change_model", style="default"),
    ]


def continue_stop_options() -> List[ChatMessageOption]:
    """Options for an action/token limit prompt: reset and continue, or stop."""
    return [
        ChatMessageOption(label="Continue", value="continue_limit", style="primary"),
        ChatMessageOption(label="Stop", value="abort_limit", style="danger"),
    ]
