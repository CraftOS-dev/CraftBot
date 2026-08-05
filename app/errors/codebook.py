# -*- coding: utf-8 -*-
"""
App-layer error codebook.

Curated entries for the highest-duplication non-LLM call sites across the
app: provider/config guards (Phase 1), and action handlers, browser_adapter,
slash commands, and CLI output (Phase 2 — see docs/error_handling_report.md
and the error-catalogue plan). This stays curated, not exhaustive: a code
earns its place here at roughly 5+ call sites, or when it needs an
`ErrorAction` (a settings-link, etc.) that a one-off `verbatim()` call can't
carry. Everything below that bar stays a `verbatim()` call at its call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Type

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
    # ─── Phase 2: action handlers, browser_adapter, commands, CLI ──────────
    "VALIDATION_REQUIRED_FIELD": _Spec(
        category=ErrorCategory.VALIDATION,
        severity=Severity.ERROR,
        title="Missing required input",
        message_template="{field} is required.",
    ),
    "VALIDATION_BAD_VALUE": _Spec(
        category=ErrorCategory.VALIDATION,
        severity=Severity.ERROR,
        title="Invalid input",
        message_template="Invalid {field}: {reason}",
    ),
    "NOT_FOUND_PATH": _Spec(
        category=ErrorCategory.NOT_FOUND,
        severity=Severity.ERROR,
        title="File not found",
        message_template="No such file or directory: {path}",
    ),
    "NOT_FOUND_NAMED": _Spec(
        category=ErrorCategory.NOT_FOUND,
        severity=Severity.ERROR,
        title="Not found",
        message_template="{kind} not found: {name}",
    ),
    "PERMISSION_DENIED_PATH": _Spec(
        category=ErrorCategory.PERMISSION,
        severity=Severity.ERROR,
        title="Permission denied",
        message_template="Permission denied accessing {path}. {detail}",
    ),
    "COMPONENT_NOT_INITIALIZED": _Spec(
        category=ErrorCategory.CONFIG,
        severity=Severity.ERROR,
        title="Component unavailable",
        message_template="{component} is not initialized.",
        actions=_settings_action,
    ),
    "PROVIDER_UNAVAILABLE": _Spec(
        category=ErrorCategory.CONFIG,
        severity=Severity.ERROR,
        title="Provider unavailable",
        message_template="{provider} is not available. {detail}",
        actions=_settings_action,
    ),
    "SHELL_TIMEOUT": _Spec(
        category=ErrorCategory.CONNECTION,
        severity=Severity.ERROR,
        title="Command timed out",
        message_template="Command timed out after {timeout}s.",
    ),
    "FILE_READ_FAILED": _Spec(
        category=ErrorCategory.INTERNAL,
        severity=Severity.ERROR,
        title="Could not read file",
        message_template="Could not read {path}. {detail}",
    ),
    "FILE_WRITE_FAILED": _Spec(
        category=ErrorCategory.INTERNAL,
        severity=Severity.ERROR,
        title="Could not write file",
        message_template="Could not write {path}. {detail}",
    ),
    "PROCESS_LAUNCH_FAILED": _Spec(
        category=ErrorCategory.INTERNAL,
        severity=Severity.ERROR,
        title="Could not start process",
        message_template="Could not start {process}. {detail}",
    ),
    "INTEGRATION_CALL_FAILED": _Spec(
        category=ErrorCategory.SERVER,
        severity=Severity.ERROR,
        title="Integration request failed",
        message_template="{integration}: {detail}",
    ),
    "SKILL_OP_FAILED": _Spec(
        category=ErrorCategory.INTERNAL,
        severity=Severity.ERROR,
        title="Skill operation failed",
        message_template="Could not {operation} skill {name}. {detail}",
    ),
    "COMMAND_USAGE": _Spec(
        category=ErrorCategory.VALIDATION,
        severity=Severity.ERROR,
        title="Invalid command usage",
        message_template="Usage: {usage}",
    ),
    "COMMAND_UNKNOWN": _Spec(
        category=ErrorCategory.VALIDATION,
        severity=Severity.ERROR,
        title="Unknown command",
        message_template="Unknown command: {command}. Use /help for available commands.",
    ),
    "COMMAND_FAILED": _Spec(
        category=ErrorCategory.INTERNAL,
        severity=Severity.ERROR,
        title="Command failed",
        message_template="{command} failed. {detail}",
    ),
}


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
        raise KeyError(f"Unknown error code {code!r} — add it to app/errors/codebook.py")
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


def verbatim(
    message: str,
    *,
    category: ErrorCategory,
    code: str,
    title: str = "",
    severity: Severity = Severity.ERROR,
) -> ErrorInfo:
    """Classify a message WITHOUT rewording it.

    For one-off strings that are instructions to the model rather than
    boilerplate — e.g. "old_string appears 3 times in file. Either provide
    more context..." — retagging must not touch the words, since the agent
    relies on that exact phrasing to self-correct. Anything reused at 2+
    call sites should get a real `_CODEBOOK` entry instead, so its wording
    is locked by tests rather than copy-pasted.
    """
    return ErrorInfo(category=category, code=code, title=title, message=message, severity=severity)


# Exception type -> category, walked via the exception's MRO in
# `error_from_exception`. Deliberately small: only stdlib exception types
# that unambiguously imply a category. Anything else falls back to the
# caller-supplied `category`, then to UNKNOWN.
_EXC_CATEGORY: Dict[Type[BaseException], ErrorCategory] = {
    FileNotFoundError: ErrorCategory.NOT_FOUND,
    PermissionError: ErrorCategory.PERMISSION,
    IsADirectoryError: ErrorCategory.VALIDATION,
    NotADirectoryError: ErrorCategory.VALIDATION,
    TimeoutError: ErrorCategory.CONNECTION,
    ConnectionError: ErrorCategory.CONNECTION,
    ValueError: ErrorCategory.VALIDATION,
    TypeError: ErrorCategory.VALIDATION,
    KeyError: ErrorCategory.VALIDATION,
}


def _category_for_exception(exc: BaseException) -> Optional[ErrorCategory]:
    for exc_type in type(exc).__mro__:
        category = _EXC_CATEGORY.get(exc_type)
        if category is not None:
            return category
    return None


def error_from_exception(
    exc: BaseException, *, code: str, category: Optional[ErrorCategory] = None, **fmt_kwargs
) -> ErrorInfo:
    """Classify + redact a caught exception in one call.

    Replaces the `except Exception as e: ... str(e)` idiom repeated across
    action handlers, browser_adapter and the command executor. `detail` is
    filled in from `str(exc)` automatically (and redacted by `make_error`,
    same as any other `detail` kwarg) unless the caller already supplied one.
    Semantic kwargs (`path=`, `target=`, `provider=`) are never redacted.

    If `exc` is already a `ClassifiedError`, its own `.info` is returned
    untouched — never re-classify an error that already knows what it is.

    The category resolution order is: the exception's own type (via
    `_EXC_CATEGORY`) > the caller-supplied `category` > the codebook code's
    declared category. A `FileNotFoundError` raised at a call site tagged
    `FILE_READ_FAILED` (declared INTERNAL) still comes back NOT_FOUND — the
    exception type is more specific than the code's default.
    """
    if isinstance(exc, ClassifiedError):
        return exc.info  # type: ignore[return-value]

    fmt_kwargs.setdefault("detail", str(exc))
    info = make_error(code, **fmt_kwargs)

    resolved = _category_for_exception(exc) or category
    if resolved is not None and resolved is not info.category:
        info = ErrorInfo(
            category=resolved,
            code=info.code,
            title=info.title,
            message=info.message,
            severity=info.severity,
            actions=info.actions,
            raw_message=info.raw_message,
            context=info.context,
        )
    return info


class CatalogError(ClassifiedError):
    """Drop-in replacement for `raise RuntimeError(f"...")` at call sites
    that have been migrated onto the codebook."""
