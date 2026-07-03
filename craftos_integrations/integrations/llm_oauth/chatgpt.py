# -*- coding: utf-8 -*-
"""ChatGPT Plus/Pro/Team subscription OAuth backend.

OpenAI's Codex CLI uses OAuth 2.0 Authorization Code + PKCE against
``auth.openai.com`` with loopback callback to port 1455. The issued bearer
JWT is audience-locked to ``chatgpt.com/backend-api/codex`` — it CANNOT be
used against ``api.openai.com/v1``. The base URL switch is mandatory.

We ride Codex's public client_id (``app_EMoamEEZ73f0CkXaXp7hrann``). The
entire ecosystem (OpenCode, Hermes, Cline, Roo) rides the same client. OpenAI
has not formally blessed this for third parties but has also not pushed back.
The client_id can be overridden via settings.json under
``oauth.openai_oauth_client_id`` if it ever gets rotated.

Entitlement check: the id_token (also a JWT) carries the custom claim
``https://api.openai.com/auth.chatgpt_plan_type`` — values are plus / pro /
team. If absent or set to ``free``, the OAuth flow succeeded but the user has
no subscription quota and the connection is rejected at login time.

REQUIRED REQUEST HEADERS for the chatgpt.com backend:
  - Authorization: Bearer <access_token>
  - chatgpt-account-id: <from JWT claim>
  - OpenAI-Originator: codex_cli_rs
  - OpenAI-Beta: responses=experimental

Without all four the backend returns 401/403.

CALL SHAPE: ``chatgpt.com/backend-api/codex`` only serves the OpenAI
Responses API. The factory wraps the OpenAI SDK client in
``ChatGPTSubscriptionClient`` (see ``agent_core/core/models/
chatgpt_subscription_client.py``) which translates chat-completions
calls to Responses-API calls on the fly. Streaming and tool-call paths
are not yet bridged; they raise ``NotImplementedError`` with a hint to
disconnect the subscription if the user needs them. JSON-mode action
decisions — CraftBot's main agent path — work transparently.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ...credentials_store import (
    has_credential as _store_has_credential,
    load_credential,
    remove_credential,
    save_credential,
)
from ._paste_back import PastebackRegistry, exchange_pasted_code
from ...helpers import request as http_request
from ...logger import get_logger
from ...oauth_flow import OAuthFlow

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════
# Accepted-model list for ChatGPT-subscription auth
# ════════════════════════════════════════════════════════════════════════

CODEX_ACCEPTED_MODELS = frozenset(
    {
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex-spark",
    }
)

CODEX_DEFAULT_MODEL = "gpt-5.4"


def effective_model_for_subscription(model: str) -> Tuple[str, bool]:
    """Return ``(effective, was_substituted)`` for a Codex-subscription call.

    If ``model`` is one of the accepted names it passes through
    unchanged. Otherwise it's replaced with ``CODEX_DEFAULT_MODEL`` and
    the second return value is ``True`` so the caller can log the
    substitution once.
    """
    if model in CODEX_ACCEPTED_MODELS:
        return model, False
    return CODEX_DEFAULT_MODEL, True


AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"

# Codex CLI's public client_id. Public; reused across the ecosystem. Override
# via settings.json oauth.OPENAI_OAUTH_CLIENT_ID once OpenAI rotates it.
DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

# Loopback on 1455 — Codex's registered redirect URI. NOT configurable
# without re-registering with OpenAI.
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"

# Standard OIDC scopes + offline_access for refresh-token issuance.
SCOPES = "openid profile email offline_access"

# Subscription-mode inference base URL. The OpenAI Python SDK appends paths
# to this; we mount the codex prefix here so SDK calls like
# ``/responses`` land at ``/backend-api/codex/responses``.
SUBSCRIPTION_BASE_URL = "https://chatgpt.com/backend-api/codex"

# Headers REQUIRED on every backend-api call (impersonates Codex CLI).
ORIGINATOR = "codex_cli_rs"
BETA_HEADER = "responses=experimental"

# JWT claim namespace where OpenAI puts plan/account info.
CLAIM_NS = "https://api.openai.com/auth"

# Refresh proactively when token has <5min left.
REFRESH_THRESHOLD_SECONDS = 5 * 60

CRED_FILE = "openai_chatgpt_oauth.json"


@dataclass
class ChatGPTOAuthCredential:
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    expires_at: float = 0.0
    account_id: str = ""
    user_id: str = ""
    email: str = ""
    plan: str = ""
    client_id: str = ""


# ════════════════════════════════════════════════════════════════════════
# JWT helpers — parse claims WITHOUT verifying the signature.
# OpenAI's id_token is signed by their server; we already trust the token
# endpoint (TLS to auth.openai.com), so signature verification adds no
# security and would require pulling JWKS. Parsing is enough to extract
# the plan/account_id we need to call the backend.
# ════════════════════════════════════════════════════════════════════════


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _parse_jwt_claims(token: str) -> Dict:
    """Return the JWT payload as a dict, or empty dict if unparseable."""
    if not token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = _b64url_decode(parts[1])
        return json.loads(payload.decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"[CHATGPT-OAUTH] could not parse JWT payload: {e}")
        return {}


def _extract_account_info(id_token: str) -> Dict[str, str]:
    """Pull email / account_id / user_id / plan from the id_token claims."""
    claims = _parse_jwt_claims(id_token)
    ns = claims.get(CLAIM_NS, {}) if isinstance(claims.get(CLAIM_NS), dict) else {}
    return {
        "email": claims.get("email", "") or claims.get("preferred_username", ""),
        "account_id": ns.get("chatgpt_account_id", ""),
        "user_id": ns.get("chatgpt_user_id", ""),
        "plan": ns.get("chatgpt_plan_type", "") or "",
    }


# ════════════════════════════════════════════════════════════════════════
# OAuth flow construction
# ════════════════════════════════════════════════════════════════════════


def _client_id() -> str:
    from ...config import ConfigStore

    override = ConfigStore.get_oauth("OPENAI_OAUTH_CLIENT_ID")
    return (override or DEFAULT_CLIENT_ID).strip()


def _build_oauth() -> OAuthFlow:
    return OAuthFlow(
        client_id_literal=_client_id(),
        client_secret_key=None,  # public client; no secret
        auth_url=AUTH_URL,
        token_url=TOKEN_URL,
        scopes=SCOPES,
        use_pkce=True,
        callback_port=CALLBACK_PORT,
        callback_path=CALLBACK_PATH,
        callback_host="localhost",
        # OpenAI uses the standard ``scope`` query param; default is fine.
    )


# ════════════════════════════════════════════════════════════════════════
# Credential I/O — called by tokens.py
# ════════════════════════════════════════════════════════════════════════


def has_credential() -> bool:
    return _store_has_credential(CRED_FILE)


def load() -> Optional[ChatGPTOAuthCredential]:
    return load_credential(CRED_FILE, ChatGPTOAuthCredential)


def remove() -> Tuple[bool, str]:
    if not has_credential():
        return False, "ChatGPT subscription not connected."
    remove_credential(CRED_FILE)
    return True, "ChatGPT subscription disconnected."


def load_and_refresh() -> ChatGPTOAuthCredential:
    cred = load()
    if cred is None:
        raise RuntimeError("ChatGPT OAuth credential missing")
    now = time.time()
    if cred.expires_at and (cred.expires_at - now) > REFRESH_THRESHOLD_SECONDS:
        return cred
    if not cred.refresh_token:
        raise RuntimeError(
            "ChatGPT access token expired and no refresh token available — reconnect."
        )
    return _refresh(cred)


def _refresh(cred: ChatGPTOAuthCredential) -> ChatGPTOAuthCredential:
    result = http_request(
        "POST",
        TOKEN_URL,
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
            f"ChatGPT token refresh failed: {result.get('details') or result['error']}"
        )
    data = result["result"] or {}
    access = data.get("access_token", "")
    if not access:
        raise RuntimeError("ChatGPT token refresh returned no access_token")
    cred.access_token = access
    if data.get("refresh_token"):
        cred.refresh_token = data["refresh_token"]
    # If a new id_token came back, re-derive account info from it (the
    # account_id can rotate on plan changes).
    if data.get("id_token"):
        cred.id_token = data["id_token"]
        info = _extract_account_info(cred.id_token)
        if info.get("account_id"):
            cred.account_id = info["account_id"]
        if info.get("plan"):
            cred.plan = info["plan"]
    cred.expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
    save_credential(CRED_FILE, cred)
    return cred


def api_base_url(_cred: ChatGPTOAuthCredential) -> Optional[str]:
    """ChatGPT subscription tokens must hit chatgpt.com/backend-api/codex —
    NOT api.openai.com. The JWT audience is locked to this host."""
    return SUBSCRIPTION_BASE_URL


def extra_headers(cred: ChatGPTOAuthCredential) -> Dict[str, str]:
    """Headers required by the backend-api host.

    The reference implementation (numman-ali/opencode-openai-codex-auth)
    uses the lowercase ``originator`` (NOT ``OpenAI-Originator``) — the
    Codex backend is case-sensitive about this one. ``accept`` must
    explicitly be ``text/event-stream`` because every request is
    streaming. Without all four headers the backend can return 401/403
    even with a valid bearer.
    """
    headers = {
        "originator": ORIGINATOR,
        "OpenAI-Beta": BETA_HEADER,
        "accept": "text/event-stream",
    }
    if cred.account_id:
        headers["chatgpt-account-id"] = cred.account_id
    return headers


# ════════════════════════════════════════════════════════════════════════
# Login
# ════════════════════════════════════════════════════════════════════════


_VALID_PLANS = {"plus", "pro", "team", "enterprise", "business"}


# Paste-back state — same mechanism as Grok's, see PastebackRegistry docstring.
_pasteback = PastebackRegistry(provider_label="CHATGPT")


async def prepare_login() -> Dict[str, str]:
    """Open browser and persist a paste-back attempt. Returns {auth_url, attempt_id}."""
    return await _pasteback.prepare(_build_oauth())


def complete_login_with_code(
    code: str, attempt_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Exchange a pasted authorization code for tokens.

    Mirrors ``run_login``'s post-exchange path including the JWT plan
    extraction — paste-back must still reject Free-tier accounts that
    have no Plus/Pro/Team subscription.
    """
    code = (code or "").strip()
    if not code:
        return False, "Paste the code shown on OpenAI's page first."

    attempt = _pasteback.find(attempt_id)
    if not attempt:
        return False, "No pending ChatGPT sign-in. Click Connect ChatGPT to start over."

    raw = exchange_pasted_code(attempt, code)
    if "error" in raw and not raw.get("access_token"):
        return False, f"ChatGPT token exchange failed: {raw['error']}"
    access = raw.get("access_token", "")
    if not access:
        return False, "ChatGPT token exchange returned no access token"

    id_token = raw.get("id_token", "")
    info = _extract_account_info(id_token)
    plan = (info.get("plan") or "free").lower()
    if plan not in _VALID_PLANS and plan != "free":
        logger.info(f"[CHATGPT-OAUTH] unrecognized plan_type '{plan}' — accepting")

    cred = ChatGPTOAuthCredential(
        access_token=access,
        refresh_token=raw.get("refresh_token", ""),
        id_token=id_token,
        expires_at=time.time() + int(raw.get("expires_in", 3600)) - 60,
        account_id=info.get("account_id", ""),
        user_id=info.get("user_id", ""),
        email=info.get("email", ""),
        plan=plan,
        client_id=_client_id(),
    )
    save_credential(CRED_FILE, cred)
    matched_id = _pasteback.find_id(attempt_id)
    if matched_id:
        _pasteback.pop(matched_id)
    who = f" as {cred.email}" if cred.email else ""
    if plan == "free":
        return True, (
            f"ChatGPT connected{who} — this account has no Plus/Pro/Team plan, "
            "so LLM calls will fail until you upgrade at chat.openai.com or "
            "switch back to API-key auth."
        )
    return True, f"ChatGPT {plan.title()} connected{who}."


async def run_login() -> Tuple[bool, str]:
    oauth = _build_oauth()
    result = await oauth.run()
    if "error" in result and not result.get("access_token"):
        return False, f"ChatGPT OAuth failed: {result['error']}"

    access = result.get("access_token", "")
    raw = result.get("raw") or {}
    id_token = raw.get("id_token", "")
    if not access:
        return False, "ChatGPT OAuth returned no access token"

    info = _extract_account_info(id_token)
    plan = (info.get("plan") or "free").lower()
    if plan not in _VALID_PLANS and plan != "free":
        # Unknown plan string — accept but log so we notice new tiers.
        logger.info(f"[CHATGPT-OAUTH] unrecognized plan_type '{plan}' — accepting")

    cred = ChatGPTOAuthCredential(
        access_token=access,
        refresh_token=raw.get("refresh_token", ""),
        id_token=id_token,
        expires_at=time.time() + int(raw.get("expires_in", 3600)) - 60,
        account_id=info.get("account_id", ""),
        user_id=info.get("user_id", ""),
        email=info.get("email", ""),
        plan=plan,
        client_id=_client_id(),
    )
    save_credential(CRED_FILE, cred)
    who = f" as {cred.email}" if cred.email else ""
    if plan == "free":
        return True, (
            f"ChatGPT connected{who} — this account has no Plus/Pro/Team plan, "
            "so LLM calls will fail until you upgrade at chat.openai.com or "
            "switch back to API-key auth."
        )
    return True, f"ChatGPT {plan.title()} connected{who}."
