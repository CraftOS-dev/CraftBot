# -*- coding: utf-8 -*-
"""
LLM Error Classification Module.

Provides user-friendly error messages for LLM-related failures.
Uses proper exception types and HTTP status codes - no string pattern matching.
"""

from __future__ import annotations


from typing import Optional

# Import provider exception types
try:
    import openai
except ImportError:
    openai = None

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import requests
except ImportError:
    requests = None


# User-friendly messages
MSG_AUTH = "Unable to connect to AI service. Please check your API key in Settings."
MSG_CONSECUTIVE_FAILURE = (
    "LLM calls have failed {count} consecutive times. "
    "Task aborted to prevent infinite retries. Please check your LLM configuration."
)


class LLMConsecutiveFailureError(Exception):
    """Raised when LLM calls fail too many times consecutively.

    This exception signals that the task should be aborted to prevent
    infinite retry loops that flood logs and waste resources.
    """

    def __init__(self, failure_count: int, last_error: Optional[Exception] = None):
        self.failure_count = failure_count
        self.last_error = last_error
        message = MSG_CONSECUTIVE_FAILURE.format(count=failure_count)
        if last_error:
            message += f" Last error: {last_error}"
        super().__init__(message)
MSG_MODEL = "The selected AI model is not available. Please check your model settings."
MSG_CONFIG = "AI service configuration error. The selected model may not support required features."
MSG_RATE_LIMIT = "AI service is rate-limited. Please wait a moment and try again."
MSG_SERVICE = "AI service is temporarily unavailable. Please try again later."
MSG_CONNECTION = "Unable to reach AI service. Please check your internet connection."
MSG_GENERIC = "An error occurred with the AI service. Please check your LLM configuration."


def classify_llm_error(error: Exception) -> str:
    """Classify an LLM error and return a user-friendly message.

    Uses exception types and HTTP status codes for classification.

    Args:
        error: The exception from the LLM call.

    Returns:
        A user-friendly error message.
    """
    # Check OpenAI exceptions
    if openai is not None:
        msg = _classify_openai_error(error)
        if msg:
            return msg

    # Check Anthropic exceptions
    if anthropic is not None:
        msg = _classify_anthropic_error(error)
        if msg:
            return msg

    # Check requests exceptions (BytePlus, remote/Ollama)
    if requests is not None:
        msg = _classify_requests_error(error)
        if msg:
            return msg

    # Check for status_code attribute on any exception
    status_code = _get_status_code(error)
    if status_code:
        return _message_from_status_code(status_code)

    # Generic fallback
    return MSG_GENERIC


def _classify_openai_error(error: Exception) -> Optional[str]:
    """Classify OpenAI SDK exceptions."""
    if isinstance(error, openai.AuthenticationError):
        return MSG_AUTH
    if isinstance(error, openai.PermissionDeniedError):
        return MSG_AUTH
    if isinstance(error, openai.NotFoundError):
        return MSG_MODEL
    if isinstance(error, openai.BadRequestError):
        return MSG_CONFIG
    if isinstance(error, openai.RateLimitError):
        return MSG_RATE_LIMIT
    if isinstance(error, openai.InternalServerError):
        return MSG_SERVICE
    if isinstance(error, openai.APIConnectionError):
        return MSG_CONNECTION
    if isinstance(error, openai.APITimeoutError):
        return MSG_CONNECTION
    if isinstance(error, openai.APIStatusError):
        return _message_from_status_code(error.status_code)
    return None


def _classify_anthropic_error(error: Exception) -> Optional[str]:
    """Classify Anthropic SDK exceptions."""
    if isinstance(error, anthropic.AuthenticationError):
        return MSG_AUTH
    if isinstance(error, anthropic.PermissionDeniedError):
        return MSG_AUTH
    if isinstance(error, anthropic.NotFoundError):
        return MSG_MODEL
    if isinstance(error, anthropic.BadRequestError):
        return MSG_CONFIG
    if isinstance(error, anthropic.RateLimitError):
        return MSG_RATE_LIMIT
    if isinstance(error, anthropic.InternalServerError):
        return MSG_SERVICE
    if isinstance(error, anthropic.APIConnectionError):
        return MSG_CONNECTION
    if isinstance(error, anthropic.APITimeoutError):
        return MSG_CONNECTION
    if isinstance(error, anthropic.APIStatusError):
        return _message_from_status_code(error.status_code)
    return None


def _classify_requests_error(error: Exception) -> Optional[str]:
    """Classify requests library exceptions (for BytePlus/Ollama)."""
    if isinstance(error, requests.exceptions.HTTPError):
        if error.response is not None:
            return _message_from_status_code(error.response.status_code)
        return MSG_SERVICE
    if isinstance(error, requests.exceptions.ConnectionError):
        return MSG_CONNECTION
    if isinstance(error, requests.exceptions.Timeout):
        return MSG_CONNECTION
    return None


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
        # Chinese provider credit codes (DeepSeek, MiniMax, Moonshot, Qwen)
        elif code in ("insufficient_user_quota", "quota_exceeded", "balance_insufficient",
                      "BillingException", "InsufficientQuota"):
            category = ErrorCategory.CREDIT
        # Chinese provider content-filter codes
        elif code in ("content_policy_violation", "content_filter", "output_moderation",
                      "ContentAuditException", "DataInspectionFailed"):
            category = ErrorCategory.BLOCKED

    # Anthropic-style nested error type can appear when OR proxies Anthropic
    if isinstance(error_type, str):
        if error_type == "credit_balance_too_low":
            category = ErrorCategory.CREDIT
        elif error_type == "overloaded_error":
            category = ErrorCategory.SERVER
        # OpenRouter content moderation (OR itself flags the content before forwarding)
        elif error_type == "moderation":
            category = ErrorCategory.BLOCKED

    # OpenRouter uses 402 for empty wallet; the openai SDK doesn't have a
    # dedicated 402 exception so we land in APIStatusError — adjust here.
    if status == 402:
        category = ErrorCategory.CREDIT

    # OpenRouter 403 can mean content moderation, not just auth — check body
    if status == 403 and provider == "openrouter":
        raw_lower = raw_message.lower()
        if any(k in raw_lower for k in ("moderat", "blocked", "policy", "content", "flagged")):
            category = ErrorCategory.BLOCKED

    # Localised error message detection — Chinese, Japanese, Korean providers
    # (DeepSeek, Moonshot, MiniMax, Qwen, rinna, CLOVA, etc.) may return
    # error text in their native language when routed via OpenRouter.
    category = _refine_category_from_localised(raw_message, category)

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
    if status == 408:
        return ErrorCategory.CONNECTION  # request timeout
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if status == 524:
        return ErrorCategory.SERVER  # Cloudflare upstream timeout (common on OpenRouter)
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


def _refine_category_from_localised(raw_message: str, current: ErrorCategory) -> ErrorCategory:
    """Detect category from non-English error text returned by Asian providers.

    Covers Chinese (DeepSeek, MiniMax, Moonshot, Qwen, Baidu ERNIE),
    Japanese (rinna, Sakura, ELYZA), and Korean (CLOVA, HyperCLOVA) providers
    that may return error messages in their native language when routed via
    OpenRouter or called directly.

    Only overrides UNKNOWN / BAD_REQUEST — specific categories already resolved
    from HTTP status or error codes take priority.

    Handles arbitrary UTF-8 safely: Python str containment checks on Unicode
    strings are always safe regardless of script or encoding.
    """
    if not raw_message or current not in (ErrorCategory.UNKNOWN, ErrorCategory.BAD_REQUEST):
        return current

    # Normalise: ensure we have a plain str (guards against bytes leaking in)
    try:
        msg = raw_message if isinstance(raw_message, str) else raw_message.decode("utf-8", errors="replace")
    except Exception:
        return current

    # ── Chinese ───────────────────────────────────────────────────────
    _ZH_BLOCKED = ("违禁", "违规", "内容政策", "不合规", "审核不通过", "违反规定",
                   "敏感内容", "内容安全", "内容审核", "政治敏感", "黄色信息")
    _ZH_CREDIT  = ("余额不足", "额度不足", "账户欠费", "账户余额", "充值", "欠费",
                   "配额不足", "余额不够")
    _ZH_AUTH    = ("无效的API", "鉴权失败", "认证失败", "密钥无效", "API密钥",
                   "身份验证", "未授权")
    _ZH_RATE    = ("频率限制", "请求过多", "限流", "速率限制", "调用频率",
                   "访问频率", "接口限流")
    _ZH_CONTEXT = ("超出最大长度", "上下文长度", "tokens超出", "输入过长",
                   "超过最大token")

    # ── Japanese ──────────────────────────────────────────────────────
    _JA_BLOCKED = ("禁止されたコンテンツ", "コンテンツポリシー", "不適切なコンテンツ",
                   "ポリシー違反", "有害なコンテンツ", "安全フィルター")
    _JA_CREDIT  = ("残高不足", "クレジット不足", "料金超過", "利用上限", "残高が不足",
                   "クォータ超過")
    _JA_AUTH    = ("認証エラー", "認証に失敗", "APIキーが無効", "無効なAPIキー",
                   "認証情報", "アクセス拒否")
    _JA_RATE    = ("レート制限", "リクエスト制限", "利用制限", "リクエストが多すぎ",
                   "スロットリング")
    _JA_CONTEXT = ("トークン数が上限", "コンテキスト長", "入力が長すぎ", "最大トークン",
                   "トークン超過")

    # ── Korean ────────────────────────────────────────────────────────
    _KO_BLOCKED = ("콘텐츠 정책 위반", "부적절한 콘텐츠", "금지된 콘텐츠",
                   "안전 필터", "정책 위반")
    _KO_CREDIT  = ("잔액 부족", "크레딧 부족", "한도 초과", "요금 미납", "충전 필요")
    _KO_AUTH    = ("인증 실패", "잘못된 API 키", "유효하지 않은 키", "인증 오류",
                   "액세스 거부")
    _KO_RATE    = ("속도 제한", "요청 제한", "너무 많은 요청", "처리율 제한")
    _KO_CONTEXT = ("토큰 초과", "컨텍스트 길이 초과", "입력이 너무 깁니다",
                   "최대 토큰")

    _BLOCKED_KWS = _ZH_BLOCKED + _JA_BLOCKED + _KO_BLOCKED
    _CREDIT_KWS  = _ZH_CREDIT  + _JA_CREDIT  + _KO_CREDIT
    _AUTH_KWS    = _ZH_AUTH    + _JA_AUTH    + _KO_AUTH
    _RATE_KWS    = _ZH_RATE    + _JA_RATE    + _KO_RATE
    _CONTEXT_KWS = _ZH_CONTEXT + _JA_CONTEXT + _KO_CONTEXT

    for kw in _BLOCKED_KWS:
        if kw in msg:
            return ErrorCategory.BLOCKED
    for kw in _CREDIT_KWS:
        if kw in msg:
            return ErrorCategory.CREDIT
    for kw in _AUTH_KWS:
        if kw in msg:
            return ErrorCategory.AUTH
    for kw in _RATE_KWS:
        if kw in msg:
            return ErrorCategory.RATE_LIMIT
    for kw in _CONTEXT_KWS:
        if kw in msg:
            return ErrorCategory.BAD_REQUEST

    return current


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
