# -*- coding: utf-8 -*-
"""
LLM Error Classification Module.

Turns provider-specific exceptions into a structured `LLMErrorInfo` so the UI
can render category-aware error cards (auth vs credits vs rate-limit vs
server, etc.) instead of a single generic string.

Provider error shapes were captured from live SDK responses — see comments
on each per-provider extractor. The classifier is intentionally defensive
(every body lookup tolerates `None` / wrong type) because some providers
return string bodies, partial JSON, or undocumented fields.

External callers:
- `classify_llm_error(exc) -> LLMErrorInfo` is the new structured API.
- `classify_llm_error_message(exc) -> str` is the back-compat shim for any
  caller that only wants the plain string. Equivalent to
  `classify_llm_error(exc).message`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# Optional provider SDK imports — kept defensive so missing extras don't
# break the classifier path.
try:
    import openai
except ImportError:  # pragma: no cover
    openai = None

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


# ─── Public taxonomy ──────────────────────────────────────────────────


class ErrorCategory(str, Enum):
    AUTH = "auth"               # 401/403 — bad/missing key, key revoked
    CREDIT = "credit"           # 402, "insufficient_quota", "credit_balance_too_low"
    RATE_LIMIT = "rate_limit"   # 429 — transient
    QUOTA = "quota"             # 429 + monthly/account scope (separable from per-min)
    MODEL = "model"             # 404, "model_not_found"
    BAD_REQUEST = "bad_request" # 400 — request malformed (context overflow, etc.)
    BLOCKED = "blocked"         # safety filter (Gemini/Anthropic)
    SERVER = "server"           # 5xx, "overloaded_error"
    CONNECTION = "connection"   # network / timeout / DNS
    UNKNOWN = "unknown"


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
class LLMErrorInfo:
    category: ErrorCategory
    title: str                          # e.g. "Rate limited"
    message: str                        # e.g. "Free-tier limit on Google AI Studio. Wait ~30s or add your own key."
    provider: str                       # "openrouter", "anthropic", ...
    upstream: Optional[str] = None      # "Google AI Studio" — present when OR proxies
    model: Optional[str] = None
    http_status: Optional[int] = None
    retry_after_seconds: Optional[int] = None
    actions: List[ErrorAction] = field(default_factory=list)
    raw_message: Optional[str] = None   # truncated raw upstream text for "Show details"
    request_id: Optional[str] = None    # for support tickets

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        return d


# ─── Provider display names + category fallbacks ─────────────────────


_PROVIDER_DISPLAY: Dict[str, str] = {
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "google": "Gemini",
    "byteplus": "BytePlus",
    "deepseek": "DeepSeek",
    "grok": "Grok",
    "moonshot": "Moonshot",
    "minimax": "MiniMax",
    "remote": "Ollama",
}


# Used only when the provider gave us no message at all (rare). Most
# real-world errors have an upstream message that's already informative;
# we lead with that and only append a short action hint.
_FALLBACK_BODY_BY_CATEGORY: Dict[ErrorCategory, str] = {
    ErrorCategory.AUTH:        "the API key was rejected",
    ErrorCategory.CREDIT:      "out of credits",
    ErrorCategory.RATE_LIMIT:  "rate-limited",
    ErrorCategory.QUOTA:       "quota exceeded",
    ErrorCategory.MODEL:       "the selected model is not available",
    ErrorCategory.BAD_REQUEST: "the request was rejected",
    ErrorCategory.BLOCKED:     "blocked by the provider's safety filter",
    ErrorCategory.SERVER:      "the provider is unavailable",
    ErrorCategory.CONNECTION:  "unable to reach the provider",
    ErrorCategory.UNKNOWN:     "something went wrong",
}


# Back-compat string constants — some callers still import these directly.
# Kept thin (single phrase) since the rich text now flows through info.message.
MSG_AUTH = "The API key was rejected. Check your key in Settings."
MSG_RATE_LIMIT = "The provider rate-limited this request. Try again shortly."
MSG_MODEL = "The selected model is not available. Pick a different model in Settings."
MSG_CONFIG = "The request was rejected by the provider."
MSG_SERVICE = "The provider service is unavailable. Try again later."
MSG_CONNECTION = "Could not reach the provider. Check your network connection."
MSG_GENERIC = "Something went wrong calling the AI service."
MSG_CONSECUTIVE_FAILURE = (
    "Aborted after consecutive failures."
)


# ─── Consecutive-failure exception (preserves last classified info) ───


class LLMConsecutiveFailureError(Exception):
    """Raised when LLM calls fail too many times consecutively.

    Carries the last classified `LLMErrorInfo` (when known) so the UI can
    surface the *cause* of the failures, not just the count.
    """

    def __init__(
        self,
        failure_count: int,
        last_error: Optional[Exception] = None,
        last_error_info: Optional[LLMErrorInfo] = None,
    ):
        self.failure_count = failure_count
        self.last_error = last_error
        self.last_error_info = last_error_info
        message = MSG_CONSECUTIVE_FAILURE.format(count=failure_count)
        if last_error:
            message += f" Last error: {last_error}"
        super().__init__(message)


# ─── Public entry points ──────────────────────────────────────────────


def classify_llm_error(
    error: Exception,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMErrorInfo:
    """Classify an LLM error into structured info.

    The user-visible string is `info.message` — fully self-contained, with
    provider/upstream/raw/action hint composed inline. Other fields are
    informational (logging, metrics) and not surfaced to the UI directly.

    Args:
        error: The exception raised by the provider call.
        provider: Provider id (e.g. "openrouter", "anthropic"). Lets us
            unwrap provider-specific error shapes (notably OpenRouter's
            `metadata.provider_name`/`metadata.raw`).
        model: Model id at call time. Stored on the info for logging.

    Returns:
        `LLMErrorInfo` — never raises. For unrecognised shapes, falls back
        to UNKNOWN with the raw exception text preserved as the message
        (better than a generic stub — at least the user sees what blew up).
    """
    info = _try_classify(error, provider=provider)
    if info is None:
        # Don't fabricate a generic message — the raw exception text is
        # almost always more informative than any stub we could write.
        raw = _truncate(str(error)) or "AI service error"
        info = LLMErrorInfo(
            category=ErrorCategory.UNKNOWN,
            title="AI service error",
            message=raw,
            provider=provider or "unknown",
            raw_message=raw,
        )

    if model and info.model is None:
        info.model = model

    return info


def classify_llm_error_message(error: Exception) -> str:
    """Back-compat shim — returns just the user-facing string.

    Equivalent to `classify_llm_error(error).message`. Kept so existing
    call sites that only need a string don't have to refactor in this PR.
    """
    return classify_llm_error(error).message


# ─── Dispatcher ───────────────────────────────────────────────────────


def _try_classify(
    error: Exception,
    *,
    provider: Optional[str],
) -> Optional[LLMErrorInfo]:
    """Try each provider extractor in turn. Returns None if nothing matches."""
    # OpenAI SDK exceptions cover openai/openrouter/grok/deepseek/moonshot/minimax
    if openai is not None and isinstance(error, openai.OpenAIError):
        return _classify_openai_compat(error, provider or "openai")

    # Anthropic SDK exceptions
    if anthropic is not None and isinstance(error, anthropic.AnthropicError):
        return _classify_anthropic(error, provider or "anthropic")

    # httpx errors are how the Gemini and BytePlus paths surface failures
    if httpx is not None and isinstance(error, httpx.HTTPStatusError):
        return _classify_httpx_status(error, provider)
    if httpx is not None and isinstance(error, httpx.RequestError):
        return _classify_httpx_connection(error, provider)

    # `requests` library — older code paths still raise these
    if requests is not None and isinstance(error, requests.exceptions.RequestException):
        return _classify_requests(error, provider)

    # Gemini's custom error type (raised by our REST client)
    msg = str(error)
    if "Gemini" in msg or "promptFeedback" in msg or "blocked" in msg.lower():
        return _classify_gemini_runtime(error, provider or "gemini")

    return None


# ─── OpenAI / OpenAI-compatible (openai, openrouter, grok, deepseek, ...) ───


def _classify_openai_compat(exc: Exception, provider: str) -> LLMErrorInfo:
    """Handle openai SDK exception hierarchy.

    Real shapes captured from live probes:
    - OpenAI 401:    body.code = "invalid_api_key" (string), body.type = "invalid_request_error"
    - OpenRouter 401: body = {"message": "User not found.", "code": 401}  ← flat, code is INT
    - OpenRouter 429: body = {"message": ..., "code": 429,
                              "metadata": {"raw": ..., "provider_name": "...", "is_byok": false}}
    - Grok 400 (auth!): body is a STRING, status is 400 (NOT 401)
    - DeepSeek 401:  body.type = "authentication_error", body.code = "invalid_request_error"
    """
    body = getattr(exc, "body", None)
    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)

    body_dict: Dict[str, Any] = {}
    if isinstance(body, dict):
        body_dict = body
    elif isinstance(body, str):
        # Grok edge case — body is the raw string message
        body_dict = {"message": body}

    # Pick the cleanest user-facing string out of the body. Different
    # OpenAI-compatible providers stash it under different keys:
    #   - OpenAI / OpenRouter / DeepSeek: body["message"]
    #   - Grok bad-model (400):           body["error"]   (a string)
    #   - Grok bad-key (400, body=string):  handled above by string→dict shim
    # Falling back to str(exc) produces "Error code: 400 - {full body dict}",
    # which is too noisy for the chat — only use it when nothing else fits.
    raw_message_candidate: Optional[str] = None
    for key in ("message", "error"):
        v = body_dict.get(key)
        if isinstance(v, str) and v:
            raw_message_candidate = v
            break
    raw_message: str = raw_message_candidate or str(exc)
    code = body_dict.get("code")
    error_type = body_dict.get("type")

    upstream: Optional[str] = None
    metadata = body_dict.get("metadata") if isinstance(body_dict.get("metadata"), dict) else None

    # OpenRouter wraps upstream errors. The upstream's verbatim message is
    # FAR more useful than OR's "Provider returned error" wrapper.
    if provider == "openrouter" and metadata:
        if isinstance(metadata.get("provider_name"), str):
            upstream = metadata["provider_name"]
        if isinstance(metadata.get("raw"), str) and metadata["raw"]:
            raw_message = metadata["raw"]

    # ── Category resolution ────────────────────────────────────────
    category = _category_from_openai_exc(exc, status=status, body_dict=body_dict, raw=raw_message)

    # OpenAI string codes are the gold standard signal where present
    if isinstance(code, str):
        if code == "insufficient_quota":
            category = ErrorCategory.CREDIT
        elif code == "rate_limit_exceeded":
            category = ErrorCategory.RATE_LIMIT
        elif code == "context_length_exceeded":
            category = ErrorCategory.BAD_REQUEST
        elif code in ("model_not_found", "invalid_model"):
            category = ErrorCategory.MODEL
        elif code == "invalid_api_key":
            category = ErrorCategory.AUTH

    # Anthropic-style nested error type can appear when OR proxies Anthropic
    if isinstance(error_type, str):
        if error_type == "credit_balance_too_low":
            category = ErrorCategory.CREDIT
        elif error_type == "overloaded_error":
            category = ErrorCategory.SERVER

    # OpenRouter uses 402 for empty wallet; the openai SDK doesn't have a
    # dedicated 402 exception so we land in APIStatusError — adjust here.
    if status == 402:
        category = ErrorCategory.CREDIT

    # ── Retry-After ────────────────────────────────────────────────
    retry_after = _retry_after_seconds(exc)

    # ── User-facing message ────────────────────────────────────────
    message = _compose_message(category, raw_message, provider, upstream, retry_after_seconds=retry_after)
    actions = _default_actions(category, provider, upstream, metadata)

    return LLMErrorInfo(
        category=category,
        title=_title_for(category, upstream=upstream),
        message=message,
        provider=provider,
        upstream=upstream,
        http_status=status if isinstance(status, int) else None,
        retry_after_seconds=retry_after,
        actions=actions,
        raw_message=_truncate(raw_message),
        request_id=request_id if isinstance(request_id, str) else None,
    )


def _category_from_openai_exc(
    exc: Exception,
    *,
    status: Optional[int],
    body_dict: Dict[str, Any],
    raw: str,
) -> ErrorCategory:
    """Map openai SDK exception type → category. Defensive for missing SDK."""
    if openai is None:  # pragma: no cover
        return _category_from_status(status)

    if isinstance(exc, openai.AuthenticationError):
        return ErrorCategory.AUTH
    if isinstance(exc, openai.PermissionDeniedError):
        # Often "billing-blocked" or "country-not-supported" — surface as AUTH-ish.
        return ErrorCategory.AUTH
    if isinstance(exc, openai.NotFoundError):
        return ErrorCategory.MODEL
    if isinstance(exc, openai.RateLimitError):
        return ErrorCategory.RATE_LIMIT
    if isinstance(exc, openai.BadRequestError):
        # Grok returns 400 for auth — sniff body
        lower = raw.lower()
        if "api key" in lower or "api_key" in lower or "invalid_api_key" in lower:
            return ErrorCategory.AUTH
        if "context" in lower and ("length" in lower or "too long" in lower or "exceeds" in lower):
            return ErrorCategory.BAD_REQUEST
        if "model" in lower and ("not found" in lower or "not available" in lower or "does not exist" in lower):
            return ErrorCategory.MODEL
        if "blocked" in lower or "safety" in lower or "policy" in lower:
            return ErrorCategory.BLOCKED
        return ErrorCategory.BAD_REQUEST
    if isinstance(exc, openai.InternalServerError):
        return ErrorCategory.SERVER
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return ErrorCategory.CONNECTION
    if isinstance(exc, openai.APIStatusError):
        return _category_from_status(status)

    return _category_from_status(status)


# ─── Anthropic ────────────────────────────────────────────────────────


def _classify_anthropic(exc: Exception, provider: str) -> LLMErrorInfo:
    """Anthropic SDK shape:
        body = {
          "type": "error",
          "error": {"type": "authentication_error" | ..., "message": "..."},
          "request_id": "..."
        }
    """
    if anthropic is None:  # pragma: no cover
        return _fallback_unknown(exc, provider)

    body = getattr(exc, "body", None)
    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)

    error_block = {}
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):
            error_block = body["error"]
        elif isinstance(body.get("type"), str):
            error_block = body

    a_type = error_block.get("type") if isinstance(error_block, dict) else None
    raw_message = (
        error_block.get("message")
        if isinstance(error_block, dict) and isinstance(error_block.get("message"), str)
        else str(exc)
    )

    # Map Anthropic's typed error names. These are richer than HTTP codes.
    type_to_category = {
        "authentication_error": ErrorCategory.AUTH,
        "permission_error": ErrorCategory.AUTH,
        "credit_balance_too_low": ErrorCategory.CREDIT,
        "billing_error": ErrorCategory.CREDIT,
        "rate_limit_error": ErrorCategory.RATE_LIMIT,
        "overloaded_error": ErrorCategory.SERVER,
        "api_error": ErrorCategory.SERVER,
        "invalid_request_error": ErrorCategory.BAD_REQUEST,
        "not_found_error": ErrorCategory.MODEL,
    }

    category: Optional[ErrorCategory] = None
    if isinstance(a_type, str) and a_type in type_to_category:
        category = type_to_category[a_type]
    else:
        # Fall back to SDK exception class
        if isinstance(exc, anthropic.AuthenticationError):
            category = ErrorCategory.AUTH
        elif isinstance(exc, anthropic.PermissionDeniedError):
            category = ErrorCategory.AUTH
        elif isinstance(exc, anthropic.NotFoundError):
            category = ErrorCategory.MODEL
        elif isinstance(exc, anthropic.RateLimitError):
            category = ErrorCategory.RATE_LIMIT
        elif isinstance(exc, anthropic.InternalServerError):
            category = ErrorCategory.SERVER
        elif isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            category = ErrorCategory.CONNECTION
        elif isinstance(exc, anthropic.BadRequestError):
            lower = raw_message.lower()
            if "prompt is too long" in lower or "maximum context length" in lower:
                category = ErrorCategory.BAD_REQUEST
            else:
                category = ErrorCategory.BAD_REQUEST
        else:
            category = _category_from_status(status)

    retry_after = _retry_after_seconds(exc)

    actions = _default_actions(category, provider, upstream=None, metadata=None)

    return LLMErrorInfo(
        category=category,
        title=_title_for(category),
        message=_compose_message(category, raw_message, provider, upstream=None, retry_after_seconds=retry_after),
        provider=provider,
        upstream=None,
        http_status=status if isinstance(status, int) else None,
        retry_after_seconds=retry_after,
        actions=actions,
        raw_message=_truncate(raw_message),
        request_id=request_id if isinstance(request_id, str) else None,
    )


# ─── Gemini ────────────────────────────────────────────────────────────


def _classify_httpx_status(exc: Exception, provider: Optional[str]) -> LLMErrorInfo:
    """httpx.HTTPStatusError — covers Gemini and BytePlus paths.

    Gemini body: {"error":{"code":400,"message":"...","status":"INVALID_ARGUMENT",
                  "details":[{"reason":"API_KEY_INVALID",...}]}}
    BytePlus body: {"error":{"code":"AuthenticationError","message":"..."}}
    """
    if httpx is None:  # pragma: no cover
        return _fallback_unknown(exc, provider or "unknown")

    response = getattr(exc, "response", None)
    status = response.status_code if response is not None else None
    text = response.text if response is not None else ""
    body_dict = _safe_json(text)

    err = body_dict.get("error") if isinstance(body_dict.get("error"), dict) else {}
    raw_message = err.get("message") if isinstance(err.get("message"), str) else str(exc)

    # Detect Gemini specifically by reason field
    reason: Optional[str] = None
    details = err.get("details") if isinstance(err.get("details"), list) else []
    for d in details:
        if isinstance(d, dict) and isinstance(d.get("reason"), str):
            reason = d["reason"]
            break

    inferred_provider = provider or ("gemini" if reason or "generativelanguage" in text else "unknown")

    # Gemini's REST API returns 400 for invalid keys — map by reason field
    if reason == "API_KEY_INVALID":
        category = ErrorCategory.AUTH
    elif reason == "RESOURCE_EXHAUSTED":
        category = ErrorCategory.RATE_LIMIT
    elif reason == "PERMISSION_DENIED":
        category = ErrorCategory.AUTH
    else:
        category = _category_from_status(status)
        # BytePlus encodes auth errors via err.code = "AuthenticationError"
        if isinstance(err.get("code"), str) and "auth" in err["code"].lower():
            category = ErrorCategory.AUTH

    retry_after = None
    if response is not None:
        ra = response.headers.get("retry-after")
        if ra is not None:
            try:
                retry_after = int(float(ra))
            except (ValueError, TypeError):
                retry_after = None

    actions = _default_actions(category, inferred_provider, upstream=None, metadata=None)

    return LLMErrorInfo(
        category=category,
        title=_title_for(category),
        message=_compose_message(category, raw_message, inferred_provider, upstream=None),
        provider=inferred_provider,
        upstream=None,
        http_status=status,
        retry_after_seconds=retry_after,
        actions=actions,
        raw_message=_truncate(raw_message),
    )


def _classify_httpx_connection(exc: Exception, provider: Optional[str]) -> LLMErrorInfo:
    raw = _truncate(str(exc))
    return LLMErrorInfo(
        category=ErrorCategory.CONNECTION,
        title=_title_for(ErrorCategory.CONNECTION),
        message=_compose_message(ErrorCategory.CONNECTION, raw, provider or "unknown", upstream=None),
        provider=provider or "unknown",
        raw_message=raw,
    )


def _classify_gemini_runtime(exc: Exception, provider: str) -> LLMErrorInfo:
    """Gemini's GeminiAPIError — raised when the response shape signals an issue
    that isn't an HTTP failure (e.g. promptFeedback.blockReason)."""
    raw = str(exc)
    lower = raw.lower()

    if "blocked" in lower or "promptfeedback" in lower or "safety" in lower:
        category = ErrorCategory.BLOCKED
    else:
        category = ErrorCategory.UNKNOWN

    return LLMErrorInfo(
        category=category,
        title=_title_for(category),
        message=_compose_message(category, raw, provider, upstream=None),
        provider=provider,
        raw_message=_truncate(raw),
        actions=_default_actions(category, provider, upstream=None, metadata=None),
    )


# ─── requests library (legacy callers) ────────────────────────────────


def _classify_requests(exc: Exception, provider: Optional[str]) -> Optional[LLMErrorInfo]:
    if requests is None:  # pragma: no cover
        return None
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        if response is not None:
            status = response.status_code
            try:
                body = response.json()
            except Exception:
                body = {}
            err = body.get("error") if isinstance(body.get("error"), dict) else {}
            raw_message = err.get("message") if isinstance(err.get("message"), str) else response.text
            return LLMErrorInfo(
                category=_category_from_status(status),
                title=_title_for(_category_from_status(status)),
                message=_compose_message(_category_from_status(status), raw_message, provider or "unknown", upstream=None),
                provider=provider or "unknown",
                http_status=status,
                raw_message=_truncate(raw_message),
            )
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        raw = _truncate(str(exc))
        return LLMErrorInfo(
            category=ErrorCategory.CONNECTION,
            title=_title_for(ErrorCategory.CONNECTION),
            message=_compose_message(ErrorCategory.CONNECTION, raw, provider or "unknown", upstream=None),
            provider=provider or "unknown",
            raw_message=raw,
        )
    return None


# ─── Helpers ──────────────────────────────────────────────────────────


def _category_from_status(status: Optional[int]) -> ErrorCategory:
    if status is None:
        return ErrorCategory.UNKNOWN
    if status in (401, 403):
        return ErrorCategory.AUTH
    if status == 402:
        return ErrorCategory.CREDIT
    if status == 404:
        return ErrorCategory.MODEL
    if status == 400:
        return ErrorCategory.BAD_REQUEST
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if 500 <= status < 600:
        return ErrorCategory.SERVER
    return ErrorCategory.UNKNOWN


def _retry_after_seconds(exc: Exception) -> Optional[int]:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    ra = None
    try:
        ra = response.headers.get("retry-after")
    except AttributeError:
        return None
    if not ra:
        return None
    try:
        return int(float(ra))
    except (ValueError, TypeError):
        return None


_CATEGORY_TITLES: Dict[ErrorCategory, str] = {
    ErrorCategory.AUTH: "Invalid API key",
    ErrorCategory.CREDIT: "Out of credits",
    ErrorCategory.RATE_LIMIT: "Rate limited",
    ErrorCategory.QUOTA: "Quota exceeded",
    ErrorCategory.MODEL: "Incorrect model id",
    ErrorCategory.BAD_REQUEST: "Bad request",
    ErrorCategory.BLOCKED: "Blocked by safety filter",
    ErrorCategory.SERVER: "Provider service unavailable",
    ErrorCategory.CONNECTION: "Cannot reach provider",
    ErrorCategory.UNKNOWN: "AI service error",
}


# Categories where we suppress the leading title sentence — the raw
# provider message is already self-explanatory or the title would just
# repeat the upstream's words.
_SKIP_TITLE_CATEGORIES = {ErrorCategory.UNKNOWN, ErrorCategory.BAD_REQUEST}


def _title_for(category: ErrorCategory, *, upstream: Optional[str] = None) -> str:
    """Short title — used for logging/metrics and for the leading sentence
    of the user-facing chat message (see `_compose_message`)."""
    base = _CATEGORY_TITLES.get(category, "AI service error")
    if upstream and category in (ErrorCategory.RATE_LIMIT, ErrorCategory.SERVER, ErrorCategory.BLOCKED):
        return f"{base} ({upstream})"
    return base


def _compose_message(
    category: ErrorCategory,
    raw_message: str,
    provider: str,
    upstream: Optional[str],
    *,
    retry_after_seconds: Optional[int] = None,
) -> str:
    """Build the single user-facing string shown in the chat error bubble.

    Format:  "<Category title>. <Provider> [via <Upstream>]: <raw>. <action hint>."

    The category title leads so users instantly know *what kind* of error
    happened — important when the provider's raw text is terse (Anthropic
    returns just `"model: claude-sonnet-4-5-2025092945"` for a bad model
    id, which is meaningless without context). The raw provider text
    follows so users see the exact upstream message. The action hint
    closes when it adds value beyond what the raw already says.
    """
    raw = (raw_message or "").strip()
    if raw.lower() == "none":
        raw = ""
    raw = _truncate(raw.rstrip("."), limit=400)
    if not raw:
        raw = _FALLBACK_BODY_BY_CATEGORY.get(category, "an error occurred")

    # Lead with category title (e.g. "Incorrect model id.") unless the
    # category is too vague to title meaningfully.
    if category in _SKIP_TITLE_CATEGORIES:
        lead = ""
    else:
        lead = f"{_title_for(category, upstream=upstream)}."

    name = _PROVIDER_DISPLAY.get(provider, "")
    if name:
        prefix = f"{name} (via {upstream})" if upstream else name
        provider_part = f"{prefix}: {raw}"
    else:
        provider_part = raw

    body = f"{lead} {provider_part}" if lead else provider_part
    return _append_hint(body, category, provider, retry_after_seconds, raw.lower())


def _append_hint(
    body: str,
    category: ErrorCategory,
    provider: str,
    retry_after: Optional[int],
    raw_lower: str,
) -> str:
    """Append a short action hint, suppressed when the provider's own raw
    text already covers it (avoids "...add your own key. Try again shortly.")."""
    base = body.rstrip(".")

    if category == ErrorCategory.AUTH:
        if "key" in raw_lower or "settings" in raw_lower:
            return f"{base}."
        return f"{base}. Check your API key in Settings."

    if category == ErrorCategory.CREDIT:
        if any(s in raw_lower for s in ("billing", "credit", "top up", "topup")):
            return f"{base}."
        if provider == "openrouter":
            return f"{base}. Top up at https://openrouter.ai/credits."
        if provider == "openai":
            return f"{base}. Manage billing at https://platform.openai.com/account/billing."
        if provider == "anthropic":
            return f"{base}. Manage billing at https://console.anthropic.com/settings/billing."
        return f"{base}."

    if category == ErrorCategory.RATE_LIMIT:
        if retry_after:
            return f"{base}. Try again in {retry_after}s."
        if any(s in raw_lower for s in (
            "byok", "your own key", "openrouter.ai/settings", "retry", "wait", "try again",
        )):
            return f"{base}."
        return f"{base}. Try again shortly."

    if category == ErrorCategory.QUOTA:
        if "billing" in raw_lower or "usage" in raw_lower:
            return f"{base}."
        if provider == "openai":
            return f"{base}. Manage usage at https://platform.openai.com/usage."
        return f"{base}."

    if category == ErrorCategory.MODEL:
        if "settings" in raw_lower:
            return f"{base}."
        return f"{base}. Use a correct model in Settings."

    if category == ErrorCategory.BLOCKED:
        return f"{base}. Edit your prompt and retry."

    if category == ErrorCategory.SERVER:
        if "try again" in raw_lower or "retry" in raw_lower:
            return f"{base}."
        return f"{base}. Try again later."

    if category == ErrorCategory.CONNECTION:
        if provider == "remote":
            return f"{base}. Check that Ollama is running."
        if "network" in raw_lower or "connection" in raw_lower:
            return f"{base}."
        return f"{base}. Check your network connection."

    # BAD_REQUEST / UNKNOWN — raw is the most informative thing we can show
    return f"{base}."


def _default_actions(
    category: ErrorCategory,
    provider: str,
    upstream: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> List[ErrorAction]:
    """Per-(category, provider) action affordances.

    Keep this list short — each action is a click target the user is more
    likely to actually want than just dismissing the error.
    """
    actions: List[ErrorAction] = []

    if category == ErrorCategory.CREDIT:
        if provider == "openrouter":
            actions.append(ErrorAction(label="Top up credits", url="https://openrouter.ai/credits"))
        elif provider == "openai":
            actions.append(ErrorAction(label="Manage billing", url="https://platform.openai.com/account/billing"))
        elif provider == "anthropic":
            actions.append(ErrorAction(label="Manage billing", url="https://console.anthropic.com/settings/billing"))
        actions.append(ErrorAction(label="Open settings", action="open_settings_model"))

    elif category == ErrorCategory.RATE_LIMIT:
        if provider == "openrouter" and metadata and metadata.get("is_byok") is False:
            # Free-tier user — point at OR integrations page for BYOK
            actions.append(ErrorAction(label="Add your own key", url="https://openrouter.ai/settings/integrations"))
        actions.append(ErrorAction(label="Open settings", action="open_settings_model"))

    elif category == ErrorCategory.QUOTA:
        if provider == "openai":
            actions.append(ErrorAction(label="Manage usage", url="https://platform.openai.com/usage"))

    return actions


def _has_action(info: LLMErrorInfo, action_value: str) -> bool:
    return any(a.action == action_value for a in info.actions)


def _safe_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        import json
        result = json.loads(text)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _truncate(s: Optional[str], limit: int = 500) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def _fallback_unknown(exc: Exception, provider: str) -> LLMErrorInfo:
    raw = _truncate(str(exc)) or "AI service error"
    return LLMErrorInfo(
        category=ErrorCategory.UNKNOWN,
        title="AI service error",
        message=raw,
        provider=provider,
        raw_message=raw,
    )
