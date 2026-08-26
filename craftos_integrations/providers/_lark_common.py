# -*- coding: utf-8 -*-
"""Shared Lark scaffolding — used by every Lark-service integration.

Underscore prefix → autoloader skips this module. It's package-internal,
imported by ``lark.py`` (messaging) and ``lark_drive.py``, with future
siblings (calendar, docs, bitable, …) following the same shape.

What it provides
----------------

  - ``LarkCredential`` — single dataclass shape for every Lark service's
    credential file. All services share the same shape because all use
    the same Custom App's App ID + Secret + cached tenant_access_token.
    Bot-specific fields (``bot_name``, ``bot_open_id``) are populated
    only by the messaging integration; non-messaging services leave
    them empty.

  - ``LARK_API_BASE`` — the global Lark host. Feishu (China region)
    differs only in this constant; the API surface is identical.

  - ``validate_and_mint_token(app_id, app_secret)`` — one-shot credential
    validation used by every handler's ``login()``. Returns
    ``(token, expires_at, error)``.

  - ``ensure_token(cred, cred_file)`` — refresh-if-needed token getter.
    Mutates ``cred`` in place and persists to ``cred_file`` when a
    refresh actually happens. Each service holds its own credential
    file with its own cached token (no cross-service sharing).

  - ``make_headers(cred, cred_file)`` — bearer + JSON content-type. All
    Lark REST calls use this shape.

Why a separate file per service uses its own credential file
-------------------------------------------------------------

Even though every Lark service is authorized via the *same* Custom App,
the user wires each service as a sibling integration in the registry
(matches the ``google_*.py`` pattern). Each gets its own ``IntegrationSpec``
with its own ``cred_file`` so that connect/disconnect status is
per-service in the UI. The user pastes the same App ID + Secret into
each one — slight UX redundancy, paid back in clean independence
between services.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .. import save_credential
from ..helpers import request as http_request

LARK_API_BASE = "https://open.larksuite.com/open-apis"


@dataclass
class LarkCredential:
    app_id: str = ""
    app_secret: str = ""
    # Cached tenant_access_token + its absolute Unix expiry. Saved so we
    # don't mint a new token on every restart, but always refresh when
    # within 60s of expiry (defensive — Lark's clocks vs ours).
    tenant_access_token: str = ""
    token_expires_at: float = 0.0
    # Bot-specific (messaging integration only). Non-messaging services
    # leave these empty; they're carried in the shared shape so that
    # ``credentials_store._load_dataclass`` survives schema reads of
    # files written by either kind of handler.
    bot_name: str = ""
    bot_open_id: str = ""


def validate_and_mint_token(
    app_id: str, app_secret: str
) -> Tuple[Optional[str], float, Optional[str]]:
    """Validate App ID + Secret by minting a tenant_access_token.

    Returns ``(token, expires_at_unix, error_msg)``. On success, ``error_msg``
    is None. Lark returns 200 OK with ``code != 0`` on bad credentials, so
    we have to inspect the body — HTTP status alone isn't enough.
    """
    result = http_request(
        "POST",
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        expected=(200,),
    )
    if "error" in result:
        return None, 0.0, f"Lark auth request failed: {result['error']}"
    body = result.get("result", {})
    if body.get("code", -1) != 0:
        return (
            None,
            0.0,
            f"Invalid Lark credentials: {body.get('msg', 'unknown error')}",
        )
    token = body.get("tenant_access_token", "")
    expire = float(body.get("expire", 0))
    return token, time.time() + expire, None


def ensure_token(cred: LarkCredential, cred_file: str) -> str:
    """Return a valid tenant_access_token, refreshing if within 60s of expiry.

    Mutates ``cred`` and writes it back to ``cred_file`` on refresh, so
    sibling processes / restarts reuse the cached token instead of minting
    fresh on every call.
    """
    now = time.time()
    if cred.tenant_access_token and cred.token_expires_at > now + 60:
        return cred.tenant_access_token
    result = http_request(
        "POST",
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": cred.app_id, "app_secret": cred.app_secret},
        expected=(200,),
    )
    if "error" in result:
        raise RuntimeError(f"Lark token refresh failed: {result['error']}")
    body = result.get("result", {})
    if body.get("code", -1) != 0:
        raise RuntimeError(f"Lark token refresh rejected: {body.get('msg', 'unknown')}")
    token = body.get("tenant_access_token", "")
    expire = float(body.get("expire", 0))
    cred.tenant_access_token = token
    cred.token_expires_at = now + expire
    save_credential(cred_file, cred)
    return token


def make_headers(cred: LarkCredential, cred_file: str) -> Dict[str, str]:
    """Bearer + JSON content-type. Used by every Lark REST call."""
    return {
        "Authorization": f"Bearer {ensure_token(cred, cred_file)}",
        "Content-Type": "application/json; charset=utf-8",
    }
