"""WhatsApp Business provider — auth-layer bridge over the legacy
``WhatsAppBusinessClient``.

Bridge port: the v2 provider handles accounts/credentials only —
``operations()`` returns [] and ``guidance()`` returns "" because the
legacy WhatsApp Business action surface stays in place; account routing
happens centrally. The binding mixin below replaces the legacy client's
disk credential plumbing with the injected per-account credential,
exactly like ``SlackClientBinding``/``StripeClientBinding``.

WhatsApp Business is token-only (a Meta Graph API access token + phone
number id per WhatsApp Business number — the legacy handler's
``auth_type = "token"``), so ``oauth_spec()`` raises NotImplementedError
and there is no ``run_login``. The stored token is whatever the user
pasted (typically a long-lived System User token); the provider has no
refresh path → ``refresh()`` returns None.

One account = one WhatsApp Business **phone number**; identity is the
``phone_number_id`` (lowercased — Graph ids are numeric strings, so this
is normalization symmetry with the other providers, not case folding).
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from ...integrations.whatsapp_business import (
    GRAPH_API_BASE,
    WhatsAppBusinessClient,
    WhatsAppBusinessCredential,
)
from .._shared import LegacyListenerAdapter

_CRED_FIELDS = {f.name for f in fields(WhatsAppBusinessCredential)}


class WhatsAppBusinessClientBinding:
    """Overrides WhatsAppBusinessClient's disk plumbing: credential is
    injected per account. MRO puts this before the legacy client:

        class BoundWhatsAppBusinessClient(
            WhatsAppBusinessClientBinding, WhatsAppBusinessClient
        ): pass

    No token refresh — the provider stores the token the user pasted and
    has no rotation path, so ``_persist`` is never called (kept so the
    build_client contract is uniform across providers).
    """

    _cred: Optional[WhatsAppBusinessCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = WhatsAppBusinessCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> WhatsAppBusinessCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundWhatsAppBusinessClient(WhatsAppBusinessClientBinding, WhatsAppBusinessClient):
    """WhatsAppBusinessClient with per-account credential binding (see
    WhatsAppBusinessClientBinding)."""


class WhatsAppBusinessProvider:
    id = "whatsapp_business"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "WhatsApp Business"
    client_cls = BoundWhatsAppBusinessClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Phone number id (each WhatsApp Business number is one account),
        lowercased/stripped. None for junk shapes — never raises (this
        runs during migration)."""
        try:
            phone_number_id = credential.get("phone_number_id")
        except AttributeError:
            return None
        if isinstance(phone_number_id, str) and phone_number_id.strip():
            return phone_number_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        # Deliberate: no Meta Embedded Signup OAuth — the legacy handler is
        # token-only; each user pastes their own Cloud API token + phone id.
        raise NotImplementedError("whatsapp_business is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # pasted token; no provider-side refresh path

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Same verification the legacy WhatsAppBusinessHandler.login()
        runs: ``GET {GRAPH_API_BASE}/{phone_number_id}`` with the bearer
        token. Expects the legacy handler's field keys: ``access_token``
        and ``phone_number_id``.

        phone_number_id is a UI field, so identity is present by
        construction — but it is still validated against the Graph
        response id, so a token/phone-id mix-up (valid token, wrong or
        mistyped id) fails here instead of storing an account whose
        identity doesn't match what the API serves.

        Returns (ok, message, credential). The credential is the asdict
        of ``WhatsAppBusinessCredential`` — the same shape the legacy
        login() saved.
        """
        access_token = (credentials.get("access_token") or "").strip()
        phone_number_id = (credentials.get("phone_number_id") or "").strip()
        if not access_token:
            return False, "Missing WhatsApp Business access token (access_token).", None
        if not phone_number_id:
            return False, "Missing WhatsApp Business phone number ID (phone_number_id).", None

        result = http_request(
            "GET",
            f"{GRAPH_API_BASE}/{phone_number_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Invalid credentials: {result['error']}", None

        data = result.get("result") or {}
        returned_id = str(data.get("id") or "").strip()
        if returned_id and returned_id.lower() != phone_number_id.lower():
            return (
                False,
                f"Phone Number ID mismatch: you entered {phone_number_id} but the "
                f"API returned {returned_id}. Re-check the Phone Number ID on the "
                "WhatsApp > API Setup page.",
                None,
            )

        credential = asdict(
            WhatsAppBusinessCredential(
                access_token=access_token,
                phone_number_id=phone_number_id,
            )
        )
        display = data.get("display_phone_number") or ""
        name = data.get("verified_name") or ""
        label = " ".join(part for part in (name, display) if part)
        suffix = f" — {label}" if label else ""
        return (
            True,
            f"WhatsApp Business connected (phone number ID: {phone_number_id}){suffix}",
            credential,
        )

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy WhatsApp Business actions stay in place

    def guidance(self) -> str:
        return ""  # bridge provider — the legacy action surface has its own docs

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Optional[LegacyListenerAdapter]:
        """The Cloud API pushes inbound messages via webhooks; the legacy
        client has no listen loop (``supports_listening`` is the
        BasePlatformClient default False), so there is nothing to poll —
        checked dynamically so a future legacy listen loop gets bridged
        automatically."""
        if getattr(client, "supports_listening", False):
            return LegacyListenerAdapter(client, emit)
        return None
