"""Stripe provider — auth-layer bridge over the legacy ``StripeClient``.

Bridge port: the v2 provider handles accounts/credentials only —
``operations()`` returns [] and ``guidance()`` returns "" because the
legacy Stripe action surface stays in place; account routing happens
centrally. The binding mixin below replaces the legacy client's disk
credential plumbing with the injected per-account credential, exactly
like ``SlackClientBinding``.

Stripe is token-only (a Restricted/Secret API key per merchant account —
no OAuth; see the legacy module's rationale for skipping Stripe Connect),
so ``oauth_spec()`` raises NotImplementedError and there is no
``run_login``. Keys never expire → ``refresh()`` returns None.

One account = one Stripe merchant account; identity is the ``acct_...``
id captured from ``GET /v1/account`` at verify time (lowercased).
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from ...integrations.stripe import (
    STRIPE_API,
    STRIPE_API_VERSION,
    StripeClient,
    StripeCredential,
    _classify_key,
)
from .._shared import LegacyListenerAdapter

_CRED_FIELDS = {f.name for f in fields(StripeCredential)}


class StripeClientBinding:
    """Overrides StripeClient's disk plumbing: credential is injected per
    account. MRO puts this before the legacy client:

        class BoundStripeClient(StripeClientBinding, StripeClient): pass

    No token refresh — Stripe API keys are non-expiring, so ``_persist``
    is never called (kept so the build_client contract is uniform across
    providers).
    """

    _cred: Optional[StripeCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = StripeCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> StripeCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundStripeClient(StripeClientBinding, StripeClient):
    """StripeClient with per-account credential binding (see StripeClientBinding)."""


class StripeProvider:
    id = "stripe"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "Stripe"
    client_cls = BoundStripeClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Stripe account id (``acct_...``), lowercased. None for
        restricted-key credentials whose scope couldn't read /v1/account
        (stored without an account id) and for pre-bridge junk shapes."""
        try:
            account_id = credential.get("account_id")
        except AttributeError:
            return None
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        # Deliberate: no Stripe Connect OAuth (see the legacy module's
        # platform-risk rationale). Each user brings their own API key.
        raise NotImplementedError("stripe is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # Stripe API keys are non-expiring

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Same verification the legacy StripeHandler.login() runs: prefix
        check + ``GET /v1/account`` with the key (falling back to
        ``GET /v1/balance`` for restricted keys that can't read the
        account). Expects the legacy handler's field key: ``api_key``.

        Returns (ok, message, credential). The credential is the asdict
        of ``StripeCredential`` — which carries ``account_id`` (the
        ``acct_...`` id from /v1/account) so ``identity_of`` works.
        """
        token = (credentials.get("api_key") or "").strip()
        if not token:
            return False, "Missing Stripe API key (api_key).", None
        if token.startswith("pk_"):
            return (
                False,
                "That's a publishable key (pk_…). Publishable keys are for "
                "client-side code and won't authenticate server-side requests. "
                "Paste a secret (sk_…) or restricted (rk_…) key instead.",
                None,
            )
        if not (token.startswith("sk_") or token.startswith("rk_")):
            return (
                False,
                "Invalid Stripe key. Expected sk_live_…, sk_test_…, rk_live_…, "
                "or rk_test_….",
                None,
            )

        livemode, kind = _classify_key(token)
        headers = {
            "Authorization": f"Bearer {token}",
            "Stripe-Version": STRIPE_API_VERSION,
        }
        account_id = ""
        business_name = ""

        acct = http_request(
            "GET",
            f"{STRIPE_API}/account",
            headers=headers,
            expected=(200,),
        )
        if "error" not in acct:
            data = acct.get("result") or {}
            account_id = data.get("id") or ""
            business_name = (
                data.get("business_profile", {}).get("name")
                or data.get("settings", {}).get("dashboard", {}).get("display_name")
                or data.get("email")
                or ""
            )
        else:
            # Restricted keys may lack the 'account read' scope; every
            # authenticated key can reach /v1/balance.
            balance = http_request(
                "GET",
                f"{STRIPE_API}/balance",
                headers=headers,
                expected=(200,),
            )
            if "error" in balance:
                return False, f"Stripe auth failed: {balance['error']}", None
            # /balance succeeded — key is valid but has no account_id
            # (identity_of returns None; core stores as legacy account).

        credential = asdict(
            StripeCredential(
                api_key=token,
                account_id=account_id,
                business_name=business_name,
                livemode=livemode,
                key_kind=kind,
            )
        )
        label = business_name or account_id or "Stripe account"
        mode = "live mode" if livemode else "TEST MODE"
        kind_label = "restricted key" if kind == "restricted" else "secret key"
        return True, f"Stripe connected: {label} ({mode}, {kind_label})", credential

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy Stripe actions stay in place

    def guidance(self) -> str:
        return ""  # bridge provider — the legacy action surface has its own docs

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Optional[LegacyListenerAdapter]:
        """Stripe's legacy client is request-response only
        (``supports_listening`` is the BasePlatformClient default False),
        so there is nothing to listen to — checked dynamically so a future
        legacy listen loop gets bridged automatically."""
        if getattr(client, "supports_listening", False):
            return LegacyListenerAdapter(client, emit)
        return None
