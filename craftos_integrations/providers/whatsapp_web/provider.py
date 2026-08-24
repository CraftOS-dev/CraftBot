"""WhatsApp Web bridge provider — auth-layer-only port of the legacy
client, with per-account Node bridges (wave 3 of the legacy-to-v2 plan).

Bridge pattern (see telegram_bot/provider.py for the binding rationale):
the battle-tested legacy ``WhatsAppWebClient`` keeps its entire API
surface; the binding mixin injects the per-account credential and — the
whatsapp-specific part — binds the client to that account's OWN
``WhatsAppBridge`` from the registry in ``_bridge_client``. One account
= one Node subprocess speaking WhatsApp's WebSocket protocol via Baileys
= one auth dir (``whatsapp_wwebjs_auth/<identity>/`` of plain key
files); the old process-wide singleton is gone.

Auth is a QR scan, not a token and not OAuth: ``oauth_spec()`` raises
NotImplementedError and there is deliberately NO ``run_login`` and NO
``verify_token`` — the only connect path is the QR session flow in the
legacy module (``start_qr_session`` / ``check_qr_session_status``),
which the host drives and which returns the identity + full credential
dict on ``connected`` for the host to store via the IntegrationSystem
(this package cannot write the AccountSet itself — layering).

One account = one **phone number**; identity is the normalized owner
wid/phone via ``normalize_wa_identity`` (digits of the wid without the
``:NN`` device suffix and ``@c.us`` domain — the ONE rule shared with
the QR flow and the bridge registry). The credential dict carries
``wid`` (preferred, it is WhatsApp's own id) and ``owner_phone`` (also
present in pre-bridge legacy credentials, so ``identity_of`` resolves
those too and the core's legacy-file migration lands on the right
identity instead of LEGACY_IDENTITY).

Sessions live in the bridge's auth dir, not in the credential — nothing
to rotate, so ``refresh()`` returns None. A revoked session surfaces as
a ``qr`` event on the next listener start (the session actor parks the
account as needs-relink until a fresh QR link).

Listener safety — how two accounts' events stay apart: each bound client
holds its own bridge instance, and a bridge fans events out to exactly
one callback (``set_event_callback``), wired to the owning client's
``_on_bridge_event`` inside the legacy ``start_listening``. All dedup /
echo-suppression state (``_seen_ids``, ``_agent_sent_ids``,
``_known_groups``, ``_message_callback``) is per client instance. The
one shared bit is the module-level *config* file (``self_messages_only``)
— a global read-only preference applied to every account alike, same as
telegram_bot/telegram_user.

Legacy disk touchpoints the binding neutralizes: ``has_credentials`` /
``_load`` (read whatsapp_web.json) answer from the injected credential;
``_get_bridge`` resolves the registry by identity instead of the legacy
single-account lookup; ``_store_updated_credential`` (owner-info refresh
captured at the ready event) routes through ``persist`` into the account
entry instead of overwriting the legacy json.

Account removal: the core's ``remove_account`` knows nothing about Node
processes, so the host must ALSO call ``teardown_account(identity)``
(module-level here, or the provider method of the same name) on
disconnect — it stops that account's bridge, attempts a server-side
logout, deletes its auth dir, and forgets it in the registry.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...contracts import OAuthSpec, Operation
from ...integrations.whatsapp_web import WhatsAppWebClient, WhatsAppWebCredential
from ...integrations.whatsapp_web._bridge_client import (
    get_whatsapp_bridge,
    normalize_wa_identity,
)
from ...integrations.whatsapp_web._bridge_client import (
    teardown_account as _teardown_account,
)
from .._shared import LegacyListenerAdapter

_CRED_FIELDS = {f.name for f in fields(WhatsAppWebCredential)}


async def teardown_account(identity: str) -> None:
    """Host hook for WhatsApp account removal (call on disconnect, after
    the core's ``remove_account``): stops the account's Node bridge,
    attempts a server-side logout, deletes its LocalAuth auth dir, and
    drops it from the bridge registry. Idempotent; accepts any phone/wid
    spelling."""
    await _teardown_account(identity)


class WhatsAppWebClientBinding:
    """Overrides WhatsAppWebClient's disk + singleton plumbing: credential
    injected per account, bridge resolved per identity. MRO puts this
    before the legacy client:

        class BoundWhatsAppWebClient(WhatsAppWebClientBinding, WhatsAppWebClient): pass

    ``_load`` ignores the legacy ``self._cred`` attribute entirely (the
    legacy ``start_listening`` nulls and reassigns it) and answers from
    ``_bound_cred``, so the bound client never touches whatsapp_web.json.
    """

    _bound_cred: Optional[WhatsAppWebCredential] = None
    _identity: Optional[str] = None
    _raw_cred: Dict[str, Any]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        # Filters to legacy dataclass fields — drops the provider-level
        # ``wid`` key the legacy client doesn't know about.
        self._bound_cred = WhatsAppWebCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        identity = normalize_wa_identity(
            credential.get("wid") or credential.get("owner_phone")
        )
        if identity is None:
            raise ValueError(
                "whatsapp_web credential has no owner phone/wid — cannot "
                "resolve which account's bridge to bind"
            )
        self._identity = identity
        self._raw_cred = dict(credential)
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._bound_cred is not None

    def _load(self) -> WhatsAppWebCredential:
        if self._bound_cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._bound_cred

    def _get_bridge(self):
        # Per-account bridge from the registry — NEVER the legacy
        # single-account resolution. Cached on the instance like the
        # legacy client does.
        if self._bridge is None:
            if self._identity is None:
                raise RuntimeError("client used before bind_credential()")
            self._bridge = get_whatsapp_bridge(self._identity)
        return self._bridge

    def _store_updated_credential(self, updated: WhatsAppWebCredential) -> None:
        # Owner info refreshed from the bridge's ready event → the
        # account entry via persist, not the legacy whatsapp_web.json.
        # ``wid`` (and any other provider-level keys) are preserved from
        # the originally bound credential so the identity stays stable.
        self._bound_cred = updated
        self._raw_cred = {
            **self._raw_cred,
            "session_id": updated.session_id,
            "owner_phone": updated.owner_phone,
            "owner_name": updated.owner_name,
        }
        self._persist(dict(self._raw_cred))


class BoundWhatsAppWebClient(WhatsAppWebClientBinding, WhatsAppWebClient):
    """WhatsAppWebClient bound to one account's credential and bridge."""


class WhatsAppWebProvider:
    id = "whatsapp_web"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "WhatsApp"
    client_cls = BoundWhatsAppWebClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Normalized owner wid/phone (``normalize_wa_identity`` — the one
        rule). Prefers the ``wid`` captured by the QR flow (WhatsApp's
        own id); falls back to ``owner_phone`` so legacy pre-bridge
        credentials resolve too. None for junk shapes."""
        try:
            wid = credential.get("wid")
            phone = credential.get("owner_phone")
        except AttributeError:
            return None
        return normalize_wa_identity(wid) or normalize_wa_identity(phone)

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("whatsapp_web uses QR login")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # the session lives in LocalAuth on disk, not the credential

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy action functions stay the surface

    def guidance(self) -> str:
        return ""

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> LegacyListenerAdapter:
        """The legacy client's own bridge-event listen loop, reused
        verbatim: ``start_listening`` starts (or reattaches to) THIS
        account's bridge and wires its single event callback to this
        client — per-account bridges mean two listening accounts never
        share an event stream. No restart-safe cursor, same as under the
        legacy manager (the bridge re-emits from WhatsApp's own sync)."""
        return LegacyListenerAdapter(client, emit)

    async def teardown_account(self, identity: str) -> None:
        """Provider-method spelling of the module-level hook (host may
        hold only the provider instance)."""
        await _teardown_account(identity)
