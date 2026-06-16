"""Provider-error message catalogue with locale-aware lookup.

Public API
----------
t(key, **kwargs) -> str
    Render a catalog template for the active locale (falls back to "en").

classify_provider_error(exc, *, provider, model="") -> str
    Map a raw exception to a human-readable, locale-aware error string.
    Prefers structured HTTP status / API-body parsing over heuristic
    substring matching to avoid false positives on URL path fragments.

Adding a new provider
---------------------
Add one entry to _PROVIDER_LABELS.  No other code changes required.

Adding a new language
---------------------
Drop app/i18n/errors.<lang>.json alongside errors.en.json.  Missing keys
fall back to "en" automatically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ── Provider display labels ───────────────────────────────────────────────────

_PROVIDER_LABELS: dict[str, str] = {
    "openai":      "OpenAI",
    "gemini":      "Gemini",
    "byteplus":    "BytePlus",
    "anthropic":   "Anthropic",
    "openrouter":  "OpenRouter",
    "ollama":      "Ollama",
}

# ── Trigger table ─────────────────────────────────────────────────────────────
# Each entry: (catalog_key, conditions)
# A condition is a str (any single substring present in the lowered message)
# or a tuple[str, ...] (ALL substrings must be present — compound match).
# First match wins.  HTTP status-code checks in classify_provider_error fire
# before this table and bypass it for unambiguous 429 / 401 / 403 / 404.

_TRIGGERS: list[tuple[str, list]] = [
    (
        "provider_rate_limit",
        ["rate limit", "ratelimit", "rate_limit", "quota", "billing", "insufficient_quota"],
    ),
    (
        "provider_invalid_key",
        ["api key", "api_key", "invalid_api_key", "authentication", "unauthorized",
         ("invalid", "key")],
    ),
    (
        "provider_safety_block",
        ["content policy", "content_policy", "safety", "blocked"],
    ),
    (
        "provider_access_denied",
        ["permission", "access denied"],
    ),
    (
        "provider_model_not_found",
        ["not found", "not available", "does not exist"],
    ),
    (
        "provider_timeout",
        ["timeout", "timed out"],
    ),
]

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


# ── HTTP error extraction ─────────────────────────────────────────────────────

def _extract_http_error(exc: Exception) -> tuple[Optional[int], str]:
    """Pull HTTP status and structured API message off an exception.

    Returns ``(status_code, api_message)``.  Either may be ``None``/``""``
    if the exception is not an ``HTTPError`` or carries no JSON body.

    Using the structured body (rather than bare ``str(exc)``) avoids
    false-positive substring matches on URL path fragments — e.g. the word
    "rate" inside "…/generate…" or "content" inside any content-endpoint URL.
    """
    status_code: Optional[int] = None
    api_message = ""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            status_code = int(getattr(resp, "status_code", 0)) or None
        except Exception:
            status_code = None
        try:
            body = resp.json()
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, dict):
                    api_message = str(err.get("message", "")).strip()
                elif isinstance(err, str):
                    api_message = err.strip()
                else:
                    api_message = str(body.get("message", "")).strip()
        except Exception:
            api_message = ""
    return status_code, api_message


def _matches(msg: str, conditions: list) -> bool:
    for cond in conditions:
        if isinstance(cond, tuple):
            if all(s in msg for s in cond):
                return True
        elif cond in msg:
            return True
    return False


# ── Public classifier ─────────────────────────────────────────────────────────

def classify_provider_error(
    exc: Exception,
    *,
    provider: str,
    model: str = "",
) -> str:
    """Map *exc* to a human-readable, locale-aware error string.

    Resolution order:
    1. HTTP status code (unambiguous signal, bypasses substring matching)
    2. Trigger table — substring / compound matches on the API message body
       (or ``str(exc)`` when no structured body is available)
    3. Generic fallback — appends the API message when present so
       unclassified 400s surface their detail instead of being swallowed.
    """
    label = _PROVIDER_LABELS.get(provider, provider.title())
    model_hint = model or "the requested model"

    status_code, api_message = _extract_http_error(exc)
    raw = api_message or str(exc)
    msg = raw.lower()

    # ── HTTP status takes priority ────────────────────────────────────────────
    if status_code == 429:
        return t("provider_rate_limit", provider_label=label)
    if status_code in (401, 403):
        return t("provider_invalid_key", provider_label=label)
    if status_code == 404:
        return t("provider_model_not_found", provider_label=label, model=model_hint)

    # ── Trigger table ─────────────────────────────────────────────────────────
    for key, conditions in _TRIGGERS:
        if _matches(msg, conditions):
            return t(key, provider_label=label, model=model_hint)

    # ── Generic fallback ──────────────────────────────────────────────────────
    result = t("provider_generic", provider_label=label)
    if api_message:
        result = f"{result}: {api_message}"
    return result
