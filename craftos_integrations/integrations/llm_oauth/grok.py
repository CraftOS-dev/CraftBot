# -*- coding: utf-8 -*-
"""Grok (xAI) SuperGrok subscription OAuth backend.

xAI publicly endorsed third-party OAuth subscription pass-through in May 2026
(announcements for OpenCode, Hermes, KiloCode). The flow is OAuth 2.0
Authorization Code + PKCE against ``auth.x.ai``, loopback callback to port
56121 by community convention. Issued tokens hit the same
``https://api.x.ai/v1`` host as API-key mode — only the bearer changes.

OIDC discovery: we read the token endpoint from
``https://auth.x.ai/.well-known/openid-configuration`` rather than hardcoding
it, so xAI can rotate URLs without breaking us. The discovery doc is fetched
lazily at login + refresh time and cached for the process lifetime.

Tool-augmented calls (web_search, x_search, code_execution) still bill the
user's underlying xAI account at $5/1k calls — subscription only covers token
inference. We surface this in the connect-success message.

Default client_id can be overridden via settings.json under
``oauth.grok_oauth_client_id`` — useful once xAI lets us register our own
desktop client. Until then we ride the ecosystem-standard public client.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ...credentials_store import (
    has_credential as _store_has_credential,
    load_credential,
    remove_credential,
    save_credential,
)
from ...helpers import request as http_request
from ...logger import get_logger
from ...oauth_flow import OAuthFlow
from ._paste_back import PastebackRegistry, exchange_pasted_code

logger = get_logger(__name__)


# Endpoints — discovery doc is the source of truth at runtime; the constants
# here are fallbacks if OIDC discovery is unreachable.
DISCOVERY_URL = "https://auth.x.ai/.well-known/openid-configuration"
AUTH_URL_FALLBACK = "https://auth.x.ai/oauth2/authorize"
TOKEN_URL_FALLBACK = "https://auth.x.ai/oauth2/token"
API_BASE_URL = "https://api.x.ai/v1"

# Real public client_id registered with xAI by the Hermes Agent team and
# reused by the ysnock404/opencode-grok-auth plugin and the rest of the
# desktop-agent ecosystem (it's a public desktop OAuth value by design,
# not a secret). Sourced from
# https://github.com/ysnock404/opencode-grok-auth/blob/master/src/constants.ts
# and cross-referenced against NousResearch/hermes-agent issue #27385.
# Override at runtime via ConfigStore.get_oauth("GROK_OAUTH_CLIENT_ID")
# once we register a CraftBot-owned client.
DEFAULT_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"

# Loopback callback. 56121 is the registered redirect for the client_id
# above — xAI does exact-string redirect_uri matching, so this is fixed
# until we register our own client. Path must be /callback (no /auth/ prefix).
CALLBACK_PORT = 56121
CALLBACK_PATH = "/callback"

# Scopes required by the registered client_id. Without `grok-cli:access` and
# `api:access`, xAI returns "invalid_scope" — these are bound to the Hermes
# client registration. Default OIDC scopes are also requested so we can
# populate the user's email on the connect-success message.
SCOPES = "openid profile email offline_access grok-cli:access api:access"

# REQUIRED extra params:
#   - referrer=hermes-agent identifies the client family at xAI's authorize
#     endpoint. Without it the client_id check fails ("Missing or invalid
#     client_id") even though the UUID is technically correct.
#     We are going to submit CraftBot as referrer, but before that
#     Gonna use hermes agent as referrer. Sorry Hermes!
#   - plan=generic is the request-tier value the ecosystem uses.
_EXTRA_AUTH_PARAMS = {"referrer": "hermes-agent", "plan": "generic"}

CRED_FILE = "grok_oauth.json"

# Refresh proactively when token has <5min left.
REFRESH_THRESHOLD_SECONDS = 5 * 60


@dataclass
class GrokOAuthCredential:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # unix epoch seconds
    email: str = ""
    plan: str = "SuperGrok"
    client_id: str = ""
    token_url: str = ""


# ════════════════════════════════════════════════════════════════════════
# OIDC discovery (cached per process)
# ════════════════════════════════════════════════════════════════════════

_discovery_cache: Optional[Dict[str, str]] = None


def _discover() -> Dict[str, str]:
    """Fetch xAI's OIDC discovery doc; fall back to hardcoded URLs on error."""
    global _discovery_cache
    if _discovery_cache is not None:
        return _discovery_cache
    fallback = {
        "authorization_endpoint": AUTH_URL_FALLBACK,
        "token_endpoint": TOKEN_URL_FALLBACK,
    }
    result = http_request("GET", DISCOVERY_URL, timeout=10.0)
    if "error" in result:
        logger.warning(
            f"[GROK-OAUTH] OIDC discovery failed ({result['error']}); using fallback URLs"
        )
        _discovery_cache = fallback
        return fallback
    doc = result.get("result") or {}
    _discovery_cache = {
        "authorization_endpoint": doc.get("authorization_endpoint", AUTH_URL_FALLBACK),
        "token_endpoint": doc.get("token_endpoint", TOKEN_URL_FALLBACK),
    }
    return _discovery_cache


def _client_id() -> str:
    """Resolve the OAuth client_id: settings.json override → hardcoded default."""
    from ...config import ConfigStore

    override = ConfigStore.get_oauth("GROK_OAUTH_CLIENT_ID")
    return (override or DEFAULT_CLIENT_ID).strip()


def _build_oauth() -> OAuthFlow:
    disco = _discover()
    # nonce binds the auth response to this request (OIDC). Generated fresh
    # per flow alongside the OAuthFlow-managed state + PKCE verifier.
    extra = dict(_EXTRA_AUTH_PARAMS)
    extra["nonce"] = secrets.token_urlsafe(32)
    return OAuthFlow(
        client_id_literal=_client_id(),
        client_secret_key=None,  # public client; no secret
        auth_url=disco["authorization_endpoint"],
        token_url=disco["token_endpoint"],
        scopes=SCOPES,
        use_pkce=True,
        callback_port=CALLBACK_PORT,
        callback_path=CALLBACK_PATH,
        callback_host="127.0.0.1",
        extra_auth_params=extra,
    )


# ════════════════════════════════════════════════════════════════════════
# Credential I/O — called by tokens.py
# ════════════════════════════════════════════════════════════════════════


def has_credential() -> bool:
    return _store_has_credential(CRED_FILE)


def load() -> Optional[GrokOAuthCredential]:
    return load_credential(CRED_FILE, GrokOAuthCredential)


def remove() -> Tuple[bool, str]:
    if not has_credential():
        return False, "Grok subscription not connected."
    remove_credential(CRED_FILE)
    return True, "Grok subscription disconnected."


def load_and_refresh() -> GrokOAuthCredential:
    """Load the credential, refresh if needed, persist, return."""
    cred = load()
    if cred is None:
        raise RuntimeError("Grok OAuth credential missing")
    now = time.time()
    if cred.expires_at and (cred.expires_at - now) > REFRESH_THRESHOLD_SECONDS:
        return cred
    if not cred.refresh_token:
        raise RuntimeError(
            "Grok access token expired and no refresh token available — reconnect."
        )
    return _refresh(cred)


def _refresh(cred: GrokOAuthCredential) -> GrokOAuthCredential:
    token_url = cred.token_url or _discover()["token_endpoint"]
    result = http_request(
        "POST",
        token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token,
            "client_id": cred.client_id or _client_id(),
        },
        timeout=30.0,
        expected=(200,),
    )
    if "error" in result:
        raise RuntimeError(
            f"Grok token refresh failed: {result.get('details') or result['error']}"
        )
    data = result["result"] or {}
    access = data.get("access_token", "")
    if not access:
        raise RuntimeError("Grok token refresh returned no access_token")
    cred.access_token = access
    # Rotate refresh token if the server issued a new one (OAuth best practice).
    if data.get("refresh_token"):
        cred.refresh_token = data["refresh_token"]
    cred.expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
    save_credential(CRED_FILE, cred)
    return cred


def api_base_url(_cred: GrokOAuthCredential) -> Optional[str]:
    """Subscription tokens hit the same host as API keys for Grok."""
    return API_BASE_URL


def extra_headers(_cred: GrokOAuthCredential) -> Dict[str, str]:
    """No extra headers needed for Grok — the bearer is enough."""
    return {}


# ════════════════════════════════════════════════════════════════════════
# Login flow
# ════════════════════════════════════════════════════════════════════════


# Paste-back state — see ``_paste_back.PastebackRegistry`` docstring.
# xAI's hermes-agent client family sometimes shows a "copy this code into
# your tool" page instead of redirecting to our loopback callback; this
# registry holds the PKCE verifier between prepare_login() and
# complete_login_with_code() so the pasted code can still be exchanged.
_pasteback = PastebackRegistry(provider_label="GROK")


async def prepare_login() -> Dict[str, str]:
    """Open browser and persist a paste-back attempt.

    Returns ``{"auth_url": ..., "attempt_id": ...}``. The caller doesn't
    have to use the attempt_id — ``complete_login_with_code`` defaults
    to the most-recent pending attempt — but exposing it lets a
    multi-attempt UI disambiguate.
    """
    return await _pasteback.prepare(_build_oauth())


def complete_login_with_code(
    code: str, attempt_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Exchange a pasted authorization code for tokens.

    Uses the PKCE verifier persisted during ``prepare_login``. If
    ``attempt_id`` is omitted the most recent pending attempt is used.
    """
    code = (code or "").strip()
    if not code:
        return False, "Paste the code shown on xAI's page first."

    attempt = _pasteback.find(attempt_id)
    if not attempt:
        return False, "No pending Grok sign-in. Click Connect Grok to start over."

    result = exchange_pasted_code(attempt, code)
    if "error" in result and not result.get("access_token"):
        # Don't drop the attempt — user may retry with a corrected code.
        return False, f"Grok token exchange failed: {result['error']}"
    access = result.get("access_token", "")
    if not access:
        return False, "Grok token exchange returned no access token"

    cred = GrokOAuthCredential(
        access_token=access,
        refresh_token=result.get("refresh_token", ""),
        expires_at=time.time() + int(result.get("expires_in", 3600)) - 60,
        email="",
        plan="SuperGrok",
        client_id=_client_id(),
        token_url=_discover()["token_endpoint"],
    )
    save_credential(CRED_FILE, cred)
    matched_id = _pasteback.find_id(attempt_id)
    if matched_id:
        _pasteback.pop(matched_id)
    return True, "Grok subscription connected."


async def run_login() -> Tuple[bool, str]:
    oauth = _build_oauth()
    result = await oauth.run()
    if "error" in result and not result.get("access_token"):
        return False, f"Grok OAuth failed: {result['error']}"
    access = result.get("access_token", "")
    if not access:
        return False, "Grok OAuth returned no access token"
    cred = GrokOAuthCredential(
        access_token=access,
        refresh_token=result.get("refresh_token", ""),
        expires_at=time.time() + int(result.get("expires_in", 3600)) - 60,
        email=(result.get("userinfo") or {}).get("email", ""),
        plan="SuperGrok",
        client_id=_client_id(),
        token_url=_discover()["token_endpoint"],
    )
    save_credential(CRED_FILE, cred)
    note = (
        " Tool-augmented calls (web_search, x_search, code_execution) still"
        " bill your xAI account at $5/1k calls — subscription covers inference only."
    )
    return (
        True,
        f"Grok subscription connected{' as ' + cred.email if cred.email else ''}.{note}",
    )
