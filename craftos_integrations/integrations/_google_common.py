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
from typing import Any, Dict, List, Optional, Tuple

from .. import (
    IntegrationSpec,
    OAuthFlow,
    load_credential,
    save_credential,
)
from .. import accounts as acc
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
        # select_account forces Google's account chooser every time. Without
        # it, the OAuth popup silently reuses whichever Google account is
        # already signed into the system browser — so "add account" would
        # just re-authenticate the same primary account and overwrite it
        # instead of letting the user pick a second one.
        extra_auth_params={"access_type": "offline", "prompt": "consent select_account"},
    )


# ════════════════════════════════════════════════════════════════════════
# Multi-account support — thin Google-flavored wrappers around the generic
# ``accounts.py`` layer (shared with every other multi-account integration).
# The bare ``spec.cred_file`` (e.g. ``gmail.json``) always holds the
# *primary* account — untouched, so existing single-account users need no
# migration. Additional accounts get their own ``<stem>__<email>.json``.
# ════════════════════════════════════════════════════════════════════════


def _cred_stem(spec: IntegrationSpec) -> str:
    cred_file = spec.cred_file
    return cred_file[:-5] if cred_file.endswith(".json") else cred_file


def _nice_name(spec: IntegrationSpec) -> str:
    return spec.name.replace("_", " ").title()


def _identity(cred: "GoogleCredential") -> str:
    return cred.email


# Aliases are shared across the whole Google family under one namespace —
# the same Google account (email) is frequently connected to several of
# Gmail/Calendar/Drive/Docs/YouTube, and a nickname set once ("work",
# "personal") should carry over to all of them rather than needing to be
# re-typed per service. Credential FILES stay separate per service (each
# is its own OAuth grant/scope); only the alias *lookup key* is shared.
_ALIAS_NAMESPACE = "google"
_LEGACY_ALIAS_PLATFORM_IDS = (
    "gmail",
    "google_calendar",
    "google_drive",
    "google_docs",
    "google_youtube",
)


def _migrate_legacy_alias(identity: str, current: Optional[str]) -> Optional[str]:
    """One-time-per-service, idempotent migration: aliases used to be keyed
    per Google service (``gmail:<email>``, ``google_calendar:<email>``, ...).
    Sweeps every legacy key for ``identity`` and removes it; the first
    legacy alias found fills the shared namespace only if it isn't already
    set (``current`` is the alias already read under the shared namespace,
    so a user-chosen shared alias is never overwritten by a stale legacy
    one). Called on every listing, but becomes a cheap no-op once no
    legacy keys remain for this identity.
    """
    result = current
    for legacy_platform in _LEGACY_ALIAS_PLATFORM_IDS:
        legacy_alias = acc.get_alias(legacy_platform, identity)
        if legacy_alias:
            if result is None:
                acc.set_alias(_ALIAS_NAMESPACE, identity, legacy_alias)
                result = legacy_alias
            acc.remove_alias(legacy_platform, identity)
    return result


def _list_accounts_migrated(spec: IntegrationSpec):
    """``accounts.list_accounts`` under the shared namespace, sweeping any
    still-legacy-keyed alias for each identity found along the way."""
    accounts = acc.list_accounts(_ALIAS_NAMESPACE, _cred_stem(spec), GoogleCredential, _identity)
    for a in accounts:
        a.alias = _migrate_legacy_alias(a.identity, a.alias)
    return accounts


def list_google_accounts(spec: IntegrationSpec) -> List[Tuple[str, str]]:
    """``[(email, filename), ...]`` for every connected account, primary first."""
    return [(a.identity, a.filename) for a in _list_accounts_migrated(spec)]


def resolve_account(
    spec: IntegrationSpec, account: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve an agent-supplied account hint (email, alias, or unique
    substring of either) to a credential filename. See ``accounts.resolve_account``."""
    _list_accounts_migrated(spec)  # ensure aliases are migrated before resolving by alias
    return acc.resolve_account(
        _ALIAS_NAMESPACE, _cred_stem(spec), GoogleCredential, _identity, account, _nice_name(spec)
    )


def run_google_list_accounts(spec: IntegrationSpec) -> List[Dict[str, Any]]:
    """Structured account list for ``IntegrationHandler.list_accounts()``."""
    return acc.accounts_to_dicts(_list_accounts_migrated(spec))


async def run_google_set_primary(
    spec: IntegrationSpec, display_name: str, account_id: str
) -> Tuple[bool, str]:
    fname, err = resolve_account(spec, account_id)
    if err:
        return False, err
    if not acc.promote_to_primary(_cred_stem(spec), fname):
        return False, f"{account_id} is already the primary {display_name} account."
    return True, f"{account_id} is now the primary {display_name} account."


def run_google_set_alias(spec: IntegrationSpec, account_id: str, alias: str) -> Tuple[bool, str]:
    fname, err = resolve_account(spec, account_id)
    if err:
        return False, err
    cred = load_credential(fname, GoogleCredential)
    if not cred:
        return False, f"Could not load credential for {account_id}."
    acc.set_alias(_ALIAS_NAMESPACE, cred.email, alias)
    return True, f"Alias {'set' if alias.strip() else 'cleared'} for {cred.email}."


# ════════════════════════════════════════════════════════════════════════
# Shared login / logout / status helpers — called by per-service handlers
# ════════════════════════════════════════════════════════════════════════


async def run_google_login(
    spec: IntegrationSpec,
    oauth: OAuthFlow,
    display_name: str,
) -> Tuple[bool, str]:
    """Run the OAuth flow and persist the credential.

    Re-authing an already-connected email overwrites that account's file.
    A brand new email fills the primary file if it's empty, otherwise gets
    its own secondary file — so "Connect" on an already-connected service
    is just "add another account".
    """
    result = await oauth.run()
    if "error" in result and not result.get("access_token"):
        return False, f"{display_name} OAuth failed: {result['error']}"

    info = result.get("userinfo", {})
    email = info.get("email", "")
    cred = GoogleCredential(
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token", ""),
        token_expiry=time.time() + result.get("expires_in", 3600),
        client_id=ConfigStore.get_oauth("GOOGLE_CLIENT_ID"),
        client_secret=ConfigStore.get_oauth("GOOGLE_CLIENT_SECRET"),
        email=email,
    )

    target_file = acc.resolve_save_target(_cred_stem(spec), GoogleCredential, _identity, email)
    save_credential(target_file, cred)
    return True, f"{display_name} connected as {email}"


async def run_google_logout(
    spec: IntegrationSpec,
    display_name: str,
    account: Optional[str] = None,
) -> Tuple[bool, str]:
    """Remove one account (``account`` given) or every account (``None`` —
    current "logout everything" semantics). Server-side invalidation isn't
    necessary for Google — the refresh token expires naturally and access
    tokens are short-lived.

    Removing the primary account while secondaries remain promotes one of
    them into the bare file, so the integration stays connected rather than
    silently dropping to "not connected" while a secondary file still exists.
    """
    accounts = list_google_accounts(spec)
    if not accounts:
        return False, f"No {display_name} credentials found."

    if not account:
        acc.remove_all_accounts(_cred_stem(spec))
        return True, f"Removed {display_name} credential."

    fname, err = resolve_account(spec, account)
    if err:
        return False, err

    acc.remove_account(_cred_stem(spec), fname)
    return True, f"Removed {display_name} account."


async def run_google_status(
    spec: IntegrationSpec,
    display_name: str,
) -> Tuple[bool, str]:
    """Connected/not-connected + one ``- email (email)`` line per connected
    account (parsed by ``service.parse_status_accounts``)."""
    accounts = list_google_accounts(spec)
    if not accounts:
        return True, f"{display_name}: Not connected"
    lines = [f"{display_name}: Connected"]
    lines.extend(f"  - {email} ({email})" for email, _ in accounts)
    return True, "\n".join(lines)


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
    # Which connected account this instance talks to (None = primary). Set
    # externally by registry.get_client(platform_id, account) — see base.py.
    _account: Optional[str]
    _cred_file: Optional[str] = None  # resolved filename, cached alongside _cred

    def has_credentials(self) -> bool:
        """True if *any* account is connected for this service.

        Deliberately does not resolve ``self._account`` here: an ambiguous or
        not-found account hint shouldn't be reported as "not connected" (which
        would hide the precise, self-correcting error). Callers that pass a
        specific ``account`` get that detail from ``_load()`` when the actual
        method call runs and raises.
        """
        return bool(list_google_accounts(self.spec))

    def _load(self) -> GoogleCredential:
        if self._cred is None:
            fname, err = resolve_account(self.spec, getattr(self, "_account", None))
            if err:
                raise RuntimeError(err)
            self._cred_file = fname
            self._cred = load_credential(fname, GoogleCredential)
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
        save_credential(self._cred_file or self.spec.cred_file, cred)
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
    "run_google_list_accounts",
    "run_google_set_primary",
    "run_google_set_alias",
    "list_google_accounts",
    "resolve_account",
]
