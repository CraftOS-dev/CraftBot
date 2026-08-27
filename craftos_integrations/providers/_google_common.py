# -*- coding: utf-8 -*-
"""Shared Google OAuth scaffolding — used by every Google-service integration.

Underscore prefix → autoloader skips this module. It's package-internal,
imported by the per-service integrations (``gmail.py``, ``google_calendar.py``,
``google_drive.py``, ``google_docs.py``, ``google_youtube.py``).

What it provides
----------------

  - ``GoogleCredential`` — single dataclass shape for every Google service's
    credential file. All services use the same shape because they all hold
    the same kind of token; they just differ in *which* file the token is
    saved to.

  - ``GMAIL_SCOPES``, ``CALENDAR_SCOPES``, ``DRIVE_SCOPES``, ``DOCS_SCOPES``,
    ``YOUTUBE_SCOPES``, ``USERINFO_SCOPES`` — per-service scope strings.
    ``ALL_GOOGLE_SCOPES`` is the union (used by the "connect everything"
    workspace integration).

  - ``make_google_oauth(scopes)`` — factory returning a per-service
    ``OAuthFlow`` instance. Each handler holds its own; differs from the
    others only in scope.

  - ``GoogleApiClientMixin`` — composition mixin for per-service clients.
    Centralizes load-credential / refresh-token / build-auth-headers so each
    service's Client doesn't duplicate those ~40 lines.

  - ``run_google_login(spec, oauth_flow)`` — shared async login implementation.
    Each per-service handler's ``login()`` is a one-liner that delegates here.

Composition over inheritance: the per-service Client subclasses
``BasePlatformClient`` (the package's runtime ABC) AND mixes in
``GoogleApiClientMixin`` for token plumbing. The Handler holds an
``OAuthFlow`` instance from ``make_google_oauth`` (composition).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .. import (
    IntegrationSpec,
    OAuthFlow,
    has_credential,
    load_credential,
    remove_credential,
    save_credential,
)
from ..config import ConfigStore
from ..helpers import request as http_request
from ..logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════
# OAuth / API URLs
# ════════════════════════════════════════════════════════════════════════

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# ════════════════════════════════════════════════════════════════════════
# Per-service scopes
# ════════════════════════════════════════════════════════════════════════

# Always requested alongside the service scope so we can populate
# ``GoogleCredential.email`` from the userinfo endpoint.
USERINFO_SCOPES = (
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile"
)

GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPES = "https://www.googleapis.com/auth/calendar"
DRIVE_SCOPES = "https://www.googleapis.com/auth/drive"
DOCS_SCOPES = "https://www.googleapis.com/auth/documents"
YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly "
    "https://www.googleapis.com/auth/youtube.force-ssl"
)
CONTACTS_SCOPES = "https://www.googleapis.com/auth/contacts.readonly"

# Union — used by the "connect everything" Workspace integration.
ALL_GOOGLE_SCOPES = " ".join(
    [
        GMAIL_SCOPES,
        CALENDAR_SCOPES,
        DRIVE_SCOPES,
        CONTACTS_SCOPES,
        USERINFO_SCOPES,
        YOUTUBE_SCOPES,
    ]
)


# ════════════════════════════════════════════════════════════════════════
# Credential dataclass (shared across all Google services)
# ════════════════════════════════════════════════════════════════════════


@dataclass
class GoogleCredential:
    """Shape of every Google service's credential file.

    Each service writes the same shape but to a different file
    (``gmail.json``, ``gcal.json``, …). When the workspace meta-integration
    connects, it cascades the same credential into all per-service files.
    """

    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    client_id: str = ""
    client_secret: str = ""
    email: str = ""


# ════════════════════════════════════════════════════════════════════════
# OAuthFlow factory — composition for handlers
# ════════════════════════════════════════════════════════════════════════


def make_google_oauth(scopes: str) -> OAuthFlow:
    """Build the per-service ``OAuthFlow``. The userinfo scopes are always
    appended so we can capture the user's email regardless of which service
    is being connected."""
    return OAuthFlow(
        client_id_key="GOOGLE_CLIENT_ID",
        client_secret_key="GOOGLE_CLIENT_SECRET",
        auth_url=GOOGLE_AUTH_URL,
        token_url=GOOGLE_TOKEN_URL,
        userinfo_url=GOOGLE_USERINFO_URL,
        scopes=f"{scopes} {USERINFO_SCOPES}".strip(),
        use_pkce=True,
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
    )


# ════════════════════════════════════════════════════════════════════════
# Shared login / logout / status helpers — called by per-service handlers
# ════════════════════════════════════════════════════════════════════════


async def run_google_login(
    spec: IntegrationSpec,
    oauth: OAuthFlow,
    display_name: str,
) -> Tuple[bool, str]:
    """Run the OAuth flow and persist the credential to the spec's file.
    Each per-service handler's ``login()`` calls into this — one place to
    change if Google ever changes the auth shape."""
    result = await oauth.run()
    if "error" in result and not result.get("access_token"):
        return False, f"{display_name} OAuth failed: {result['error']}"

    info = result.get("userinfo", {})
    save_credential(
        spec.cred_file,
        GoogleCredential(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token", ""),
            token_expiry=time.time() + result.get("expires_in", 3600),
            client_id=ConfigStore.get_oauth("GOOGLE_CLIENT_ID"),
            client_secret=ConfigStore.get_oauth("GOOGLE_CLIENT_SECRET"),
            email=info.get("email", ""),
        ),
    )
    return True, f"{display_name} connected as {info.get('email')}"


async def run_google_logout(
    spec: IntegrationSpec,
    display_name: str,
) -> Tuple[bool, str]:
    """Standard logout: just remove the credential file. Server-side
    invalidation isn't necessary for Google — the refresh token expires
    naturally and access tokens are short-lived."""
    if not has_credential(spec.cred_file):
        return False, f"No {display_name} credentials found."
    remove_credential(spec.cred_file)
    return True, f"Removed {display_name} credential."


async def run_google_status(
    spec: IntegrationSpec,
    display_name: str,
) -> Tuple[bool, str]:
    """Standard status: connected/not-connected based on credential file."""
    if not has_credential(spec.cred_file):
        return True, f"{display_name}: Not connected"
    cred = load_credential(spec.cred_file, GoogleCredential)
    email = cred.email if cred else "unknown"
    return True, f"{display_name}: Connected\n  - {email}"


# ════════════════════════════════════════════════════════════════════════
# Client mixin — shared token plumbing for every per-service Client
# ════════════════════════════════════════════════════════════════════════


class GoogleApiClientMixin:
    """Composition mixin: gives a Client class the shared Google token
    machinery (load credential, refresh on expiry, build auth headers).

    Used by the per-service Clients alongside ``BasePlatformClient``::

        class GmailClient(BasePlatformClient, GoogleApiClientMixin):
            spec = GMAIL_SPEC
            ...

    The mixin reads ``self.spec`` (set by the subclass) to know which
    credential file to load. No state is kept on the mixin itself; every
    method reads/writes through ``self._cred`` on the subclass instance.
    """

    spec: IntegrationSpec  # subclass provides this
    _cred: Optional[GoogleCredential]  # subclass declares in __init__

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> GoogleCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, GoogleCredential)
        if self._cred is None:
            raise RuntimeError(
                f"No {self.spec.name} credentials. Connect the integration first."
            )
        return self._cred

    def _ensure_token(self) -> str:
        cred = self._load()
        if cred.refresh_token and cred.token_expiry and time.time() > cred.token_expiry:
            refreshed = self.refresh_access_token()
            if refreshed:
                return refreshed
        return cred.access_token

    def refresh_access_token(self) -> Optional[str]:
        cred = self._load()
        if not all([cred.client_id, cred.client_secret, cred.refresh_token]):
            return None
        result = http_request(
            "POST",
            GOOGLE_TOKEN_URL,
            data={
                "client_id": cred.client_id,
                "client_secret": cred.client_secret,
                "refresh_token": cred.refresh_token,
                "grant_type": "refresh_token",
            },
            expected=(200,),
        )
        if "error" in result:
            return None
        data = result["result"]
        cred.access_token = data["access_token"]
        cred.token_expiry = time.time() + data.get("expires_in", 3600) - 60
        save_credential(self.spec.cred_file, cred)
        self._cred = cred
        return cred.access_token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def _auth_header(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_token()}"}


__all__ = [
    "GoogleCredential",
    "GoogleApiClientMixin",
    "GOOGLE_AUTH_URL",
    "GOOGLE_TOKEN_URL",
    "GOOGLE_USERINFO_URL",
    "USERINFO_SCOPES",
    "GMAIL_SCOPES",
    "CALENDAR_SCOPES",
    "DRIVE_SCOPES",
    "DOCS_SCOPES",
    "YOUTUBE_SCOPES",
    "CONTACTS_SCOPES",
    "ALL_GOOGLE_SCOPES",
    "make_google_oauth",
    "run_google_login",
    "run_google_logout",
    "run_google_status",
]
