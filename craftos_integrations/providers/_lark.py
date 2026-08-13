"""Lark family provider base — shared by lark / lark_calendar / lark_drive.

Auth-layer bridge port (wave 2) of the legacy Lark integrations. Like the
Google family (``_google.py``), the three Lark services are sibling
provider ids that share one conceptual account — a Lark Custom App
(App ID + App Secret) — so ``family = "lark"`` lets the core sync aliases
across siblings (``core/accounts.py sync_family_aliases``).

Bridge pattern (see stripe/github providers for the wave-1 rationale):
``operations()`` is empty and ``guidance()`` blank — the legacy Lark
action surface stays in place; only the credential plumbing is replaced.

Token-only: a Lark Custom App has no per-user OAuth here (auth is the
app's own tenant_access_token minted from App ID + Secret), so
``oauth_spec()`` raises NotImplementedError and there is no ``run_login``.

Tenant-token refresh — the one disk write the binding must intercept:
the legacy clients cache a ~2h ``tenant_access_token`` in the credential
and refresh it via ``_lark_common.ensure_token``, which writes the
refreshed credential back to the single-account ``lark*.json`` file
(cross-wiring secondaries). The binding's ``_load()`` pre-refreshes the
bound credential through ``persist`` whenever the token is within
``_REFRESH_MARGIN`` seconds of expiry, so every legacy ``ensure_token``
call site (``make_headers`` plus lark_drive's direct upload/download
calls) sees a fresh token, takes its cache-hit branch, and its
``save_credential`` is never reached.
"""

from __future__ import annotations

import time
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ..contracts import OAuthSpec, Operation
from ..integrations._lark_common import LarkCredential, validate_and_mint_token
from ..logger import get_logger
from ._shared import LegacyListenerAdapter

logger = get_logger(__name__)

LARK_FAMILY = "lark"

_CRED_FIELDS = {f.name for f in fields(LarkCredential)}

# The binding refreshes when within this many seconds of expiry. MUST stay
# wider than the legacy ``ensure_token``'s 60s threshold: when the bound
# credential reaches a legacy call site, the legacy freshness check
# ``token_expires_at > now + 60`` must hold, so the legacy save branch
# (which writes the single-account credential file) is never entered.
_REFRESH_MARGIN = 120.0


class LarkClientBinding:
    """Overrides a legacy Lark client's disk plumbing: credential is
    injected per account, tenant-token refresh persists through the core.
    MRO puts this before the legacy client:

        class BoundLarkClient(LarkClientBinding, LarkClient): pass

    Works unchanged for all three legacy clients (lark / lark_calendar /
    lark_drive) because they share ``LarkCredential`` and the same
    ``has_credentials``/``_load``/``_headers`` plumbing shape.
    """

    _cred: Optional[LarkCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = LarkCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> LarkCredential:
        """Bound credential, guaranteed token-fresh (see module docstring:
        pre-refreshing here is what keeps the legacy ``ensure_token`` from
        ever writing the legacy credential file)."""
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        self._refresh_token_if_needed(self._cred)
        return self._cred

    def _refresh_token_if_needed(self, cred: LarkCredential) -> None:
        now = time.time()
        if cred.tenant_access_token and cred.token_expires_at > now + _REFRESH_MARGIN:
            return
        token, expires_at, err = validate_and_mint_token(cred.app_id, cred.app_secret)
        if err:
            raise RuntimeError(f"Lark token refresh failed: {err}")
        cred.tenant_access_token = token or ""
        cred.token_expires_at = expires_at
        # In-memory + core persist ONLY — never the legacy lark*.json file.
        self._persist(asdict(cred))


class LarkProviderBase:
    """Subclasses set: id, display_name, client_cls (bound class).

    All three Lark providers are bridges, so operations()/guidance() are
    concrete (empty) here, unlike the Google base.
    """

    id: str = ""
    display_name: str = ""
    client_cls: type = None  # LarkClientBinding subclass
    family = LARK_FAMILY

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """The Custom App's ``app_id`` (cli_…), lowercased — one Lark app
        = one account across the whole family. None for junk shapes."""
        try:
            app_id = credential.get("app_id")
        except AttributeError:
            return None
        if isinstance(app_id, str) and app_id.strip():
            return app_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError(f"{self.id} is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Out-of-band tenant-token refresh (listener wake-up etc.);
        operations normally refresh inline via the binding's ``_load``.
        Returns the updated credential dict only when a refresh actually
        happened; None when the cached token is still fresh or the app
        credentials no longer mint."""
        holder: Dict[str, Any] = {}
        client = self.build_client(credential, holder.update)
        try:
            client._load()
        except RuntimeError as e:
            logger.warning(f"[LARK] out-of-band refresh failed: {e}")
            return None
        return holder or None

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Same verification every legacy Lark handler's login() runs:
        mint a tenant_access_token from App ID + Secret via
        ``validate_and_mint_token``. Same field keys as the handlers'
        ``fields``: ``app_id`` + ``app_secret`` — identity (app_id) is in
        the fields by construction, but still validated against the API.

        Returns (ok, message, credential); credential is the asdict of
        ``LarkCredential`` with the freshly minted token cached.
        """
        app_id = (credentials.get("app_id") or "").strip()
        app_secret = (credentials.get("app_secret") or "").strip()
        if not app_id:
            return False, "Missing Lark App ID (app_id).", None
        if not app_secret:
            return False, "Missing Lark App Secret (app_secret).", None

        token, expires_at, err = validate_and_mint_token(app_id, app_secret)
        if err:
            return False, err, None

        credential = asdict(
            LarkCredential(
                app_id=app_id,
                app_secret=app_secret,
                tenant_access_token=token or "",
                token_expires_at=expires_at,
            )
        )
        return True, f"{self.display_name} connected: {app_id}", credential

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy Lark actions stay in place

    def guidance(self) -> str:
        return ""  # bridge provider — the legacy action surface has its own docs

    # Whether this sibling's platform has an inbound listen loop — a static
    # property of the platform, not of a client instance (the lark
    # messaging client's lark-oapi WebSocket loop; calendar and drive are
    # request-response only). LarkProvider overrides to True.
    has_listener: bool = False

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Optional[LegacyListenerAdapter]:
        if self.has_listener:
            return LegacyListenerAdapter(client, emit)
        return None
