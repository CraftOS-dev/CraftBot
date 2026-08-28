"""Google family provider base — shared by gmail/calendar/drive/docs/youtube.

Reuses the battle-tested API client classes from
the per-service clients but replaces their credential
plumbing: clients are bound to ONE injected account credential and
persist refreshed tokens through the core (never to spec.cred_file, which
is single-account and would cross-wire secondaries).

The OAuth spec carries the multi-account fix this whole feature started
from: ``prompt=consent select_account`` forces Google's account chooser,
so "Add account" can actually add a *different* account (space-delimited
prompt values are valid per Google's OAuth docs; ``consent`` keeps
refresh-token issuance for re-auths).
"""

from __future__ import annotations

import time
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ..contracts import OAuthSpec, Operation
from ..helpers import request as http_request
from ._google_common import (
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    GoogleCredential,
    USERINFO_SCOPES,
    make_google_oauth,
)
from ..logger import get_logger

logger = get_logger(__name__)

GOOGLE_FAMILY = "google"

_CRED_FIELDS = {f.name for f in fields(GoogleCredential)}

# The chooser fix. NOT plain "consent" (old behavior: silently re-auths the
# browser-session account) and NOT dropped for Outlook-style reasons — if
# this regresses token issuance somewhere, that's a review conversation.
GOOGLE_AUTH_PARAMS = {
    "access_type": "offline",
    "prompt": "consent select_account",
}


class GoogleClientBinding:
    """Overrides GoogleApiClientMixin's disk plumbing on a API client
    class: credential is injected per account, refresh persists through the
    core. MRO puts this before the mixin:

        class BoundGmailClient(GoogleClientBinding, GmailClient): pass
    """

    _cred: Optional[GoogleCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = GoogleCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> GoogleCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

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
            logger.warning(f"[GOOGLE] token refresh failed: {result['error']}")
            return None
        data = result["result"]
        cred.access_token = data["access_token"]
        cred.token_expiry = time.time() + data.get("expires_in", 3600) - 60
        self._persist(asdict(cred))
        return cred.access_token


class GoogleProviderBase:
    """Subclasses set: id, display_name, scopes, client_cls (bound
    class), and implement operations()/guidance()."""

    id: str = ""
    display_name: str = ""
    scopes: str = ""
    client_cls: type = None  # GoogleClientBinding subclass
    family = GOOGLE_FAMILY

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        email = credential.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=GOOGLE_AUTH_URL,
            token_url=GOOGLE_TOKEN_URL,
            scopes=tuple(f"{self.scopes} {USERINFO_SCOPES}".split()),
            extra_authorize_params=GOOGLE_AUTH_PARAMS,
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
        """Full add-account flow via the package's OAuthFlow (localhost
        callback or host-injected oauth_runner). Returns
        (identity, credential, message). Refuses identity-less results —
        an unaddressable account is worse than a failed login."""
        from ..config import ConfigStore

        oauth = make_google_oauth(self.scopes)
        oauth.extra_auth_params = dict(GOOGLE_AUTH_PARAMS)
        result = await oauth.run()
        if "error" in result and not result.get("access_token"):
            return None, None, f"{self.display_name} OAuth failed: {result['error']}"
        email = (result.get("userinfo") or {}).get("email", "").strip().lower()
        if not email:
            return None, None, (
                f"{self.display_name} sign-in completed but Google returned no "
                f"email address — cannot store an unaddressable account. "
                f"Please try again."
            )
        credential = asdict(
            GoogleCredential(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", ""),
                token_expiry=time.time() + result.get("expires_in", 3600),
                client_id=ConfigStore.get_oauth("GOOGLE_CLIENT_ID"),
                client_secret=ConfigStore.get_oauth("GOOGLE_CLIENT_SECRET"),
                email=email,
            )
        )
        return email, credential, f"{self.display_name} connected as {email}"

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ):
        return None  # calendar/drive/docs/youtube have no inbound events

    # subclasses implement:
    def operations(self) -> List[Operation]:
        raise NotImplementedError

    def guidance(self) -> str:
        raise NotImplementedError
