# -*- coding: utf-8 -*-
"""WhatsApp Web integration — handler + client + QR-session helpers.

The QR session helpers (``start_qr_session`` / ``check_qr_session_status``
/ ``cancel_qr_session``) provide a stateful login flow for non-blocking
UIs (web settings page, etc.) that need to poll instead of awaiting the
QR scan synchronously.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    PlatformMessage,
    has_credential,
    load_config,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
)
from ...config import ConfigStore
from ...logger import get_logger

logger = get_logger(__name__)


@dataclass
class WhatsAppWebCredential:
    session_id: str = ""
    owner_phone: str = ""
    owner_name: str = ""


@dataclass
class WhatsAppWebConfig:
    """Runtime knobs persisted to ``whatsapp_web_config.json``."""

    # When True, only forward messages the owner sent to themselves
    # (self-chat). All other incoming messages — DMs from contacts, group
    # chats — are dropped before reaching the agent. Useful when the user
    # wants WhatsApp to act as a personal command channel only.
    self_messages_only: bool = False

    # Sanity cap for multi-account: each connected WhatsApp account runs
    # its own Baileys Node bridge (~50-100 MB) and takes one linked-device
    # slot on the phone. Starting a QR login beyond this cap is refused
    # with a clear error.
    max_accounts: int = 4


WHATSAPP_WEB = IntegrationSpec(
    name="whatsapp_web",
    cred_class=WhatsAppWebCredential,
    cred_file="whatsapp_web.json",
    platform_id="whatsapp_web",
)


def _whatsapp_web_config_file() -> str:
    """``whatsapp_web.json`` → ``whatsapp_web_config.json``."""
    stem = WHATSAPP_WEB.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# ════════════════════════════════════════════════════════════════════════
# Handler
# ════════════════════════════════════════════════════════════════════════


@register_handler(WHATSAPP_WEB.name)
class WhatsAppWebHandler(IntegrationHandler):
    spec = WHATSAPP_WEB
    display_name = "WhatsApp"
    description = "Messaging via Web (QR code)"
    auth_type = "interactive"
    config_class = WhatsAppWebConfig
    config_fields = [
        {
            "key": "self_messages_only",
            "label": "Self-messages only",
            "type": "checkbox",
            "help": "Only forward messages you send to yourself (the WhatsApp self-chat). "
            "Drops incoming DMs and group messages before they reach the agent.",
        },
        {
            "key": "max_accounts",
            "label": "Max accounts",
            "type": "number",
            "help": "Maximum WhatsApp accounts connected at once. Each account "
            "runs its own lightweight bridge process and uses one linked-device "
            "slot on its phone.",
        },
    ]
    icon = "whatsapp"
    fields: List = []

    @property
    def subcommands(self) -> List[str]:
        return ["login", "logout", "status"]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        # The CLI QR-in-terminal flow went with the legacy single-account
        # path (session-durability plan §2.8): it could only persist into
        # whatsapp_web.json, which no longer exists as a write target. The
        # LinkFlow + account-store path is the one connect path.
        return (
            False,
            "WhatsApp connects via QR from the Settings → Integrations page "
            "(or the connect_integration action). The CLI login flow was "
            "removed with the legacy single-account path.",
        )

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        """Cleanup for a stray/surviving legacy whatsapp_web.json — the
        real disconnect path is ``system_disconnect`` → ``teardown_account``
        per account. Only does work when a legacy file still exists."""
        if not has_credential(self.spec.cred_file):
            return False, "No WhatsApp credentials found."
        identity = None
        try:
            from ._bridge_client import normalize_wa_identity

            cred = load_credential(self.spec.cred_file, WhatsAppWebCredential)
            identity = normalize_wa_identity(cred.owner_phone if cred else None)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        if identity:
            try:
                from ._session import get_session_manager

                await get_session_manager().teardown(identity)
            except Exception as e:
                logger.warning(
                    f"[WHATSAPP_WEB] legacy logout teardown for '{identity}': {e}"
                )
        return True, "WhatsApp disconnected."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "WhatsApp: Not connected"
        cred = load_credential(self.spec.cred_file, WhatsAppWebCredential)
        if not cred:
            return True, "WhatsApp: Not connected"
        phone = cred.owner_phone or "unknown"
        name = cred.owner_name or ""
        label = f"+{phone}" + (f" ({name})" if name else "")
        return True, f"WhatsApp: Connected\n  - {label}"


# ════════════════════════════════════════════════════════════════════════
# Client
# ════════════════════════════════════════════════════════════════════════


def _bridge_result(result: Dict[str, Any], ok: Optional[bool] = None) -> Dict[str, Any]:
    """Wrap a bridge response for return: derive ``status`` and drop the
    bridge's redundant ``success`` bool — ``status`` already carries it, and
    shipping both doubled the envelope on every WhatsApp action result.

    ``ok`` overrides the derived status; when omitted, a missing ``success``
    key counts as failure — the bridge always sets it, so its absence means
    a malformed/partial response and must not be reported as a sent message.
    """
    if ok is None:
        ok = bool(result.get("success", False))
    return {
        "status": "success" if ok else "error",
        **{k: v for k, v in result.items() if k != "success"},
    }


@register_client
class WhatsAppWebClient(BasePlatformClient):
    spec = WHATSAPP_WEB
    PLATFORM_ID = WHATSAPP_WEB.platform_id

    _OWNER_ALIASES = {"user", "owner", "me", "self"}

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[WhatsAppWebCredential] = None
        self._bridge = None
        self._seen_ids: set = set()
        self._known_groups: set = set()
        self._agent_sent_ids: set = set()

    @property
    def _agent_prefix(self) -> str:
        name = ConfigStore.extras.get("agent_name", "AGENT")
        return f"[{name}] "

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> WhatsAppWebCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, WhatsAppWebCredential)
        if self._cred is None:
            raise RuntimeError(
                "No WhatsApp Web credentials found. Please log in first."
            )
        return self._cred

    @property
    def owner_phone(self) -> str:
        return self._load().owner_phone

    def _get_bridge(self):
        if self._bridge is None:
            from ._bridge_client import get_whatsapp_bridge

            self._bridge = get_whatsapp_bridge()
        return self._bridge

    def _store_updated_credential(self, updated: WhatsAppWebCredential) -> None:
        """Persist refreshed owner info captured from the bridge's ready
        event. Bound multi-account clients (the v2 provider binding)
        override this to route through the account store; the base client
        keeps it in memory only — the legacy whatsapp_web.json is never
        written anymore (legacy removal, session-durability plan §2.8)."""
        self._cred = updated

    async def connect(self) -> None:
        bridge = self._get_bridge()
        if not bridge.is_running:
            await bridge.start()
        if not bridge.is_ready:
            ready = await bridge.wait_for_ready(timeout=120.0)
            if not ready:
                raise RuntimeError(
                    "WhatsApp bridge did not become ready within timeout"
                )
        self._connected = True

    async def disconnect(self) -> None:
        await super().disconnect()
        bridge = self._get_bridge()
        if bridge.is_running:
            await bridge.stop()

    def _resolve_recipient(self, recipient: str) -> str:
        if recipient.strip().lower() in self._OWNER_ALIASES:
            phone = self.owner_phone
            if phone:
                return phone
        return recipient

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        prefixed_text = f"{self._agent_prefix}{text}"
        result = await bridge.send_message(to=resolved, text=prefixed_text)
        msg_id = result.get("message_id")
        if msg_id:
            self._agent_sent_ids.add(msg_id)
        return _bridge_result(result)

    async def send_media(
        self,
        recipient: str,
        media_path: str,
        caption: Optional[str] = None,
        send_as_sticker: bool = False,
        send_as_voice: bool = False,
        send_as_document: bool = False,
        quoted_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        result = await bridge.send_media(
            to=resolved,
            file_path=media_path,
            caption=caption,
            send_as_sticker=send_as_sticker,
            send_as_voice=send_as_voice,
            send_as_document=send_as_document,
            quoted_message_id=quoted_message_id,
        )
        msg_id = result.get("message_id")
        if msg_id:
            self._agent_sent_ids.add(msg_id)
        return _bridge_result(result)

    async def send_location(
        self, recipient: str, latitude: float, longitude: float, description: str = ""
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        result = await bridge.send_location(resolved, latitude, longitude, description)
        return _bridge_result(result)

    async def send_reply(
        self, recipient: str, text: str, quoted_message_id: str
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        prefixed = f"{self._agent_prefix}{text}"
        result = await bridge.send_reply(resolved, prefixed, quoted_message_id)
        msg_id = result.get("message_id")
        if msg_id:
            self._agent_sent_ids.add(msg_id)
        return _bridge_result(result)

    async def edit_message(self, message_id: str, new_body: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.edit_message(message_id, new_body)
        return _bridge_result(result)

    async def delete_message(
        self, message_id: str, everyone: bool = False
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.delete_message(message_id, everyone)
        return _bridge_result(result)

    async def forward_message(self, message_id: str, recipient: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        result = await bridge.forward_message(message_id, resolved)
        return _bridge_result(result)

    async def react_message(self, message_id: str, emoji: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.react_message(message_id, emoji)
        return _bridge_result(result)

    async def star_message(
        self, message_id: str, starred: bool = True
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.star_message(message_id, starred)
        return _bridge_result(result)

    async def download_message_media(
        self, message_id: str, dest_path: str
    ) -> Dict[str, Any]:
        """Download attached media from a message to a local path."""
        import base64 as _b64

        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.download_message_media(message_id)
        if not result.get("success"):
            return _bridge_result(result, ok=False)
        data_b64 = result.get("data_b64", "")
        if not data_b64:
            return {"status": "error", "error": "No media data returned"}
        try:
            dest_path = os.path.abspath(dest_path)
            parent = os.path.dirname(dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(_b64.b64decode(data_b64))
            return {
                "status": "success",
                "saved_to": dest_path,
                "mimetype": result.get("mimetype", ""),
                "filename": result.get("filename", ""),
                "size": os.path.getsize(dest_path),
            }
        except OSError as e:
            return {"status": "error", "error": str(e)}

    async def get_quoted_message(self, message_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.get_quoted_message(message_id)
        return _bridge_result(result)

    # ----- Chat operations -----

    async def mark_chat_read(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.mark_chat_read(chat_id))

    async def mark_chat_unread(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.mark_chat_unread(chat_id))

    async def archive_chat(self, chat_id: str, archive: bool = True) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.archive_chat(chat_id, archive))

    async def pin_chat(self, chat_id: str, pin: bool = True) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.pin_chat(chat_id, pin))

    async def mute_chat(
        self, chat_id: str, mute: bool = True, unmute_date: Optional[int] = None
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.mute_chat(chat_id, mute, unmute_date))

    async def clear_chat_messages(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.clear_chat_messages(chat_id))

    async def delete_chat(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.delete_chat(chat_id))

    async def send_typing_state(
        self, chat_id: str, state: str = "typing"
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.send_typing_state(chat_id, state))

    # ----- Groups -----

    async def create_group(self, name: str, participants: list) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.create_group(name, participants)
        return _bridge_result(result)

    async def group_add_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(
            await bridge.group_add_participants(group_id, participants)
        )

    async def group_remove_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(
            await bridge.group_remove_participants(group_id, participants)
        )

    async def group_promote_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(
            await bridge.group_promote_participants(group_id, participants)
        )

    async def group_demote_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(
            await bridge.group_demote_participants(group_id, participants)
        )

    async def group_set_subject(self, group_id: str, subject: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.group_set_subject(group_id, subject))

    async def group_set_description(
        self, group_id: str, description: str
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.group_set_description(group_id, description))

    async def group_get_info(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.group_get_info(group_id))

    async def group_leave(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.group_leave(group_id))

    async def group_invite_code(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.group_invite_code(group_id))

    async def group_revoke_invite(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.group_revoke_invite(group_id))

    async def accept_group_invite(self, invite_code: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.accept_group_invite(invite_code))

    # ----- Contacts -----

    async def block_contact(
        self, contact_id: str, block: bool = True
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.block_contact(contact_id, block))

    async def get_profile_pic_url(self, contact_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.get_profile_pic_url(contact_id))

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.get_contact(contact_id))

    async def get_all_contacts(
        self, my_contacts_only: bool = True, limit: int = 500
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.get_all_contacts(my_contacts_only, limit))

    async def check_number_on_whatsapp(self, number: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return _bridge_result(await bridge.check_number_on_whatsapp(number))

    async def get_chat_messages(
        self, phone_number: str, limit: int = 50
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.get_chat_messages(chat_id=phone_number, limit=limit)
        return _bridge_result(result)

    async def get_unread_chats(self) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.get_unread_chats()
        return _bridge_result(result)

    async def search_contact(self, name: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.search_contact(name=name)
        return _bridge_result(result)

    async def get_session_status(self) -> Optional[Dict[str, Any]]:
        bridge = self._get_bridge()
        if not bridge.is_running:
            return {"status": "disconnected", "ready": False}
        try:
            result = await bridge.get_status()
            return {
                "status": "connected" if result.get("ready") else "waiting",
                **result,
            }
        except Exception:
            return {"status": "disconnected", "ready": False}

    @property
    def supports_listening(self) -> bool:
        return True

    def _session_identity(self) -> str:
        """This client's account identity — the bound identity (v2 binding)
        or, for a bare legacy client, the credential's owner phone."""
        identity = getattr(self, "_identity", None)
        if identity:
            return identity
        from ._bridge_client import normalize_wa_identity

        resolved = normalize_wa_identity(self._load().owner_phone)
        if resolved is None:
            raise RuntimeError(
                "whatsapp_web credential has no owner phone/wid — cannot "
                "resolve which account's session to use"
            )
        return resolved

    async def start_listening(self, callback) -> None:
        """Delegate lifecycle to this account's session actor and subscribe
        to its events. The listener supervisor re-invokes this ~1Hz; the
        actor makes every repeat call a cheap state check — LAUNCHING,
        RECONNECTING (backoff), NEEDS_RELINK (parked until a fresh QR link)
        all spawn nothing here. The actor owns start/stop, supervision,
        heartbeat, and reconnect policy."""
        if self._listening:
            # Already subscribed — just point at the new callback. Lets a
            # new integration manager rewire onto a still-running session
            # (e.g. between test_live tests) without tearing down the
            # bridge session.
            self._message_callback = callback
            return
        self._cred = None
        from ._session import CONNECTED, get_session_manager

        identity = self._session_identity()
        session = get_session_manager().session_for(identity)
        # Register the callback up-front so any event the session forwards
        # during startup (incl. a late "ready" after we return) reaches us.
        self._message_callback = callback
        state = await session.ensure_started(self._on_bridge_event)
        self._listening = True
        self._connected = state == CONNECTED

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        # Graceful stop through the session actor: clean ``shutdown`` so
        # the bridge closes its socket properly — WhatsApp sees a proper
        # disconnect (like the desktop app on quit) instead of a crash,
        # which directly extends session credential lifetime.
        session = None
        try:
            from ._session import get_session_manager

            session = get_session_manager().peek(self._session_identity())
        except Exception:
            session = None
        if session is not None:
            try:
                await session.stop()
            except Exception as e:
                logger.warning(f"[WHATSAPP_WEB] Session stop error: {e}")
            return
        # No session actor (direct-wired bridge in tests / already-torn-down
        # account). Peek only — resolving via _get_bridge here would
        # re-register a bridge for a removed identity and leak a capacity
        # slot.
        bridge = self._bridge
        if bridge is None:
            try:
                from ._bridge_client import peek_whatsapp_bridge

                bridge = peek_whatsapp_bridge(self._session_identity())
            except Exception:
                bridge = None
        if bridge is None:
            return
        bridge.set_event_callback(None)
        try:
            await bridge.stop()
        except Exception as e:
            logger.warning(f"[WHATSAPP_WEB] Bridge stop error: {e}")

    async def _on_bridge_event(self, event: str, data: Dict[str, Any]) -> None:
        if event in ("message", "message_sent"):
            # Receipt is LOGGED: a message that dies in the filters below
            # must be traceable (2026-08-05 — three debugging rounds because
            # emitted events vanished without a line). Never log the body.
            # f-string, NOT printf-style args: the host logger is loguru,
            # which formats with str.format() — "%s" + positional args
            # prints the literal placeholders (observed 2026-08-05).
            logger.info(
                f"[WhatsApp] {event} event:"
                f" from={data.get('from', '?')}"
                f" to={data.get('to', '?')}"
                f" self_chat={data.get('is_self_chat', 'n/a')}"
                f" body_len={len(data.get('body', '') or '')}"
                # id + type are load-bearing for attachment download —
                # an id-less media message has no fetch handle (2026-08-17).
                f" type={data.get('type', '?')}"
                f" id={'yes' if data.get('id') else 'MISSING'}"
            )
        if event == "message":
            await self._handle_incoming_message(data)
        elif event == "message_sent":
            await self._handle_sent_message(data)
        elif event == "disconnected":
            self._connected = False
        elif event == "ready":
            self._connected = True
            self._refresh_owner_info(data)

    def _refresh_owner_info(self, data: Dict[str, Any]) -> None:
        """Persist owner phone/name captured from the ready event when they
        drifted from the stored credential (renames, first fill-in)."""
        owner_phone = (data or {}).get("owner_phone", "") or ""
        owner_name = (data or {}).get("owner_name", "") or ""
        if not owner_phone and not owner_name:
            return
        try:
            cred = self._load()
            if cred.owner_phone != owner_phone or cred.owner_name != owner_name:
                self._store_updated_credential(
                    WhatsAppWebCredential(
                        session_id=cred.session_id,
                        owner_phone=owner_phone or cred.owner_phone,
                        owner_name=owner_name or cred.owner_name,
                    )
                )
        except Exception as e:
            logger.warning(f"[WHATSAPP_WEB] owner-info refresh failed: {e}")

    # Bridge message ``type`` → normalized attachment kind. Text messages
    # are type "chat"; anything here is media fetchable by message_id via
    # download_message_media (docs/plans/attachment-reception-plan.md).
    _MEDIA_KINDS = {
        "image": "photo",
        "video": "video",
        "audio": "audio",
        "ptt": "voice",
        "document": "document",
        "sticker": "sticker",
    }

    @classmethod
    def _extract_attachments(cls, data: Dict[str, Any]) -> list:
        """Normalize a bridge message-event's media into
        PlatformMessage.attachments. The bridge sends only ``type`` (+
        ``has_media``) — name/mime/size arrive at download time, so the
        message_id is the whole fetch handle."""
        mtype = data.get("type", "")
        kind = cls._MEDIA_KINDS.get(mtype)
        if kind:
            return [{"kind": kind, "id": data.get("id", "")}]
        if mtype == "location":
            return [{"kind": "location"}]
        if mtype == "vcard":
            return [{"kind": "contact"}]
        return []

    async def _handle_incoming_message(self, data: Dict[str, Any]) -> None:
        if not self._listening or not self._message_callback:
            return

        # Self-chat messages arrive via _handle_sent_message (from_me=True),
        # so when self_messages_only is set we drop everything else here.
        cfg = (
            load_config(_whatsapp_web_config_file(), WhatsAppWebConfig)
            or WhatsAppWebConfig()
        )
        if cfg.self_messages_only:
            # Deliberate drop, but never a SILENT one: an undocumented drop
            # here cost a debugging session (2026-08-05 — bridge healthy,
            # message emitted, agent never triggered).
            logger.info(
                f"[WhatsApp] dropping message from {data.get('from', '?')} — "
                "self_messages_only is enabled (personal command channel mode)"
            )
            return

        msg_id = data.get("id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids.add(msg_id)

        if data.get("from_me", False):
            return

        body = data.get("body", "")
        attachments = self._extract_attachments(data)
        # Media-only messages (no caption) must not be dropped.
        if not body and not attachments:
            return

        chat = data.get("chat", {})
        contact = data.get("contact", {})
        is_group = chat.get("is_group", False)
        is_muted = chat.get("is_muted", False)
        chat_name = chat.get("name", "")
        if is_group:
            self._known_groups.add(chat_name)
        if is_muted and is_group:
            return
        if is_group and not self._is_mention_for_me(body):
            return

        sender_name = contact.get("name", "") or chat_name
        sender_id = data.get("from", "")
        timestamp = data.get("timestamp")

        ts: Optional[datetime] = None
        if timestamp:
            try:
                ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except Exception:
                ts = datetime.now(tz=timezone.utc)

        await self._message_callback(
            PlatformMessage(
                platform=self.PLATFORM_ID,
                sender_id=sender_id,
                sender_name=sender_name,
                text=body,
                channel_id=chat.get("id", ""),
                channel_name=chat_name,
                message_id=msg_id,
                timestamp=ts,
                attachments=attachments,
                raw={
                    "source": "WhatsApp Web",
                    "integrationType": "whatsapp_web",
                    "is_self_message": False,
                    "is_group": is_group,
                    "contactId": sender_id,
                    "contactName": sender_name,
                    "messageBody": body,
                    "chatId": chat.get("id", ""),
                    "chatName": chat_name,
                    "timestamp": str(timestamp or ""),
                },
            )
        )

    async def _handle_sent_message(self, data: Dict[str, Any]) -> None:
        if not self._listening or not self._message_callback:
            logger.info("[WhatsApp] sent-message dropped: not listening")
            return
        if not data.get("is_self_chat", False):
            logger.info(
                "[WhatsApp] sent-message dropped: not the self chat "
                f"(to={data.get('to', '?')} from={data.get('from', '?')})"
            )
            return

        msg_id = data.get("id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids.add(msg_id)

        if msg_id and msg_id in self._agent_sent_ids:
            self._agent_sent_ids.discard(msg_id)
            return

        body = data.get("body", "")
        attachments = self._extract_attachments(data)
        if (not body and not attachments) or body.startswith(self._agent_prefix):
            reason = "empty body" if not body else "agent echo (prefix match)"
            logger.info(f"[WhatsApp] sent-message dropped: {reason}")
            return

        chat = data.get("chat", {})
        chat_name = chat.get("name", "")
        timestamp = data.get("timestamp")

        ts: Optional[datetime] = None
        if timestamp:
            try:
                ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except Exception:
                ts = datetime.now(tz=timezone.utc)

        await self._message_callback(
            PlatformMessage(
                platform=self.PLATFORM_ID,
                sender_id=data.get("from", ""),
                sender_name=chat_name or "Self",
                text=body,
                channel_id=chat.get("id", ""),
                channel_name=chat_name,
                message_id=msg_id,
                timestamp=ts,
                attachments=attachments,
                raw={
                    "source": "WhatsApp Web",
                    "integrationType": "whatsapp_web",
                    "is_self_message": True,
                    "is_group": False,
                    "contactId": data.get("from", ""),
                    "contactName": chat_name or "Self",
                    "messageBody": body,
                    "chatId": chat.get("id", ""),
                    "chatName": chat_name,
                    "timestamp": str(timestamp or ""),
                },
            )
        )

    def _is_mention_for_me(self, text: str) -> bool:
        if "@" not in text:
            return False
        text_lower = text.lower()
        bridge = self._get_bridge()
        own_name = bridge.owner_name if bridge else ""
        if own_name:
            own_lower = own_name.lower()
            if f"@{own_lower}" in text_lower:
                return True
            first_name = own_lower.split()[0] if " " in own_lower else ""
            if first_name and f"@{first_name}" in text_lower:
                return True
            return False
        return True


# ════════════════════════════════════════════════════════════════════════
# QR-session API — thin delegates over the LinkFlow actor (_session.py)
# ════════════════════════════════════════════════════════════════════════
#
# Every ``start_qr_session`` gets a uuid session id and a LinkFlow with a
# fresh *pending* bridge (own Node process, own temp auth dir), so
# concurrent QR logins never collide. States the caller can see:
# ``qr_ready`` → ``scanned`` → ``promoting`` → ``connected`` (with the
# identity and full credential dict — the HOST stores the account via the
# IntegrationSystem; this package must not import from app/), plus
# ``timeout`` / ``cancelled`` / ``error``. Completed flows stay registered
# and return the same ``connected`` result on every poll — no
# pop-before-promote race, no "Session not found" after success. The
# legacy whatsapp_web.json is never written (legacy removal, §2.8).


async def start_qr_session(force: bool = False) -> Dict[str, Any]:
    """Start a fresh QR link flow. ``force`` bypasses the just-connected
    guard (explicit user clicks pass True; stale pollers can't ghost-start
    a flow). Refused with a clear error at the ``max_accounts`` cap."""
    try:
        from ._session import get_session_manager
    except ImportError:
        return {
            "success": False,
            "status": "error",
            "message": "WhatsApp bridge not available. Ensure Node.js >= 18 is installed.",
        }
    return await get_session_manager().start_link_flow(force=force)


async def check_qr_session_status(session_id: str) -> Dict[str, Any]:
    """Poll a started QR flow. On ``connected`` the result carries
    ``identity`` and ``credential`` for the host to store; polling a
    finished flow returns the same result again (idempotent)."""
    from ._session import get_session_manager

    return await get_session_manager().link_flow_status(session_id)


def cancel_qr_session(session_id: str) -> Dict[str, Any]:
    """Cancel a pending QR flow: stop its bridge AND delete its temp auth
    dir. Safe for unknown/finished ids. Sync entry — schedules on the
    running loop when there is one."""
    from ._session import get_session_manager

    manager = get_session_manager()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    try:
        if loop is not None:
            asyncio.ensure_future(manager.cancel_link_flow(session_id))
            return {"success": True, "message": "Session cancelled."}
        return asyncio.run(manager.cancel_link_flow(session_id))
    except Exception as e:
        logger.warning(f"Failed to cancel WhatsApp QR session: {e}")
        return {"success": True, "message": "Session cancelled."}
