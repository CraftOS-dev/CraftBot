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

from agent_core.core.errors import (
    ClassifiedError,
    ErrorAction,
    ErrorCategory,
    ErrorInfo,
    Severity,
    redact,
)


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


def _register_mini_browser_errors() -> None:
    """Add every Mini Browser code to the codebook.

    ``app/mini_browser/errors.py`` ``ERROR_SPECS`` is the single source of
    truth for those codes; registering them here makes ``make_error`` work for
    them like for any other app error. A broken Mini Browser package must not
    take the whole codebook down with it (Mini Browser errors then fall back
    to formatting their spec directly, see app/mini_browser/errors.py).
    """
    try:
        from app.mini_browser.errors import ERROR_SPECS
    except Exception:
        return

    for code, (category, severity, title, template) in ERROR_SPECS.items():
        try:
            spec_category = ErrorCategory(category)
        except ValueError:
            spec_category = ErrorCategory.INTERNAL
        try:
            spec_severity = Severity(severity)
        except ValueError:
            spec_severity = Severity.ERROR
        _CODEBOOK[code] = _Spec(
            category=spec_category,
            severity=spec_severity,
            title=title,
            message_template=template,
        )


_register_mini_browser_errors()


def make_error(code: str, **fmt_kwargs) -> ErrorInfo:
    """Build a structured `ErrorInfo` from a codebook entry.

    `fmt_kwargs` fill the entry's message template (e.g. `provider=`,
    `target=`). A missing key raises `KeyError` here, at the call site,
    rather than shipping a broken `"{provider}"` literal to the UI.

    `detail` is redacted before formatting — by convention it's raw
    exception text (`str(e)`), unlike `provider`/`target` which are
    semantic, already-user-known values.
    """
    spec = _CODEBOOK.get(code)
    if spec is None:
        raise KeyError(
            f"Unknown error code {code!r} — add it to app/errors/codebook.py"
        )
    if "detail" in fmt_kwargs:
        fmt_kwargs["detail"] = redact(str(fmt_kwargs["detail"]))
    message = spec.message_template.format(**fmt_kwargs)
    return ErrorInfo(
        category=spec.category,
        code=code,
        title=spec.title,
        message=message,
        severity=spec.severity,
        actions=spec.actions(**fmt_kwargs),
    )


class CatalogError(ClassifiedError):
    """Drop-in replacement for `raise RuntimeError(f"...")` at call sites
    that have been migrated onto the codebook."""
