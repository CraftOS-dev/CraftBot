# -*- coding: utf-8 -*-
"""Stripe integration — handler (Restricted/Secret API key) + client.

Stripe's auth model is a Bearer key tied to the merchant's own Stripe account.
We deliberately do NOT ship a shared OAuth (Stripe Connect) path: Connect would
pool every CraftBot user under one platform whose suspension risk and KYC
obligations would cascade across the install base. Each user brings their own
key — preferably a Restricted Key (``rk_live_*``) scoped to the resources the
agent needs.

See INTEGRATION.md for the form-encoding rules, search query syntax, ID
prefixes, expand support, and idempotency semantics.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationSpec,
    has_credential,
    load_credential,
    register_client,
)
from ...helpers import Result, arequest
from ...logger import get_logger

logger = get_logger(__name__)

STRIPE_API = "https://api.stripe.com/v1"
STRIPE_FILES_API = "https://files.stripe.com/v1"

# Pinned API version — Stripe rolls schemas forward continuously; pinning
# protects the agent from silently breaking field shapes when Stripe ships a
# new release. Bump this deliberately, with a regression pass, not casually.
STRIPE_API_VERSION = "2024-12-18.acacia"


# ------------------------------------------------------------------
# Credential + config
# ------------------------------------------------------------------


@dataclass
class StripeCredential:
    api_key: str = ""
    account_id: str = ""  # acct_... from /v1/account
    business_name: str = ""  # display label for /stripe status
    livemode: bool = False  # True if api_key.startswith("sk_live_" | "rk_live_")
    key_kind: str = "secret"  # "secret" | "restricted"


@dataclass
class StripeConfig:
    """Post-connect runtime knobs."""

    default_currency: str = "usd"
    default_expand: List[str] = field(default_factory=list)
    require_idempotency_key: bool = True


STRIPE = IntegrationSpec(
    name="stripe",
    cred_class=StripeCredential,
    cred_file="stripe.json",
    platform_id="stripe",
)


# ------------------------------------------------------------------
# Handler — auth flow (token only)
# ------------------------------------------------------------------


def _classify_key(token: str) -> Tuple[bool, str]:
    """Return ``(livemode, key_kind)`` for a Stripe key.

    ``key_kind`` is ``"secret"`` for ``sk_*`` and ``"restricted"`` for ``rk_*``.
    Stripe also issues publishable keys (``pk_*``) — those are client-side only
    and rejected by the handler before we get here.
    """
    if token.startswith("sk_live_") or token.startswith("rk_live_"):
        livemode = True
    else:
        livemode = False
    kind = "restricted" if token.startswith("rk_") else "secret"
    return livemode, kind


def _flatten_params(
    payload: Mapping[str, Any],
    *,
    prefix: str = "",
) -> Dict[str, str]:
    """Flatten nested dicts/lists into Stripe's bracket notation.

    None values are dropped (caller passes ``None`` to mean "omit this field").
    Booleans become lowercase strings (Stripe expects ``true``/``false``).
    Everything else is coerced to str.
    """
    out: Dict[str, str] = {}

    def _emit(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, Mapping):
            for sub_k, sub_v in value.items():
                _emit(f"{key}[{sub_k}]", sub_v)
            return
        if isinstance(value, (list, tuple)):
            # Use indexed-bracket notation for ALL list items (primitive or
            # nested). Stripe accepts both ``key[]=v1&key[]=v2`` and
            # ``key[0]=v1&key[1]=v2``, but we have to use indexed because
            # httpx's data= dict can't carry repeated keys.
            for i, item in enumerate(value):
                _emit(f"{key}[{i}]", item)
            return
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
            return
        out[key] = str(value)

    for k, v in payload.items():
        if prefix:
            _emit(f"{prefix}[{k}]", v)
        else:
            _emit(k, v)
    return out


def _form_expand(out: Dict[str, str], expand: Optional[Iterable[str]]) -> None:
    """Append expand[]=… entries to a flat form dict."""
    if not expand:
        return
    # Stripe accepts multiple expand[]= entries; httpx urlencode collapses dup
    # keys into a list only when the value is a list. So we ship the multi-value
    # case as a list and let httpx re-emit.
    items = [s for s in expand if s]
    if not items:
        return
    # Because out is a flat str->str dict and expand[] uses bracket-list syntax,
    # we attach via the special key shape with index suffixes — Stripe accepts
    # expand[0]=…&expand[1]=… interchangeably with expand[]=….
    for i, name in enumerate(items):
        out[f"expand[{i}]"] = name


# ------------------------------------------------------------------
# Client — runtime: REST against api.stripe.com
# ------------------------------------------------------------------


@register_client
class StripeClient(BasePlatformClient):
    spec = STRIPE
    PLATFORM_ID = STRIPE.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[StripeCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> StripeCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, StripeCredential)
        if self._cred is None:
            raise RuntimeError("No Stripe credentials. Use /stripe login first.")
        return self._cred

    def _load_config(self) -> StripeConfig:
        # Fresh per-call so config edits take effect without a restart.
        from ... import load_config

        return load_config("stripe_config.json", StripeConfig) or StripeConfig()

    def _headers(
        self,
        *,
        idempotency_key: Optional[str] = None,
        connect_account: Optional[str] = None,
    ) -> Dict[str, str]:
        cred = self._load()
        h: Dict[str, str] = {
            "Authorization": f"Bearer {cred.api_key}",
            "Stripe-Version": STRIPE_API_VERSION,
        }
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        if connect_account:
            # If the user happens to have a Connect setup, this lets them
            # impersonate a connected account on a per-call basis.
            h["Stripe-Account"] = connect_account
        return h

    def _maybe_idempotency_key(
        self, *, mutation: bool, explicit: Optional[str]
    ) -> Optional[str]:
        if explicit:
            return explicit
        if not mutation:
            return None
        cfg = self._load_config()
        if cfg.require_idempotency_key:
            return str(uuid.uuid4())
        return None

    def _default_expand(self) -> List[str]:
        return list(self._load_config().default_expand or [])

    def _default_currency(self) -> str:
        return (self._load_config().default_currency or "usd").lower()

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        # Stripe isn't a messaging platform. We expose this so the facade
        # send_message() returns a deterministic error rather than crashing.
        return {
            "error": "Stripe is not a messaging integration. Use the action surface "
            "(create_stripe_payment_intent, send_stripe_invoice, etc.) instead."
        }

    # ===============================================================
    # Generic REST primitives
    # ===============================================================

    async def _get(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        expand: Optional[Iterable[str]] = None,
        connect_account: Optional[str] = None,
        base: str = STRIPE_API,
    ) -> Result:
        flat = _flatten_params(params or {})
        # Merge default expand[] with any caller-supplied ones.
        merged_expand: List[str] = []
        merged_expand.extend(self._default_expand())
        if expand:
            merged_expand.extend(expand)
        _form_expand(flat, merged_expand)
        return await arequest(
            "GET",
            f"{base}{path}",
            headers=self._headers(connect_account=connect_account),
            params=flat or None,
            expected=(200,),
        )

    async def _post(
        self,
        path: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        expand: Optional[Iterable[str]] = None,
        idempotency_key: Optional[str] = None,
        connect_account: Optional[str] = None,
        mutation: bool = True,
        base: str = STRIPE_API,
        expected: Iterable[int] = (200,),
    ) -> Result:
        flat = _flatten_params(payload or {})
        merged_expand: List[str] = []
        merged_expand.extend(self._default_expand())
        if expand:
            merged_expand.extend(expand)
        _form_expand(flat, merged_expand)
        ikey = self._maybe_idempotency_key(mutation=mutation, explicit=idempotency_key)
        return await arequest(
            "POST",
            f"{base}{path}",
            headers=self._headers(
                idempotency_key=ikey, connect_account=connect_account
            ),
            data=flat or None,
            expected=expected,
        )

    async def _delete(
        self,
        path: str,
        *,
        idempotency_key: Optional[str] = None,
        connect_account: Optional[str] = None,
        base: str = STRIPE_API,
    ) -> Result:
        ikey = self._maybe_idempotency_key(mutation=True, explicit=idempotency_key)
        return await arequest(
            "DELETE",
            f"{base}{path}",
            headers=self._headers(
                idempotency_key=ikey, connect_account=connect_account
            ),
            expected=(200,),
        )

    @staticmethod
    def _list_params(
        *,
        limit: Optional[int],
        starting_after: Optional[str],
        ending_before: Optional[str],
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = min(max(int(limit), 1), 100)
        if starting_after:
            params["starting_after"] = starting_after
        if ending_before:
            params["ending_before"] = ending_before
        if extra:
            for k, v in extra.items():
                if v is not None:
                    params[k] = v
        return params

    # ===============================================================
    # Account (read-only)
    # ===============================================================

    async def get_account(self) -> Result:
        return await self._get("/account")

    # ===============================================================
    # Customers
    # ===============================================================

    async def list_customers(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        email: Optional[str] = None,
        created_gte: Optional[int] = None,
        created_lte: Optional[int] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra: Dict[str, Any] = {"email": email}
        if created_gte is not None or created_lte is not None:
            created: Dict[str, Any] = {}
            if created_gte is not None:
                created["gte"] = created_gte
            if created_lte is not None:
                created["lte"] = created_lte
            extra["created"] = created
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/customers", params=params, expand=expand)

    async def get_customer(
        self, customer_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/customers/{customer_id}", expand=expand)

    async def create_customer(
        self,
        *,
        email: Optional[str] = None,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        description: Optional[str] = None,
        address: Optional[Dict[str, Any]] = None,
        shipping: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        payment_method: Optional[str] = None,
        invoice_settings: Optional[Dict[str, Any]] = None,
        tax_exempt: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {
            "email": email,
            "name": name,
            "phone": phone,
            "description": description,
            "address": address,
            "shipping": shipping,
            "metadata": metadata,
            "payment_method": payment_method,
            "invoice_settings": invoice_settings,
            "tax_exempt": tax_exempt,
        }
        return await self._post(
            "/customers",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_customer(
        self,
        customer_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/customers/{customer_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def delete_customer(self, customer_id: str) -> Result:
        return await self._delete(f"/customers/{customer_id}")

    async def search_customers(
        self,
        query: str,
        *,
        limit: int = 10,
        page: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params: Dict[str, Any] = {"query": query, "limit": min(max(limit, 1), 100)}
        if page:
            params["page"] = page
        return await self._get("/customers/search", params=params, expand=expand)

    # ===============================================================
    # Payment intents
    # ===============================================================

    async def list_payment_intents(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        created_gte: Optional[int] = None,
        created_lte: Optional[int] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra: Dict[str, Any] = {"customer": customer}
        if created_gte is not None or created_lte is not None:
            created: Dict[str, Any] = {}
            if created_gte is not None:
                created["gte"] = created_gte
            if created_lte is not None:
                created["lte"] = created_lte
            extra["created"] = created
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/payment_intents", params=params, expand=expand)

    async def get_payment_intent(
        self,
        payment_intent_id: str,
        *,
        client_secret: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = {"client_secret": client_secret} if client_secret else None
        return await self._get(
            f"/payment_intents/{payment_intent_id}", params=params, expand=expand
        )

    async def create_payment_intent(
        self,
        *,
        amount: int,
        currency: Optional[str] = None,
        customer: Optional[str] = None,
        payment_method: Optional[str] = None,
        payment_method_types: Optional[List[str]] = None,
        automatic_payment_methods: Optional[Dict[str, Any]] = None,
        confirm: Optional[bool] = None,
        capture_method: Optional[str] = None,
        confirmation_method: Optional[str] = None,
        description: Optional[str] = None,
        receipt_email: Optional[str] = None,
        setup_future_usage: Optional[str] = None,
        statement_descriptor: Optional[str] = None,
        statement_descriptor_suffix: Optional[str] = None,
        application_fee_amount: Optional[int] = None,
        transfer_data: Optional[Dict[str, Any]] = None,
        on_behalf_of: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {
            "amount": amount,
            "currency": (currency or self._default_currency()).lower(),
            "customer": customer,
            "payment_method": payment_method,
            "payment_method_types": payment_method_types,
            "automatic_payment_methods": automatic_payment_methods,
            "confirm": confirm,
            "capture_method": capture_method,
            "confirmation_method": confirmation_method,
            "description": description,
            "receipt_email": receipt_email,
            "setup_future_usage": setup_future_usage,
            "statement_descriptor": statement_descriptor,
            "statement_descriptor_suffix": statement_descriptor_suffix,
            "application_fee_amount": application_fee_amount,
            "transfer_data": transfer_data,
            "on_behalf_of": on_behalf_of,
            "metadata": metadata,
        }
        if (
            payload["payment_method_types"] is None
            and payload["automatic_payment_methods"] is None
        ):
            # Stripe rejects PI creation when neither is set; default to the
            # modern automatic-payment-methods flow (Stripe's recommendation).
            payload["automatic_payment_methods"] = {"enabled": True}
        return await self._post(
            "/payment_intents",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_payment_intent(
        self,
        payment_intent_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payment_intents/{payment_intent_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def confirm_payment_intent(
        self,
        payment_intent_id: str,
        *,
        payment_method: Optional[str] = None,
        return_url: Optional[str] = None,
        receipt_email: Optional[str] = None,
        setup_future_usage: Optional[str] = None,
        off_session: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "payment_method": payment_method,
            "return_url": return_url,
            "receipt_email": receipt_email,
            "setup_future_usage": setup_future_usage,
            "off_session": off_session,
        }
        return await self._post(
            f"/payment_intents/{payment_intent_id}/confirm",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def capture_payment_intent(
        self,
        payment_intent_id: str,
        *,
        amount_to_capture: Optional[int] = None,
        application_fee_amount: Optional[int] = None,
        statement_descriptor: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "amount_to_capture": amount_to_capture,
            "application_fee_amount": application_fee_amount,
            "statement_descriptor": statement_descriptor,
        }
        return await self._post(
            f"/payment_intents/{payment_intent_id}/capture",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def cancel_payment_intent(
        self,
        payment_intent_id: str,
        *,
        cancellation_reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payment_intents/{payment_intent_id}/cancel",
            payload={"cancellation_reason": cancellation_reason},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def search_payment_intents(
        self,
        query: str,
        *,
        limit: int = 10,
        page: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params: Dict[str, Any] = {"query": query, "limit": min(max(limit, 1), 100)}
        if page:
            params["page"] = page
        return await self._get("/payment_intents/search", params=params, expand=expand)

    # ===============================================================
    # Charges (legacy direct-charge API — still useful for read paths)
    # ===============================================================

    async def list_charges(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        payment_intent: Optional[str] = None,
        transfer_group: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {
            "customer": customer,
            "payment_intent": payment_intent,
            "transfer_group": transfer_group,
        }
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/charges", params=params, expand=expand)

    async def get_charge(
        self, charge_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/charges/{charge_id}", expand=expand)

    # ===============================================================
    # Refunds
    # ===============================================================

    async def create_refund(
        self,
        *,
        payment_intent: Optional[str] = None,
        charge: Optional[str] = None,
        amount: Optional[int] = None,
        reason: Optional[str] = None,
        refund_application_fee: Optional[bool] = None,
        reverse_transfer: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        if not payment_intent and not charge:
            return {
                "error": "create_refund: pass exactly one of payment_intent or charge",
            }
        payload = {
            "payment_intent": payment_intent,
            "charge": charge,
            "amount": amount,
            "reason": reason,
            "refund_application_fee": refund_application_fee,
            "reverse_transfer": reverse_transfer,
            "metadata": metadata,
        }
        return await self._post(
            "/refunds",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def get_refund(
        self, refund_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/refunds/{refund_id}", expand=expand)

    async def list_refunds(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        payment_intent: Optional[str] = None,
        charge: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {"payment_intent": payment_intent, "charge": charge}
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/refunds", params=params, expand=expand)

    # ===============================================================
    # Payment methods
    # ===============================================================

    async def list_payment_methods(
        self,
        *,
        customer: Optional[str] = None,
        type: str = "card",
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        if customer:
            path = f"/customers/{customer}/payment_methods"
            extra = {"type": type}
        else:
            path = "/payment_methods"
            extra = {"type": type, "customer": None}
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get(path, params=params, expand=expand)

    async def get_payment_method(
        self, payment_method_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/payment_methods/{payment_method_id}", expand=expand)

    async def attach_payment_method(
        self,
        payment_method_id: str,
        *,
        customer: str,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payment_methods/{payment_method_id}/attach",
            payload={"customer": customer},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def detach_payment_method(
        self,
        payment_method_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payment_methods/{payment_method_id}/detach",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_payment_method(
        self,
        payment_method_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payment_methods/{payment_method_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Products
    # ===============================================================

    async def list_products(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        active: Optional[bool] = None,
        ids: Optional[List[str]] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra: Dict[str, Any] = {"active": active}
        if ids:
            extra["ids"] = ids
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/products", params=params, expand=expand)

    async def get_product(
        self, product_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/products/{product_id}", expand=expand)

    async def create_product(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        active: Optional[bool] = None,
        images: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        default_price_data: Optional[Dict[str, Any]] = None,
        shippable: Optional[bool] = None,
        statement_descriptor: Optional[str] = None,
        tax_code: Optional[str] = None,
        unit_label: Optional[str] = None,
        url: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "name": name,
            "description": description,
            "active": active,
            "images": images,
            "metadata": metadata,
            "default_price_data": default_price_data,
            "shippable": shippable,
            "statement_descriptor": statement_descriptor,
            "tax_code": tax_code,
            "unit_label": unit_label,
            "url": url,
        }
        return await self._post(
            "/products",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_product(
        self,
        product_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/products/{product_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def delete_product(self, product_id: str) -> Result:
        return await self._delete(f"/products/{product_id}")

    # ===============================================================
    # Prices
    # ===============================================================

    async def list_prices(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        active: Optional[bool] = None,
        product: Optional[str] = None,
        currency: Optional[str] = None,
        type: Optional[str] = None,
        recurring_interval: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra: Dict[str, Any] = {
            "active": active,
            "product": product,
            "currency": currency.lower() if currency else None,
            "type": type,
        }
        if recurring_interval:
            extra["recurring"] = {"interval": recurring_interval}
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/prices", params=params, expand=expand)

    async def get_price(
        self, price_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/prices/{price_id}", expand=expand)

    async def create_price(
        self,
        *,
        currency: Optional[str] = None,
        product: Optional[str] = None,
        product_data: Optional[Dict[str, Any]] = None,
        unit_amount: Optional[int] = None,
        unit_amount_decimal: Optional[str] = None,
        active: Optional[bool] = None,
        nickname: Optional[str] = None,
        recurring: Optional[Dict[str, Any]] = None,
        tax_behavior: Optional[str] = None,
        billing_scheme: Optional[str] = None,
        tiers: Optional[List[Dict[str, Any]]] = None,
        tiers_mode: Optional[str] = None,
        transform_quantity: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "currency": (currency or self._default_currency()).lower(),
            "product": product,
            "product_data": product_data,
            "unit_amount": unit_amount,
            "unit_amount_decimal": unit_amount_decimal,
            "active": active,
            "nickname": nickname,
            "recurring": recurring,
            "tax_behavior": tax_behavior,
            "billing_scheme": billing_scheme,
            "tiers": tiers,
            "tiers_mode": tiers_mode,
            "transform_quantity": transform_quantity,
            "metadata": metadata,
        }
        return await self._post(
            "/prices",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_price(
        self,
        price_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/prices/{price_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Invoices + invoice items
    # ===============================================================

    async def list_invoices(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        subscription: Optional[str] = None,
        status: Optional[str] = None,
        collection_method: Optional[str] = None,
        created_gte: Optional[int] = None,
        created_lte: Optional[int] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra: Dict[str, Any] = {
            "customer": customer,
            "subscription": subscription,
            "status": status,
            "collection_method": collection_method,
        }
        if created_gte is not None or created_lte is not None:
            created: Dict[str, Any] = {}
            if created_gte is not None:
                created["gte"] = created_gte
            if created_lte is not None:
                created["lte"] = created_lte
            extra["created"] = created
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/invoices", params=params, expand=expand)

    async def get_invoice(
        self, invoice_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/invoices/{invoice_id}", expand=expand)

    async def create_invoice(
        self,
        *,
        customer: str,
        auto_advance: Optional[bool] = None,
        collection_method: Optional[str] = None,
        days_until_due: Optional[int] = None,
        due_date: Optional[int] = None,
        description: Optional[str] = None,
        footer: Optional[str] = None,
        default_payment_method: Optional[str] = None,
        default_source: Optional[str] = None,
        statement_descriptor: Optional[str] = None,
        subscription: Optional[str] = None,
        from_invoice: Optional[Dict[str, Any]] = None,
        pending_invoice_items_behavior: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "customer": customer,
            "auto_advance": auto_advance,
            "collection_method": collection_method,
            "days_until_due": days_until_due,
            "due_date": due_date,
            "description": description,
            "footer": footer,
            "default_payment_method": default_payment_method,
            "default_source": default_source,
            "statement_descriptor": statement_descriptor,
            "subscription": subscription,
            "from_invoice": from_invoice,
            "pending_invoice_items_behavior": pending_invoice_items_behavior,
            "metadata": metadata,
        }
        return await self._post(
            "/invoices",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_invoice(
        self,
        invoice_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/invoices/{invoice_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def delete_invoice(self, invoice_id: str) -> Result:
        return await self._delete(f"/invoices/{invoice_id}")

    async def finalize_invoice(
        self,
        invoice_id: str,
        *,
        auto_advance: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/invoices/{invoice_id}/finalize",
            payload={"auto_advance": auto_advance},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def send_invoice(
        self,
        invoice_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/invoices/{invoice_id}/send",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def pay_invoice(
        self,
        invoice_id: str,
        *,
        payment_method: Optional[str] = None,
        source: Optional[str] = None,
        off_session: Optional[bool] = None,
        paid_out_of_band: Optional[bool] = None,
        forgive: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "payment_method": payment_method,
            "source": source,
            "off_session": off_session,
            "paid_out_of_band": paid_out_of_band,
            "forgive": forgive,
        }
        return await self._post(
            f"/invoices/{invoice_id}/pay",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def void_invoice(
        self,
        invoice_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/invoices/{invoice_id}/void",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def mark_invoice_uncollectible(
        self,
        invoice_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/invoices/{invoice_id}/mark_uncollectible",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def get_upcoming_invoice(
        self,
        *,
        customer: Optional[str] = None,
        subscription: Optional[str] = None,
        subscription_items: Optional[List[Dict[str, Any]]] = None,
        coupon: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params: Dict[str, Any] = {
            "customer": customer,
            "subscription": subscription,
            "subscription_items": subscription_items,
            "coupon": coupon,
        }
        return await self._get("/invoices/upcoming", params=params, expand=expand)

    async def list_invoice_items(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        invoice: Optional[str] = None,
        pending: Optional[bool] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {
            "customer": customer,
            "invoice": invoice,
            "pending": pending,
        }
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/invoiceitems", params=params, expand=expand)

    async def create_invoice_item(
        self,
        *,
        customer: str,
        invoice: Optional[str] = None,
        subscription: Optional[str] = None,
        amount: Optional[int] = None,
        currency: Optional[str] = None,
        price: Optional[str] = None,
        price_data: Optional[Dict[str, Any]] = None,
        quantity: Optional[int] = None,
        description: Optional[str] = None,
        discountable: Optional[bool] = None,
        discounts: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        period: Optional[Dict[str, int]] = None,
        tax_rates: Optional[List[str]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "customer": customer,
            "invoice": invoice,
            "subscription": subscription,
            "amount": amount,
            "currency": currency.lower() if currency else None,
            "price": price,
            "price_data": price_data,
            "quantity": quantity,
            "description": description,
            "discountable": discountable,
            "discounts": discounts,
            "metadata": metadata,
            "period": period,
            "tax_rates": tax_rates,
        }
        return await self._post(
            "/invoiceitems",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def delete_invoice_item(self, invoice_item_id: str) -> Result:
        return await self._delete(f"/invoiceitems/{invoice_item_id}")

    # ===============================================================
    # Subscriptions
    # ===============================================================

    async def list_subscriptions(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        price: Optional[str] = None,
        status: Optional[str] = None,
        collection_method: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {
            "customer": customer,
            "price": price,
            "status": status,
            "collection_method": collection_method,
        }
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/subscriptions", params=params, expand=expand)

    async def get_subscription(
        self, subscription_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/subscriptions/{subscription_id}", expand=expand)

    async def create_subscription(
        self,
        *,
        customer: str,
        items: List[Dict[str, Any]],
        cancel_at_period_end: Optional[bool] = None,
        collection_method: Optional[str] = None,
        days_until_due: Optional[int] = None,
        default_payment_method: Optional[str] = None,
        default_tax_rates: Optional[List[str]] = None,
        coupon: Optional[str] = None,
        promotion_code: Optional[str] = None,
        trial_period_days: Optional[int] = None,
        trial_end: Optional[int] = None,
        payment_behavior: Optional[str] = None,
        payment_settings: Optional[Dict[str, Any]] = None,
        proration_behavior: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "customer": customer,
            "items": items,
            "cancel_at_period_end": cancel_at_period_end,
            "collection_method": collection_method,
            "days_until_due": days_until_due,
            "default_payment_method": default_payment_method,
            "default_tax_rates": default_tax_rates,
            "coupon": coupon,
            "promotion_code": promotion_code,
            "trial_period_days": trial_period_days,
            "trial_end": trial_end,
            "payment_behavior": payment_behavior,
            "payment_settings": payment_settings,
            "proration_behavior": proration_behavior,
            "metadata": metadata,
        }
        return await self._post(
            "/subscriptions",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_subscription(
        self,
        subscription_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/subscriptions/{subscription_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def cancel_subscription(
        self,
        subscription_id: str,
        *,
        invoice_now: Optional[bool] = None,
        prorate: Optional[bool] = None,
        cancellation_details: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "invoice_now": invoice_now,
            "prorate": prorate,
            "cancellation_details": cancellation_details,
        }
        # DELETE /v1/subscriptions/:id — but Stripe accepts a body. httpx DELETE
        # with data= works; route through _post to keep idempotency handling.
        flat = _flatten_params(payload)
        ikey = self._maybe_idempotency_key(mutation=True, explicit=idempotency_key)
        return await arequest(
            "DELETE",
            f"{STRIPE_API}/subscriptions/{subscription_id}",
            headers=self._headers(idempotency_key=ikey),
            data=flat or None,
            expected=(200,),
        )

    async def resume_subscription(
        self,
        subscription_id: str,
        *,
        billing_cycle_anchor: Optional[str] = None,
        proration_behavior: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "billing_cycle_anchor": billing_cycle_anchor,
            "proration_behavior": proration_behavior,
        }
        return await self._post(
            f"/subscriptions/{subscription_id}/resume",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Coupons + promotion codes
    # ===============================================================

    async def list_coupons(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
        )
        return await self._get("/coupons", params=params, expand=expand)

    async def get_coupon(
        self, coupon_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/coupons/{coupon_id}", expand=expand)

    async def create_coupon(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        duration: str = "once",  # once | repeating | forever
        amount_off: Optional[int] = None,
        percent_off: Optional[float] = None,
        currency: Optional[str] = None,
        duration_in_months: Optional[int] = None,
        max_redemptions: Optional[int] = None,
        redeem_by: Optional[int] = None,
        applies_to: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "id": id,
            "name": name,
            "duration": duration,
            "amount_off": amount_off,
            "percent_off": percent_off,
            "currency": currency.lower() if currency else None,
            "duration_in_months": duration_in_months,
            "max_redemptions": max_redemptions,
            "redeem_by": redeem_by,
            "applies_to": applies_to,
            "metadata": metadata,
        }
        return await self._post(
            "/coupons",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_coupon(
        self,
        coupon_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/coupons/{coupon_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def delete_coupon(self, coupon_id: str) -> Result:
        return await self._delete(f"/coupons/{coupon_id}")

    async def list_promotion_codes(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        active: Optional[bool] = None,
        code: Optional[str] = None,
        coupon: Optional[str] = None,
        customer: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {
            "active": active,
            "code": code,
            "coupon": coupon,
            "customer": customer,
        }
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/promotion_codes", params=params, expand=expand)

    async def create_promotion_code(
        self,
        *,
        coupon: str,
        code: Optional[str] = None,
        customer: Optional[str] = None,
        active: Optional[bool] = None,
        expires_at: Optional[int] = None,
        max_redemptions: Optional[int] = None,
        restrictions: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "coupon": coupon,
            "code": code,
            "customer": customer,
            "active": active,
            "expires_at": expires_at,
            "max_redemptions": max_redemptions,
            "restrictions": restrictions,
            "metadata": metadata,
        }
        return await self._post(
            "/promotion_codes",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_promotion_code(
        self,
        promotion_code_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/promotion_codes/{promotion_code_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Checkout sessions
    # ===============================================================

    async def list_checkout_sessions(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        payment_intent: Optional[str] = None,
        subscription: Optional[str] = None,
        status: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {
            "customer": customer,
            "payment_intent": payment_intent,
            "subscription": subscription,
            "status": status,
        }
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/checkout/sessions", params=params, expand=expand)

    async def get_checkout_session(
        self, session_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/checkout/sessions/{session_id}", expand=expand)

    async def create_checkout_session(
        self,
        *,
        mode: str,  # payment | subscription | setup
        line_items: Optional[List[Dict[str, Any]]] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        return_url: Optional[str] = None,
        ui_mode: Optional[str] = None,  # hosted | embedded
        customer: Optional[str] = None,
        customer_email: Optional[str] = None,
        client_reference_id: Optional[str] = None,
        allow_promotion_codes: Optional[bool] = None,
        automatic_tax: Optional[Dict[str, Any]] = None,
        billing_address_collection: Optional[str] = None,
        shipping_address_collection: Optional[Dict[str, Any]] = None,
        payment_method_types: Optional[List[str]] = None,
        payment_intent_data: Optional[Dict[str, Any]] = None,
        subscription_data: Optional[Dict[str, Any]] = None,
        discounts: Optional[List[Dict[str, Any]]] = None,
        expires_at: Optional[int] = None,
        locale: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "mode": mode,
            "line_items": line_items,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "return_url": return_url,
            "ui_mode": ui_mode,
            "customer": customer,
            "customer_email": customer_email,
            "client_reference_id": client_reference_id,
            "allow_promotion_codes": allow_promotion_codes,
            "automatic_tax": automatic_tax,
            "billing_address_collection": billing_address_collection,
            "shipping_address_collection": shipping_address_collection,
            "payment_method_types": payment_method_types,
            "payment_intent_data": payment_intent_data,
            "subscription_data": subscription_data,
            "discounts": discounts,
            "expires_at": expires_at,
            "locale": locale,
            "metadata": metadata,
        }
        return await self._post(
            "/checkout/sessions",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def expire_checkout_session(
        self,
        session_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/checkout/sessions/{session_id}/expire",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def list_checkout_line_items(
        self,
        session_id: str,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
        )
        return await self._get(
            f"/checkout/sessions/{session_id}/line_items",
            params=params,
            expand=expand,
        )

    # ===============================================================
    # Payment links
    # ===============================================================

    async def list_payment_links(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        active: Optional[bool] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra={"active": active},
        )
        return await self._get("/payment_links", params=params, expand=expand)

    async def get_payment_link(
        self, payment_link_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/payment_links/{payment_link_id}", expand=expand)

    async def create_payment_link(
        self,
        *,
        line_items: List[Dict[str, Any]],
        after_completion: Optional[Dict[str, Any]] = None,
        allow_promotion_codes: Optional[bool] = None,
        automatic_tax: Optional[Dict[str, Any]] = None,
        billing_address_collection: Optional[str] = None,
        currency: Optional[str] = None,
        customer_creation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        payment_intent_data: Optional[Dict[str, Any]] = None,
        payment_method_types: Optional[List[str]] = None,
        subscription_data: Optional[Dict[str, Any]] = None,
        shipping_address_collection: Optional[Dict[str, Any]] = None,
        shipping_options: Optional[List[Dict[str, Any]]] = None,
        tax_id_collection: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "line_items": line_items,
            "after_completion": after_completion,
            "allow_promotion_codes": allow_promotion_codes,
            "automatic_tax": automatic_tax,
            "billing_address_collection": billing_address_collection,
            "currency": currency.lower() if currency else None,
            "customer_creation": customer_creation,
            "metadata": metadata,
            "payment_intent_data": payment_intent_data,
            "payment_method_types": payment_method_types,
            "subscription_data": subscription_data,
            "shipping_address_collection": shipping_address_collection,
            "shipping_options": shipping_options,
            "tax_id_collection": tax_id_collection,
        }
        return await self._post(
            "/payment_links",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_payment_link(
        self,
        payment_link_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payment_links/{payment_link_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def list_payment_link_line_items(
        self,
        payment_link_id: str,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
        )
        return await self._get(
            f"/payment_links/{payment_link_id}/line_items",
            params=params,
            expand=expand,
        )

    # ===============================================================
    # Customer portal sessions (Billing portal)
    # ===============================================================

    async def create_billing_portal_session(
        self,
        *,
        customer: str,
        return_url: Optional[str] = None,
        configuration: Optional[str] = None,
        flow_data: Optional[Dict[str, Any]] = None,
        locale: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "customer": customer,
            "return_url": return_url,
            "configuration": configuration,
            "flow_data": flow_data,
            "locale": locale,
        }
        return await self._post(
            "/billing_portal/sessions",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Disputes
    # ===============================================================

    async def list_disputes(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        charge: Optional[str] = None,
        payment_intent: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {"charge": charge, "payment_intent": payment_intent}
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/disputes", params=params, expand=expand)

    async def get_dispute(
        self, dispute_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/disputes/{dispute_id}", expand=expand)

    async def update_dispute(
        self,
        dispute_id: str,
        *,
        evidence: Optional[Dict[str, Any]] = None,
        submit: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "evidence": evidence,
            "submit": submit,
            "metadata": metadata,
        }
        return await self._post(
            f"/disputes/{dispute_id}",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def close_dispute(
        self,
        dispute_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/disputes/{dispute_id}/close",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Payouts + balance
    # ===============================================================

    async def list_payouts(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        status: Optional[str] = None,
        destination: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {"status": status, "destination": destination}
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/payouts", params=params, expand=expand)

    async def get_payout(
        self, payout_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/payouts/{payout_id}", expand=expand)

    async def create_payout(
        self,
        *,
        amount: int,
        currency: Optional[str] = None,
        description: Optional[str] = None,
        statement_descriptor: Optional[str] = None,
        method: Optional[str] = None,  # standard | instant
        source_type: Optional[str] = None,  # bank_account | card
        destination: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "amount": amount,
            "currency": (currency or self._default_currency()).lower(),
            "description": description,
            "statement_descriptor": statement_descriptor,
            "method": method,
            "source_type": source_type,
            "destination": destination,
            "metadata": metadata,
        }
        return await self._post(
            "/payouts",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_payout(
        self,
        payout_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payouts/{payout_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def cancel_payout(
        self,
        payout_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/payouts/{payout_id}/cancel",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def get_balance(self) -> Result:
        return await self._get("/balance")

    async def list_balance_transactions(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        type: Optional[str] = None,
        currency: Optional[str] = None,
        source: Optional[str] = None,
        payout: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {
            "type": type,
            "currency": currency.lower() if currency else None,
            "source": source,
            "payout": payout,
        }
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/balance_transactions", params=params, expand=expand)

    async def get_balance_transaction(
        self, balance_transaction_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(
            f"/balance_transactions/{balance_transaction_id}", expand=expand
        )

    # ===============================================================
    # Quotes
    # ===============================================================

    async def list_quotes(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        customer: Optional[str] = None,
        status: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra = {"customer": customer, "status": status}
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/quotes", params=params, expand=expand)

    async def get_quote(
        self, quote_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/quotes/{quote_id}", expand=expand)

    async def create_quote(
        self,
        *,
        customer: str,
        line_items: List[Dict[str, Any]],
        application_fee_amount: Optional[int] = None,
        application_fee_percent: Optional[float] = None,
        automatic_tax: Optional[Dict[str, Any]] = None,
        collection_method: Optional[str] = None,
        default_tax_rates: Optional[List[str]] = None,
        description: Optional[str] = None,
        discounts: Optional[List[Dict[str, Any]]] = None,
        expires_at: Optional[int] = None,
        footer: Optional[str] = None,
        from_quote: Optional[Dict[str, Any]] = None,
        header: Optional[str] = None,
        invoice_settings: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        on_behalf_of: Optional[str] = None,
        subscription_data: Optional[Dict[str, Any]] = None,
        test_clock: Optional[str] = None,
        transfer_data: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "customer": customer,
            "line_items": line_items,
            "application_fee_amount": application_fee_amount,
            "application_fee_percent": application_fee_percent,
            "automatic_tax": automatic_tax,
            "collection_method": collection_method,
            "default_tax_rates": default_tax_rates,
            "description": description,
            "discounts": discounts,
            "expires_at": expires_at,
            "footer": footer,
            "from_quote": from_quote,
            "header": header,
            "invoice_settings": invoice_settings,
            "metadata": metadata,
            "on_behalf_of": on_behalf_of,
            "subscription_data": subscription_data,
            "test_clock": test_clock,
            "transfer_data": transfer_data,
        }
        return await self._post(
            "/quotes",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_quote(
        self,
        quote_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/quotes/{quote_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def finalize_quote(
        self,
        quote_id: str,
        *,
        expires_at: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/quotes/{quote_id}/finalize",
            payload={"expires_at": expires_at},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def accept_quote(
        self,
        quote_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/quotes/{quote_id}/accept",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def cancel_quote(
        self,
        quote_id: str,
        *,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/quotes/{quote_id}/cancel",
            payload={},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    # ===============================================================
    # Events + webhook endpoints
    # ===============================================================

    async def list_events(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        type: Optional[str] = None,
        types: Optional[List[str]] = None,
        delivery_success: Optional[bool] = None,
        created_gte: Optional[int] = None,
        created_lte: Optional[int] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        extra: Dict[str, Any] = {
            "type": type,
            "types": types,
            "delivery_success": delivery_success,
        }
        if created_gte is not None or created_lte is not None:
            created: Dict[str, Any] = {}
            if created_gte is not None:
                created["gte"] = created_gte
            if created_lte is not None:
                created["lte"] = created_lte
            extra["created"] = created
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra=extra,
        )
        return await self._get("/events", params=params, expand=expand)

    async def get_event(
        self, event_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/events/{event_id}", expand=expand)

    async def list_webhook_endpoints(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
        )
        return await self._get("/webhook_endpoints", params=params, expand=expand)

    async def get_webhook_endpoint(
        self, endpoint_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/webhook_endpoints/{endpoint_id}", expand=expand)

    async def create_webhook_endpoint(
        self,
        *,
        url: str,
        enabled_events: List[str],
        description: Optional[str] = None,
        connect: Optional[bool] = None,
        api_version: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        payload = {
            "url": url,
            "enabled_events": enabled_events,
            "description": description,
            "connect": connect,
            "api_version": api_version,
            "metadata": metadata,
        }
        return await self._post(
            "/webhook_endpoints",
            payload=payload,
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def update_webhook_endpoint(
        self,
        endpoint_id: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        return await self._post(
            f"/webhook_endpoints/{endpoint_id}",
            payload=properties or {},
            expand=expand,
            idempotency_key=idempotency_key,
        )

    async def delete_webhook_endpoint(self, endpoint_id: str) -> Result:
        return await self._delete(f"/webhook_endpoints/{endpoint_id}")

    # ===============================================================
    # Files (multipart upload — separate host)
    # ===============================================================

    async def upload_file(
        self,
        file_path: str,
        *,
        purpose: str,  # dispute_evidence | identity_document | business_logo | …
        link_create: Optional[bool] = None,
        link_expires_at: Optional[int] = None,
    ) -> Result:
        if not os.path.isfile(file_path):
            return {"error": f"file not found: {file_path}"}
        cred = self._load()
        with open(file_path, "rb") as fh:
            blob = fh.read()
        files = {
            "file": (os.path.basename(file_path), blob),
        }
        data: Dict[str, Any] = {"purpose": purpose}
        if link_create is not None:
            data["file_link_data[create]"] = "true" if link_create else "false"
        if link_expires_at is not None:
            data["file_link_data[expires_at]"] = str(link_expires_at)
        # Multipart goes to the files host, not the main API host.
        return await arequest(
            "POST",
            f"{STRIPE_FILES_API}/files",
            headers={
                "Authorization": f"Bearer {cred.api_key}",
                "Stripe-Version": STRIPE_API_VERSION,
            },
            data=data,
            files=files,
            expected=(200, 201),
        )

    async def get_file(
        self, file_id: str, *, expand: Optional[List[str]] = None
    ) -> Result:
        return await self._get(f"/files/{file_id}", expand=expand)

    async def list_files(
        self,
        *,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        purpose: Optional[str] = None,
        expand: Optional[List[str]] = None,
    ) -> Result:
        params = self._list_params(
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
            extra={"purpose": purpose},
        )
        return await self._get("/files", params=params, expand=expand)
