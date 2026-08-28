"""LinkedIn provider — multi-account wrapper over ``LinkedInClient``.

Follows the Slack binding pattern: the battle-tested API surface of the
API client is reused unchanged, and only its credential plumbing is
overridden — the credential is injected per account by ``build_client``
and never read from ``spec.cred_file`` (single-account; would cross-wire
secondaries).

Unlike Slack, LinkedIn tokens expire (~60 days), so the binding also
reimplements ``refresh_access_token`` with one change: the
refreshed credential is persisted through ``self._persist`` (routed by
the core to the right account entry), mirroring
``GoogleClientBinding.refresh_access_token`` — never written to disk
by the client itself.

Identity is the account's email (lowercased) captured at OAuth time,
falling back to the OpenID ``sub`` claim when LinkedIn returns no email.
Old ``linkedin.json`` shapes carry neither key — ``identity_of`` returns
None and the core stores them under UNIDENTIFIED, upgrading in place
on the next re-auth.

CRITICAL — no account chooser: LinkedIn's OAuth documents NO
prompt/account-chooser parameter (an undocumented ``prompt=login`` was
shipped by the abandoned PR and does nothing). ``has_chooser=False``
declares that explicitly; the conformance suite then requires
GUIDANCE.md to document the add-account browser-session workaround.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from .client import (
    LINKEDIN_OAUTH_BASE,
    LinkedInClient,
    LinkedInCredential,
    LINKEDIN_OAUTH,
)
from ...logger import get_logger
from .._shared import read_guidance
from .operations import build_operations

logger = get_logger(__name__)

_CRED_FIELDS = {f.name for f in fields(LinkedInCredential)}


class LinkedInClientBinding:
    """Overrides LinkedInClient's disk plumbing: credential is injected
    per account, refresh persists through the core. MRO puts this before
    the API client:

        class BoundLinkedInClient(LinkedInClientBinding, LinkedInClient): pass

    Stored credentials carry identity keys (``email``/``sub``) that are not
    LinkedInCredential dataclass fields — they are kept aside and merged
    back into every persisted refresh so identity is never dropped.
    """

    _cred: Optional[LinkedInCredential]
    _extra: Dict[str, Any]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = LinkedInCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._extra = {k: v for k, v in credential.items() if k not in _CRED_FIELDS}
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> LinkedInCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    def refresh_access_token(self) -> Optional[str]:
        """LinkedIn refresh, persisted via the core (never to
        spec.cred_file). Same request/expiry math as the API client:
        LinkedIn access tokens last ~60 days (5184000s), renewed a day
        early."""
        cred = self._load()
        if not all([cred.client_id, cred.client_secret, cred.refresh_token]):
            return None
        result = http_request(
            "POST",
            f"{LINKEDIN_OAUTH_BASE}/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": cred.refresh_token,
                "client_id": cred.client_id,
                "client_secret": cred.client_secret,
            },
            expected=(200,),
        )
        if "error" in result:
            logger.warning(f"[LINKEDIN] token refresh failed: {result['error']}")
            return None
        data = result["result"]
        cred.access_token = data["access_token"]
        cred.token_expiry = time.time() + data.get("expires_in", 5184000) - 86400
        self._persist({**self._extra, **asdict(cred)})
        return cred.access_token


class BoundLinkedInClient(LinkedInClientBinding, LinkedInClient):
    """LinkedInClient with per-account credential binding (see LinkedInClientBinding)."""


class LinkedInProvider:
    id = "linkedin"
    display_name = "LinkedIn"
    # ----- UI metadata -----
    description = "Professional network"
    auth_type = "oauth"
    icon = "linkedin"
    connect_help = [
        "Click 'Sign in with LinkedIn' below",
        "A browser tab will open at linkedin.com/oauth - sign in with your LinkedIn account",
        "Approve the requested permissions (read profile, post on behalf, etc.)",
        "You'll be redirected back to CraftBot once consent completes",
    ]

    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundLinkedInClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Email (lowercased) captured at OAuth time; falls back to the
        OpenID ``sub`` claim when LinkedIn returned no email. The
        ``linkedin.json`` shapes carry neither — None → UNIDENTIFIED,
        upgraded in place on the next re-auth."""
        email = credential.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
        sub = credential.get("sub")
        if isinstance(sub, str) and sub.strip():
            return sub.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=LINKEDIN_OAUTH.auth_url,
            token_url=LINKEDIN_OAUTH.token_url,
            scopes=tuple(LINKEDIN_OAUTH.scopes.split()),
            # LinkedIn's OAuth documents NO prompt/account-chooser param —
            # do NOT add one (the abandoned PR's ``prompt=login`` is
            # fictitious and does nothing). has_chooser=False makes the
            # conformance suite require the GUIDANCE.md workaround: log
            # out of linkedin.com in the browser, then Add account.
            extra_authorize_params={},
            has_chooser=False,
        )

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Out-of-band refresh (listener wake-up etc.); operations normally
        refresh inline via the binding's ``_ensure_token``."""
        holder: Dict[str, Any] = {}
        client = self.build_client(credential, holder.update)
        token = client.refresh_access_token()
        return (holder or None) if token else None

    async def run_login(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """Full add-account flow via the connect flow's OAuthFlow (same
        endpoints/scopes, localhost callback or host-injected oauth_runner).
        A *copy* of the shared flow gets the provider spec's
        ``extra_authorize_params`` applied — for LinkedIn that is ``{}``
        (no chooser param exists; the abandoned PR's ``prompt=login`` was
        fictitious), but routing through ``oauth_spec()`` keeps the spec
        the single source of truth and never mutates the shared handler
        instance.

        Returns (identity, credential, message). Identity is computed by
        ``identity_of`` from the credential (email, falling back to the
        OpenID ``sub`` claim). When LinkedIn returns neither, the
        credential is returned with identity None — the core stores it
        under UNIDENTIFIED and upgrades it in place on the next
        re-auth; a working token beats a failed login here (unlike
        Google/Outlook, where a missing identity implies the userinfo
        call itself failed).
        """
        from ...config import ConfigStore

        oauth = copy.copy(LINKEDIN_OAUTH)
        oauth.extra_auth_params = dict(self.oauth_spec().extra_authorize_params)
        result = await oauth.run()
        if "error" in result and not result.get("access_token"):
            return None, None, f"LinkedIn OAuth failed: {result['error']}"
        info = result.get("userinfo") or {}
        credential = asdict(
            LinkedInCredential(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", ""),
                token_expiry=time.time() + result.get("expires_in", 3600),
                client_id=ConfigStore.get_oauth("LINKEDIN_CLIENT_ID"),
                client_secret=ConfigStore.get_oauth("LINKEDIN_CLIENT_SECRET"),
                linkedin_id=info.get("sub", ""),
                user_id=info.get("sub", ""),
            )
        )
        # Identity keys ride alongside the dataclass fields — the client
        # binding keeps them aside and re-merges them on every refresh.
        if info.get("email"):
            credential["email"] = info["email"]
        if info.get("sub"):
            credential["sub"] = info["sub"]
        identity = self.identity_of(credential)
        if identity:
            name = info.get("name") or identity
            return identity, credential, f"LinkedIn connected as {name} ({identity})"
        return (
            None,
            credential,
            (
                "LinkedIn connected, but no email or member id was returned — "
                "stored without an account identity until the next re-auth."
            ),
        )

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ):
        return None  # LinkedIn is request-response only (no event listening)
