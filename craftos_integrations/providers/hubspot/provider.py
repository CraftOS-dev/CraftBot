"""HubSpot provider — first non-Google provider with rotating tokens.

Follows the Slack non-Google binding pattern (reuse the battle-tested
legacy ``HubSpotClient`` API surface, override only its credential
plumbing) plus the Google refresh pattern: HubSpot OAuth access tokens
expire (~30 min), so the binding reimplements the legacy client's
``_refresh_access_token`` but persists the rotated credential through
the core via ``self._persist(...)`` — never to ``spec.cred_file``,
which is single-account and would cross-wire secondaries.

The legacy ``_get_valid_access_token`` (lazy expiry check on every
request) is inherited unchanged: it calls ``self._load()`` and
``self._refresh_access_token()``, both of which the binding overrides,
so per-request refresh flows through the account plumbing automatically.
Private App tokens (``auth_kind == "token"``) never expire and skip the
refresh path entirely, exactly as in the legacy client.

One account = one HubSpot **hub** (portal); identity is the hub id from
the credential (stringified, lowercased). OAuth parameters are
referenced from the legacy handler's ``OAuthFlow`` so the provider spec can
never drift from it.

multi-account plan decision — dropped legacy quirk: the old handler's ``logout``
also called ``manager.stop_platform(...)``, so the LAST logout stopped
the whole integration platform. That special case is deliberately NOT
ported; the last disconnect is now a plain disconnect, uniform across
providers (the core handles disconnect centrally).
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...config import ConfigStore
from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from ...integrations.hubspot import (
    HUBSPOT_API,
    HUBSPOT_SCOPES,
    HubSpotClient,
    HubSpotCredential,
    HubSpotHandler,
)
from ...logger import get_logger
from .._shared import read_guidance
from .operations import build_operations

logger = get_logger(__name__)

_CRED_FIELDS = {f.name for f in fields(HubSpotCredential)}


class HubSpotClientBinding:
    """Overrides HubSpotClient's disk plumbing: credential is injected per
    account, token refresh persists through the core. MRO puts this before
    the legacy client:

        class BoundHubSpotClient(HubSpotClientBinding, HubSpotClient): pass
    """

    _cred: Optional[HubSpotCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = HubSpotCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> HubSpotCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    def _refresh_access_token(self) -> Optional[str]:
        """Swap the refresh_token for a fresh access_token + expiry.

        Legacy logic verbatim (same endpoint, same params, same rotate-or-
        keep refresh_token handling, same 60s early-refresh margin) except
        for persistence: the mutated credential goes through
        ``self._persist(...)`` so the core routes it to the right account
        entry, instead of ``save_credential(spec.cred_file, ...)``.

        Returns the new access_token, or ``None`` on failure (the inherited
        ``_get_valid_access_token`` then falls back to the stale token,
        which produces a clean 401 from HubSpot rather than a crash).
        """
        cred = self._load()
        if cred.auth_kind != "oauth" or not cred.refresh_token:
            return None

        client_id = ConfigStore.get_oauth("HUBSPOT_SHARED_CLIENT_ID")
        client_secret = ConfigStore.get_oauth("HUBSPOT_SHARED_CLIENT_SECRET")
        if not client_id or not client_secret:
            logger.warning(
                "[HUBSPOT] Cannot refresh token: HUBSPOT_SHARED_CLIENT_ID/SECRET "
                "not configured. Reconnect the account to continue."
            )
            return None

        result = http_request(
            "POST",
            f"{HUBSPOT_API}/oauth/v1/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": cred.refresh_token,
            },
            expected=(200,),
        )
        if "error" in result:
            logger.warning(
                f"[HUBSPOT] Token refresh failed: {result.get('error')}. "
                "Reconnect the account to continue."
            )
            return None

        data = result.get("result") or {}
        new_token = data.get("access_token")
        if not new_token:
            logger.warning("[HUBSPOT] Token refresh returned no access_token.")
            return None

        cred.access_token = new_token
        # HubSpot sometimes rotates the refresh_token, sometimes doesn't —
        # keep the old one if a new one isn't returned.
        cred.refresh_token = data.get("refresh_token") or cred.refresh_token
        # Refresh 60s before actual expiry to avoid races with in-flight calls.
        cred.token_expiry = time.time() + data.get("expires_in", 1800) - 60
        self._persist(asdict(cred))
        logger.info("[HUBSPOT] Access token refreshed.")
        return new_token


class BoundHubSpotClient(HubSpotClientBinding, HubSpotClient):
    """HubSpotClient with per-account credential binding (see HubSpotClientBinding)."""


class HubSpotProvider:
    id = "hubspot"
    display_name = "HubSpot"
    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundHubSpotClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Hub (portal) id as a lowercase string. None for credentials saved
        before the hub id was captured (pre-multi-account Private App token logins)."""
        hub_id = credential.get("hub_id")
        if hub_id is None or isinstance(hub_id, (dict, list)):
            return None
        text = str(hub_id).strip()
        return text.lower() if text else None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=HubSpotHandler.oauth.auth_url,
            token_url=HubSpotHandler.oauth.token_url,
            scopes=tuple(s for s in HUBSPOT_SCOPES.split() if s),
            # HubSpot's authorize page always shows its own account/hub
            # chooser (pick which portal to grant access to) — no extra
            # params needed to add a *different* hub.
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
        refresh inline via the binding's ``_get_valid_access_token``.
        Returns None for non-expiring Private App tokens."""
        holder: Dict[str, Any] = {}
        client = self.build_client(credential, holder.update)
        token = client._refresh_access_token()
        return holder or None if token else None

    async def run_login(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """Full add-account flow via the legacy handler's OAuthFlow — the
        machinery behind the legacy ``invite()`` subcommand, including the
        access-token introspection call that captures hub_id/hub_domain/
        user email (HubSpot has no OAuthFlow userinfo endpoint). The
        Private-App-token ``login()`` path is host UI territory and is
        not ported here.

        A *copy* of the shared flow gets the provider spec's
        ``extra_authorize_params`` applied (empty — HubSpot's authorize
        page always shows its own hub chooser); the shared handler
        instance is never mutated.

        Returns (identity, credential, message). Identity is computed by
        ``identity_of`` (hub id). One deliberate deviation from the
        legacy ``invite()``: a failed introspection no longer fails the
        whole login — the token itself is valid, so the credential is
        returned with identity None and the core stores it under
        LEGACY_IDENTITY, upgrading in place on the next re-auth.
        """
        oauth = copy.copy(HubSpotHandler.oauth)
        oauth.extra_auth_params = dict(self.oauth_spec().extra_authorize_params)
        result = await oauth.run()
        if "error" in result and not result.get("access_token"):
            return None, None, f"HubSpot OAuth failed: {result['error']}"

        access_token = result.get("access_token", "")
        expires_in = result.get("expires_in", 0) or 0

        # Hub metadata from the introspection endpoint (same call as the
        # legacy invite()).
        info = http_request(
            "GET",
            f"{HUBSPOT_API}/oauth/v1/access-tokens/{access_token}",
            expected=(200,),
        )
        if "error" in info:
            logger.warning(
                f"[HUBSPOT] token introspection failed: {info['error']} — "
                "storing the credential without a hub id."
            )
            meta: Dict[str, Any] = {}
        else:
            meta = info.get("result") or {}

        credential = asdict(
            HubSpotCredential(
                access_token=access_token,
                refresh_token=result.get("refresh_token", ""),
                token_expiry=time.time() + expires_in if expires_in else 0.0,
                hub_id=str(meta.get("hub_id", "")),
                hub_domain=meta.get("hub_domain", ""),
                user_email=meta.get("user", ""),
                auth_kind="oauth",
            )
        )
        identity = self.identity_of(credential)
        label = meta.get("hub_domain") or meta.get("hub_id") or "HubSpot"
        message = f"HubSpot connected via OAuth: {label}"
        if not identity:
            message += (
                " (no hub id captured — stored as the legacy account until "
                "the next re-auth)"
            )
        return identity, credential, message

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
        return None  # HubSpot is request-response only (no event listening)
