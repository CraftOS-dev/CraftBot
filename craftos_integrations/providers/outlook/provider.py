"""Outlook provider — Microsoft Graph mail with rotating tokens.

Reuses the battle-tested API surface of ``OutlookClient``
unchanged and overrides only its credential plumbing with a binding mixin
(mirroring ``GoogleClientBinding``): the credential is injected per
account by ``build_client`` and never read from ``spec.cred_file`` (which
is single-account and would cross-wire secondaries).

Unlike Slack, Outlook access tokens expire (~2h) and Microsoft *rotates*
refresh tokens, so the binding reimplements the refresh but
persists through ``self._persist`` — the core routes the updated
credential to the right account entry. The API client's inline
``_ensure_token`` path picks up the overridden ``refresh_access_token``
via MRO, so mid-operation refreshes also persist through the core.

One account = one Microsoft account (email/UPN). OAuth parameters are
referenced from ``OAuthFlow`` so the provider spec cannot
drift from it — except for the added account-chooser prompt below.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from .client import (
    MS_TOKEN_URL,
    OUTLOOK_SCOPES,
    OutlookClient,
    OutlookCredential,
    OUTLOOK_OAUTH,
)
from ...logger import get_logger
from .._shared import read_guidance
from .listener import OutlookListener
from .operations import build_operations

logger = get_logger(__name__)

_CRED_FIELDS = {f.name for f in fields(OutlookCredential)}

# The chooser fix this port exists for: without ``prompt=select_account``,
# "Add account" silently re-auths whichever Microsoft account the browser
# is already signed into — the abandoned PR shipped without it and could
# never actually add a *second* Outlook account. ``response_mode=query``
# is carried from the connect flow. If ``select_account`` regresses
# token issuance for some tenant, that's a review conversation, never a
# silent drop.
OUTLOOK_AUTH_PARAMS = {
    "response_mode": "query",
    "prompt": "select_account",
}


class OutlookClientBinding:
    """Overrides OutlookClient's disk plumbing: credential is injected per
    account, refresh persists through the core. MRO puts this before the
    API client:

        class BoundOutlookClient(OutlookClientBinding, OutlookClient): pass
    """

    _cred: Optional[OutlookCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = OutlookCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> OutlookCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    def refresh_access_token(self) -> Optional[str]:
        """Outlook refresh: PKCE public-client token
        request (no client_secret), but the refreshed credential goes to
        ``self._persist`` instead of ``spec.cred_file``."""
        cred = self._load()
        if not all([cred.client_id, cred.refresh_token]):
            return None
        result = http_request(
            "POST",
            MS_TOKEN_URL,
            data={
                "client_id": cred.client_id,
                "refresh_token": cred.refresh_token,
                "grant_type": "refresh_token",
                "scope": OUTLOOK_SCOPES,
            },
            expected=(200,),
        )
        if "error" in result:
            logger.warning(f"[OUTLOOK] token refresh failed: {result['error']}")
            return None
        data = result["result"]
        cred.access_token = data["access_token"]
        # Microsoft rotates refresh tokens: persist the new one when
        # issued, keep the old one when the response omits it.
        cred.refresh_token = data.get("refresh_token", cred.refresh_token)
        cred.token_expiry = time.time() + data.get("expires_in", 3600) - 60
        self._persist(asdict(cred))
        return cred.access_token


class BoundOutlookClient(OutlookClientBinding, OutlookClient):
    """OutlookClient with per-account credential binding (see OutlookClientBinding)."""


class OutlookProvider:
    id = "outlook"
    display_name = "Outlook"
    # ----- UI metadata -----
    description = "Microsoft email and calendar"
    auth_type = "oauth"
    icon = "Inbox"

    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundOutlookClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """The account's email/UPN, lowercased. The connect flow stores
        ``mail`` or ``userPrincipalName`` under ``email``; None for
        credentials saved before that capture."""
        email = credential.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=OUTLOOK_OAUTH.auth_url,
            token_url=OUTLOOK_OAUTH.token_url,
            scopes=tuple(OUTLOOK_SCOPES.split()),
            # prompt=select_account is load-bearing (see OUTLOOK_AUTH_PARAMS).
            extra_authorize_params=OUTLOOK_AUTH_PARAMS,
            has_chooser=True,
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
        refresh inline via the binding."""
        holder: Dict[str, Any] = {}
        client = self.build_client(credential, holder.update)
        token = client.refresh_access_token()
        return holder or None if token else None

    async def run_login(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """Full add-account flow via the connect flow's OAuthFlow (same
        PKCE public-client dance, localhost callback or host-injected
        oauth_runner), with the chooser params applied: a *copy* of the
        shared flow gets ``prompt=select_account`` (+ the carried
        ``response_mode=query``) so "Add account" can add a *different*
        Microsoft account — the shared handler instance is never mutated.

        Returns (identity, credential, message). Google-style refusal on a
        missing identity — documented judgment call: Graph's ``/me`` with
        the ``User.Read`` scope always returns a ``userPrincipalName`` when
        the fetch succeeds, so an empty result means the userinfo call
        itself failed; re-prompting beats storing an unaddressable account.
        """
        from ...config import ConfigStore

        oauth = copy.copy(OUTLOOK_OAUTH)
        oauth.extra_auth_params = dict(self.oauth_spec().extra_authorize_params)
        result = await oauth.run()
        if "error" in result and not result.get("access_token"):
            return None, None, f"Outlook OAuth failed: {result['error']}"
        info = result.get("userinfo") or {}
        email = (info.get("mail") or info.get("userPrincipalName") or "").strip().lower()
        if not email:
            return None, None, (
                "Outlook sign-in completed but Microsoft Graph returned no "
                "email/UPN — cannot store an unaddressable account. "
                "Please try again."
            )
        credential = asdict(
            OutlookCredential(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", ""),
                token_expiry=time.time() + result.get("expires_in", 3600),
                client_id=ConfigStore.get_oauth("OUTLOOK_CLIENT_ID"),
                email=email,
            )
        )
        return email, credential, f"Outlook connected as {email}"

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> OutlookListener:
        """Mailbox poll listener (see listener.py)."""
        return OutlookListener(client, cursor, emit)
