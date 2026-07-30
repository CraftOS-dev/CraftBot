# -*- coding: utf-8 -*-
"""
App-layer error codebook.

Curated, representative entries for the highest-duplication non-LLM call
sites (see docs/error_handling_report.md and the error-catalogue plan). This
is deliberately a small proof-of-adoption set, not exhaustive coverage of
every hand-rolled error string in the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from agent_core.core.errors import ErrorAction, ErrorCategory, ErrorInfo, Severity


@dataclass(frozen=True)
class _Spec:
    category: ErrorCategory
    severity: Severity
    title: str
    message_template: str
    actions: Callable[..., List[ErrorAction]] = lambda **_: []


def _settings_action(**_kwargs) -> List[ErrorAction]:
    return [ErrorAction(label="Open settings", action="open_settings_model")]


_CODEBOOK: Dict[str, _Spec] = {
    "CONFIG_NO_API_KEY": _Spec(
        category=ErrorCategory.CONFIG,
        severity=Severity.ERROR,
        title="No API key configured",
        message_template="No {provider} API key configured. Add one in Settings.",
        actions=_settings_action,
    ),
    "CONFIG_INVALID_API_KEY": _Spec(
        category=ErrorCategory.AUTH,
        severity=Severity.ERROR,
        title="Invalid API key",
        message_template="The {provider} API key was rejected. Check your key in Settings.",
        actions=_settings_action,
    ),
    "CONNECTION_FAILED": _Spec(
        category=ErrorCategory.CONNECTION,
        severity=Severity.ERROR,
        title="Connection failed",
        message_template="Could not reach {target}. {detail}",
    ),
    "CONNECTION_TIMEOUT": _Spec(
        category=ErrorCategory.CONNECTION,
        severity=Severity.ERROR,
        title="Request timed out",
        message_template="{target} did not respond in time. Try again.",
    ),
    "VLM_PROVIDER_UNAVAILABLE": _Spec(
        category=ErrorCategory.CONFIG,
        severity=Severity.ERROR,
        title="Vision model unavailable",
        message_template=(
            "VLM is not available for provider '{provider}'. Switch VLM provider "
            "in Settings to one that supports vision (e.g. anthropic, openai, "
            "gemini, byteplus)."
        ),
        actions=_settings_action,
    ),
    "VLM_PROVIDER_NOT_INITIALIZED": _Spec(
        category=ErrorCategory.CONFIG,
        severity=Severity.ERROR,
        title="Vision model not configured",
        message_template=(
            "VLM for provider '{provider}' is not initialized. Check that the "
            "API key is configured in Settings."
        ),
        actions=_settings_action,
    ),
    "PROXY_ERROR": _Spec(
        category=ErrorCategory.SERVER,
        severity=Severity.ERROR,
        title="Proxy request failed",
        message_template="{detail}",
    ),
    "SUBAGENT_TIMEOUT": _Spec(
        category=ErrorCategory.CONNECTION,
        severity=Severity.ERROR,
        title="Sub-agent call timed out",
        message_template="The sub-agent LLM call did not respond within {timeout}s.",
    ),
}


def make_error(code: str, **fmt_kwargs) -> ErrorInfo:
    """Build a structured `ErrorInfo` from a codebook entry.

    `fmt_kwargs` fill the entry's message template (e.g. `provider=`,
    `target=`). A missing key raises `KeyError` here, at the call site,
    rather than shipping a broken `"{provider}"` literal to the UI.
    """
    spec = _CODEBOOK.get(code)
    if spec is None:
        raise KeyError(f"Unknown error code {code!r} — add it to app/errors/codebook.py")
    message = spec.message_template.format(**fmt_kwargs)
    return ErrorInfo(
        category=spec.category,
        code=code,
        title=spec.title,
        message=message,
        severity=spec.severity,
        actions=spec.actions(**fmt_kwargs),
    )


class CatalogError(Exception):
    """Drop-in replacement for `raise RuntimeError(f"...")` at call sites
    that have been migrated onto the codebook."""

    def __init__(self, info: ErrorInfo):
        self.info = info
        super().__init__(info.message)
