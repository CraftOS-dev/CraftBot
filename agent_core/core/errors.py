# -*- coding: utf-8 -*-
"""
Shared error-catalogue primitives.

`agent_core` never imports from `app` (the dependency runs the other way), so
the category/severity/action vocabulary shared between the LLM classifier
(`agent_core/core/impl/llm/errors.py`) and app-layer call sites
(`app/errors/codebook.py`) lives here.

`LLMErrorInfo` (in the LLM package) is intentionally NOT made a subclass of
`ErrorInfo` — its `provider` field is positional/non-default and reordering it
behind new defaulted base fields would break its existing consumers. Both
satisfy `ErrorInfoLike` structurally instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"  # aborts a run


class ErrorCategory(str, Enum):
    AUTH = "auth"  # 401/403 — bad/missing key, key revoked
    CREDIT = "credit"  # 402, "insufficient_quota", "credit_balance_too_low"
    RATE_LIMIT = "rate_limit"  # 429 — transient
    QUOTA = "quota"  # 429 + monthly/account scope (separable from per-min)
    MODEL = "model"  # 404, "model_not_found"
    BAD_REQUEST = "bad_request"  # 400 — request malformed (context overflow, etc.)
    BLOCKED = "blocked"  # safety filter (Gemini/Anthropic)
    SERVER = "server"  # 5xx, "overloaded_error"
    CONNECTION = "connection"  # network / timeout / DNS
    UNKNOWN = "unknown"
    # App-layer categories, not produced by the LLM classifier:
    VALIDATION = "validation"  # malformed input outside an LLM call
    NOT_FOUND = "not_found"
    CONFIG = "config"  # local misconfiguration (e.g. no key set, before any network call)
    PERMISSION = "permission"  # local/file/OS permission issues
    INTERNAL = "internal"  # unexpected/bug-shaped exception


# Categories where retrying the same request essentially never succeeds —
# these should fail fast instead of consuming a retry budget. RATE_LIMIT,
# SERVER, CONNECTION, and UNKNOWN are left out deliberately: they're the
# genuinely transient cases retries exist for.
FAIL_FAST_CATEGORIES = frozenset(
    {
        ErrorCategory.AUTH,
        ErrorCategory.CREDIT,
        ErrorCategory.QUOTA,
        ErrorCategory.MODEL,
        ErrorCategory.BLOCKED,
        ErrorCategory.BAD_REQUEST,
    }
)


def is_transient(category: ErrorCategory) -> bool:
    """Whether retrying the same request has a real chance of succeeding."""
    return category not in FAIL_FAST_CATEGORIES


@dataclass
class ErrorAction:
    """A clickable affordance attached to an error.

    `url` opens in a new tab; `action` is a frontend-resolved verb such as
    "open_settings_model" — handled by the chat component, not by URL nav.
    Exactly one of url/action should be set.
    """

    label: str
    url: Optional[str] = None
    action: Optional[str] = None


@dataclass
class ErrorInfo:
    """Generic app-wide structured error, for call sites outside the LLM
    provider classifier (which uses the richer `LLMErrorInfo`)."""

    category: ErrorCategory
    code: str
    title: str
    message: str
    severity: Severity = Severity.ERROR
    actions: List[ErrorAction] = field(default_factory=list)
    raw_message: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_transient(self) -> bool:
        return is_transient(self.category)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d


@runtime_checkable
class ErrorInfoLike(Protocol):
    """Structural type both `ErrorInfo` and `LLMErrorInfo` satisfy."""

    category: ErrorCategory
    title: str
    message: str
    actions: List[ErrorAction]


# ─── Redaction ──────────────────────────────────────────────────────────
# Ported from the now-removed app/security/error_handler.py — applied to raw
# upstream/exception text before it's echoed to the UI (e.g. UNKNOWN/BAD_REQUEST
# fallback messages), not to the curated, hand-written catalogue strings.

_REDACT_PATTERNS = [
    re.compile(r"/[^/\s]+\.py"),  # file paths
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),  # emails
    re.compile(r"://[^/\s]+"),  # URLs/hostnames
    re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"),  # IPv4 addresses
]


def redact(raw: str, max_length: int = 500) -> str:
    """Strip file paths/emails/hostnames/IPs from raw exception text."""
    text = raw
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text
