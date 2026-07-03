# -*- coding: utf-8 -*-
"""Shared token plumbing for subscription-OAuth LLM backends.

One public function the factory cares about — ``get_bearer(provider)``:

    bearer = get_bearer("openai")
    if bearer is not None:
        access_token, base_url, extra_headers = bearer
        # build subscription-mode client
    else:
        # fall back to stored API key

The provider arg is the LLM-factory provider name (``openai``, ``grok``),
NOT the OAuth credential slug — the mapping lives here. Returning ``None``
means "no subscription connected; caller should fall back". A raised
``RuntimeError`` means "connected but the refresh blew up" — caller should
surface the message so the user can reconnect.

Refresh contract: every call checks the on-disk credential, refreshes if it
expires in <5 min, persists the new tokens, returns a still-fresh access
token. We do NOT cache in memory — settings.json + .credentials/ remain the
single source of truth so a manual disconnect from another process is picked
up immediately. Per-provider locks prevent thundering-herd refreshes when N
parallel agent tasks all hit expiry at once.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

# Module-level locks, one per provider, allocated lazily.
_refresh_locks: Dict[str, threading.Lock] = {}


def _lock_for(provider: str) -> threading.Lock:
    if provider not in _refresh_locks:
        _refresh_locks[provider] = threading.Lock()
    return _refresh_locks[provider]


# The factory's provider name → the OAuth backend module that handles it.
# Anthropic is intentionally absent: Pro/Max OAuth is forbidden by ToS
# since Feb 2026. Adding it here would silently re-enable a banned path.
def _backend_for(provider: str):
    if provider == "openai":
        from . import chatgpt

        return chatgpt
    if provider == "grok":
        from . import grok

        return grok
    return None


# ════════════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════════════


def get_bearer(provider: str) -> Optional[Tuple[str, Optional[str], Dict[str, str]]]:
    """Return (access_token, base_url, extra_headers) for a subscription-mode
    LLM call, or ``None`` if the user hasn't connected this provider.

    ``base_url`` is the API host the bearer is valid against (ChatGPT
    subscription tokens hit ``chatgpt.com/backend-api/codex`` rather than
    ``api.openai.com``; Grok subscription tokens hit the same
    ``api.x.ai/v1`` as API-key mode — backend returns ``None`` if no
    base-URL override is needed).
    """
    backend = _backend_for(provider)
    if backend is None:
        return None
    if not backend.has_credential():
        return None
    with _lock_for(provider):
        try:
            cred = backend.load_and_refresh()
        except Exception as e:
            from ...logger import get_logger

            get_logger(__name__).error(f"[LLM-OAUTH] {provider} refresh failed: {e}")
            raise RuntimeError(
                f"{provider} subscription session expired and refresh failed: {e}. "
                f"Reconnect from Settings."
            ) from e
    return cred.access_token, backend.api_base_url(cred), backend.extra_headers(cred)


def has_credential(provider: str) -> bool:
    """True if there's an OAuth credential on disk for this provider."""
    backend = _backend_for(provider)
    return backend is not None and backend.has_credential()


def status(provider: str) -> Dict[str, object]:
    """UI-friendly summary: connected / account / plan / expiry."""
    backend = _backend_for(provider)
    if backend is None:
        return {"supported": False, "connected": False}
    if not backend.has_credential():
        return {"supported": True, "connected": False}
    cred = backend.load()
    if cred is None:
        return {"supported": True, "connected": False}
    return {
        "supported": True,
        "connected": True,
        "email": getattr(cred, "email", "") or "",
        "plan": getattr(cred, "plan", "") or "",
        "expires_at": getattr(cred, "expires_at", 0),
        "expires_in_seconds": max(0, int(getattr(cred, "expires_at", 0) - time.time())),
    }


async def connect(provider: str) -> Tuple[bool, str]:
    """Run the OAuth flow for this provider. Browser opens, user signs in."""
    backend = _backend_for(provider)
    if backend is None:
        return False, f"Subscription auth not supported for '{provider}'"
    return await backend.run_login()


def disconnect(provider: str) -> Tuple[bool, str]:
    """Remove stored OAuth credentials. No server-side revocation —
    refresh tokens expire on their own."""
    backend = _backend_for(provider)
    if backend is None:
        return False, f"Subscription auth not supported for '{provider}'"
    return backend.remove()


# ════════════════════════════════════════════════════════════════════════
# Paste-back flow — opens browser, hands the user a textbox to paste back
# the authorization code when the provider's auth UI shows a "copy this
# code into your tool" page instead of redirecting to our loopback.
# ════════════════════════════════════════════════════════════════════════


async def prepare_connect(provider: str) -> Tuple[bool, Dict[str, Any]]:
    """Open browser, persist a PKCE attempt, return the auth URL and an
    attempt_id. The user then pastes the code shown on the provider's page
    into the UI and ``complete_connect`` finalizes the exchange.

    Returns ``(True, {auth_url, attempt_id})`` or
    ``(False, {error: ...})``.
    """
    backend = _backend_for(provider)
    if backend is None:
        return False, {"error": f"Subscription auth not supported for '{provider}'"}
    if not hasattr(backend, "prepare_login"):
        return False, {"error": "Paste-back not implemented for this provider"}
    try:
        info = await backend.prepare_login()
    except Exception as e:
        from ...logger import get_logger

        get_logger(__name__).error(f"[LLM-OAUTH] prepare {provider} failed: {e}")
        return False, {"error": str(e)}
    return True, info


def complete_connect(
    provider: str, code: str, attempt_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Exchange the pasted code for tokens using the persisted PKCE verifier."""
    backend = _backend_for(provider)
    if backend is None:
        return False, f"Subscription auth not supported for '{provider}'"
    if not hasattr(backend, "complete_login_with_code"):
        return False, "Paste-back not implemented for this provider"
    return backend.complete_login_with_code(code, attempt_id)
