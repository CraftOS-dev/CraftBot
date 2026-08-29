# -*- coding: utf-8 -*-
"""GitHub Copilot subscription OAuth backend (Phase 6 subset,
docs/PROVIDER_LAYER_CATCHUP.md).

Flow (both competitors ship the same shape):
  1. GitHub DEVICE FLOW: POST github.com/login/device/code -> user_code +
     verification_uri; open the browser; poll login/oauth/access_token until
     the user authorizes. Yields a long-lived ``gho_``/``ghu_`` OAuth token
     (no refresh token — it does not expire).
  2. COPILOT BEARER: exchange the GitHub token at
     api.github.com/copilot_internal/v2/token for a short-lived (~30 min)
     bearer valid against api.githubcopilot.com. ``load_and_refresh``
     re-exchanges when <5 min from expiry — same refresh contract as the
     other backends, driven per-request by ``tokens.get_bearer``.

The inference surface is OpenAI-compatible chat completions at
https://api.githubcopilot.com with Copilot's editor headers, so the
existing chat_completions transport works unchanged.

NOTE: written against GitHub's documented device flow + the de-facto
Copilot token exchange used by the ecosystem (OpenClaw, Hermes); not yet
exercised against a live Copilot seat from this environment — the first
real connect is the acceptance test.
"""

from __future__ import annotations

import asyncio
import os
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import httpx

from ..credentials_store import (
    has_credential as _store_has,
    load_credential as _store_load,
    remove_credential as _store_remove,
    save_credential as _store_save,
)
from ..logger import get_logger

logger = get_logger(__name__)

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
USER_URL = "https://api.github.com/user"
API_BASE_URL = "https://api.githubcopilot.com"

# VS Code's public GitHub OAuth client id — the id the Copilot ecosystem's
# device-flow tools authenticate as. Override with COPILOT_CLIENT_ID.
DEFAULT_CLIENT_ID = "01ab8ac9400c4e429b23"
SCOPES = "read:user"

CRED_FILE = "copilot_oauth.json"
REFRESH_THRESHOLD_SECONDS = 5 * 60
DEVICE_FLOW_TIMEOUT_SECONDS = 15 * 60

# Copilot's API rejects requests without editor identification headers.
EDITOR_HEADERS = {
    "Editor-Version": "vscode/1.99.0",
    "Editor-Plugin-Version": "copilot-chat/0.26.0",
    "Copilot-Integration-Id": "vscode-chat",
}


@dataclass
class CopilotOAuthCredential:
    github_token: str = ""  # long-lived gho_/ghu_ OAuth token
    access_token: str = ""  # short-lived Copilot bearer
    expires_at: float = 0.0  # Copilot bearer expiry (epoch seconds)
    email: str = ""  # GitHub login, for the settings UI
    plan: str = field(default="copilot")


def _client_id() -> str:
    return os.environ.get("COPILOT_CLIENT_ID") or DEFAULT_CLIENT_ID


# ─────────────────────────── store plumbing ───────────────────────────


def has_credential() -> bool:
    return _store_has(CRED_FILE)


def load() -> Optional[CopilotOAuthCredential]:
    return _store_load(CRED_FILE, CopilotOAuthCredential)


def remove() -> Tuple[bool, str]:
    removed = _store_remove(CRED_FILE)
    return (
        (True, "GitHub Copilot disconnected.")
        if removed
        else (
            False,
            "No Copilot credential to remove.",
        )
    )


# ─────────────────────────── bearer contract ───────────────────────────


def _exchange_copilot_bearer(github_token: str) -> Tuple[str, float]:
    """GitHub OAuth token -> short-lived Copilot bearer + expiry."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
                **EDITOR_HEADERS,
            },
        )
    if resp.status_code in (401, 403):
        raise RuntimeError(
            "GitHub rejected the stored token (revoked, or the account has "
            "no active Copilot subscription). Reconnect from Settings."
        )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"Copilot token exchange returned no token: {data}")
    expires_at = float(data.get("expires_at") or (time.time() + 25 * 60))
    return token, expires_at


def load_and_refresh() -> CopilotOAuthCredential:
    cred = load()
    if cred is None or not cred.github_token:
        raise RuntimeError("No Copilot credential on disk.")
    if cred.access_token and cred.expires_at - time.time() > REFRESH_THRESHOLD_SECONDS:
        return cred
    token, expires_at = _exchange_copilot_bearer(cred.github_token)
    cred.access_token = token
    cred.expires_at = expires_at
    _store_save(CRED_FILE, cred)
    return cred


def api_base_url(_cred: CopilotOAuthCredential) -> Optional[str]:
    return API_BASE_URL


def extra_headers(_cred: CopilotOAuthCredential) -> Dict[str, str]:
    return dict(EDITOR_HEADERS)


# ─────────────────────────── device-flow login ───────────────────────────


async def run_login() -> Tuple[bool, str]:
    """GitHub device flow: open the verification page, poll until authorized."""

    def _start() -> dict:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                DEVICE_CODE_URL,
                data={"client_id": _client_id(), "scope": SCOPES},
                headers={"Accept": "application/json"},
            )
        resp.raise_for_status()
        return resp.json()

    try:
        start = await asyncio.to_thread(_start)
    except Exception as e:
        return False, f"Could not start the GitHub device flow: {e}"

    device_code = start.get("device_code")
    user_code = start.get("user_code")
    verification_uri = (
        start.get("verification_uri") or "https://github.com/login/device"
    )
    interval = int(start.get("interval") or 5)
    if not device_code or not user_code:
        return False, f"GitHub device flow returned an unexpected payload: {start}"

    logger.info(f"[COPILOT] Enter code {user_code} at {verification_uri}")
    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass

    def _poll_once() -> dict:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                ACCESS_TOKEN_URL,
                data={
                    "client_id": _client_id(),
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
        resp.raise_for_status()
        return resp.json()

    deadline = time.time() + DEVICE_FLOW_TIMEOUT_SECONDS
    github_token: Optional[str] = None
    while time.time() < deadline:
        await asyncio.sleep(interval)
        try:
            result = await asyncio.to_thread(_poll_once)
        except Exception as e:
            return False, f"Device-flow polling failed: {e}"
        error = result.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error in ("expired_token", "access_denied"):
            return False, f"GitHub device flow ended: {error}. Try again."
        if error:
            return False, f"GitHub device flow error: {error}"
        github_token = result.get("access_token")
        if github_token:
            break
    if not github_token:
        return False, (
            f"Timed out waiting for authorization. Enter code {user_code} at "
            f"{verification_uri} and try again."
        )

    # Verify the seat by exchanging for a Copilot bearer right away.
    try:
        access_token, expires_at = await asyncio.to_thread(
            _exchange_copilot_bearer, github_token
        )
    except Exception as e:
        return False, str(e)

    login = ""
    try:

        def _whoami() -> str:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    USER_URL,
                    headers={
                        "Authorization": f"token {github_token}",
                        "Accept": "application/json",
                    },
                )
            return resp.json().get("login", "") if resp.status_code == 200 else ""

        login = await asyncio.to_thread(_whoami)
    except Exception:
        pass

    _store_save(
        CRED_FILE,
        CopilotOAuthCredential(
            github_token=github_token,
            access_token=access_token,
            expires_at=expires_at,
            email=login,
        ),
    )
    who = f" as {login}" if login else ""
    return True, f"GitHub Copilot connected{who}."
