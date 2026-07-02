"""Locale-aware rendering of provider errors.

Classification is delegated to the codebase's single structured classifier,
``agent_core.core.impl.llm.errors.classify_llm_error`` — per-SDK extractors,
HTTP status/body parsing, localized (CJK) error-text detection, OpenRouter
unwrapping.  This module only maps the resulting ``ErrorCategory`` onto a
catalog template for the active locale.

Public API
----------
t(key, **kwargs) -> str
    Render a catalog template for the active locale (falls back to "en").

classify_provider_error(exc, *, provider, model="") -> str
    Map a raw exception to a human-readable, locale-aware error string.

Adding a new provider
---------------------
Add one entry to ``_PROVIDER_DISPLAY`` in agent_core/core/impl/llm/errors.py.

Adding a new language
---------------------
Drop app/i18n/errors.<lang>.json alongside errors.en.json.  Missing keys
fall back to "en" automatically.  Packaging picks the file up via the
errors.*.json glob in packaging/CraftBotAgent.spec.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_core.core.impl.llm.errors import (
    ErrorCategory,
    classify_llm_error,
    provider_display_name,
)

# ── Category → catalog key ────────────────────────────────────────────────────
# BAD_REQUEST / SERVER / UNKNOWN deliberately have no entry: they render via
# the generic template with the classifier's (truncated) upstream message
# appended, so unrecognised errors surface their detail instead of being
# swallowed behind a placeholder.  CONNECTION is handled separately to keep
# the polling-timeout wording for timeout-shaped failures.

_CATEGORY_KEYS: dict[ErrorCategory, str] = {
    ErrorCategory.AUTH: "provider_invalid_key",
    ErrorCategory.CREDIT: "provider_rate_limit",
    ErrorCategory.RATE_LIMIT: "provider_rate_limit",
    ErrorCategory.QUOTA: "provider_rate_limit",
    ErrorCategory.MODEL: "provider_model_not_found",
    ErrorCategory.BLOCKED: "provider_safety_block",
}

# ── Catalog loading ───────────────────────────────────────────────────────────

_I18N_DIR = Path(__file__).parent
_catalog_cache: dict[str, dict[str, str]] = {}


def _load_catalog(lang: str) -> dict[str, str]:
    if lang not in _catalog_cache:
        path = _I18N_DIR / f"errors.{lang}.json"
        _catalog_cache[lang] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
    return _catalog_cache[lang]


# ── Template lookup ───────────────────────────────────────────────────────────

def t(key: str, **kwargs: str) -> str:
    """Render catalog *key* with ``{placeholder}`` substitution.

    Resolves in order: active locale → "en" → key itself (never raises).
    """
    from app.config import get_os_language

    lang = get_os_language()
    template = _load_catalog(lang).get(key) or _load_catalog("en").get(key, key)
    return template.format_map(kwargs)


# ── Public classifier ─────────────────────────────────────────────────────────

def classify_provider_error(
    exc: Exception,
    *,
    provider: str,
    model: str = "",
) -> str:
    """Map *exc* to a human-readable, locale-aware error string.

    Classification (status codes, structured bodies, SDK exception types,
    CJK error text) is done by ``classify_llm_error``; this function only
    renders the resulting category through the locale catalog.
    """
    info = classify_llm_error(exc, provider=provider, model=model or None)
    label = provider_display_name(provider)

    key = _CATEGORY_KEYS.get(info.category)
    if key:
        return t(key, provider_label=label, model=model or "the requested model")

    if info.category is ErrorCategory.CONNECTION:
        low = (info.raw_message or str(exc)).lower()
        if "timeout" in low or "timed out" in low:
            return t("provider_timeout", provider_label=label)
        return t("provider_connection", provider_label=label)

    # BAD_REQUEST / SERVER / UNKNOWN — generic template, with the upstream
    # detail appended so misclassified 400s and provider outages surface
    # their cause.  raw_message is already truncated by the classifier.
    result = t("provider_generic", provider_label=label)
    detail = (info.raw_message or "").strip()
    if detail:
        result = f"{result}: {detail}"
    return result
