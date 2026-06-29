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
import sys
import tempfile
import webbrowser
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
    save_credential,
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
    ]
    icon = "whatsapp"
    fields: List = []

    @property
    def subcommands(self) -> List[str]:
        return ["login", "logout", "status"]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        try:
            from ._bridge_client import get_whatsapp_bridge
        except ImportError:
            return (
                False,
                "WhatsApp bridge not available. Ensure Node.js >= 18 is installed.",
            )

        bridge = get_whatsapp_bridge()
        if not bridge.is_running:
            try:
                await bridge.start()
            except Exception as e:
                return False, f"Failed to start WhatsApp bridge: {e}"

        event_type, event_data = await bridge.wait_for_qr_or_ready(timeout=60.0)

        if event_type == "ready":
            owner_phone = bridge.owner_phone or ""
            owner_name = bridge.owner_name or ""
            save_credential(
                self.spec.cred_file,
                WhatsAppWebCredential(
                    session_id="bridge",
                    owner_phone=owner_phone,
                    owner_name=owner_name,
                ),
            )
            display = owner_phone or owner_name or "connected"
            return True, f"WhatsApp Web connected: +{display}"

        if event_type == "qr":
            qr_string = (event_data or {}).get("qr_string", "")
            if qr_string:
                try:
                    import qrcode

                    qr = qrcode.QRCode(border=1)
                    qr.add_data(qr_string)
                    qr.make(fit=True)
                    matrix = qr.get_matrix()
                    lines = [
                        "".join("##" if cell else "  " for cell in row)
                        for row in matrix
                    ]
                    sys.stderr.write("\n" + "\n".join(lines) + "\n\n")
                    sys.stderr.write(
                        "Scan the QR code above with WhatsApp on your phone\n\n"
                    )
                    sys.stderr.flush()
                except Exception:
                    pass

            qr_data_url = (event_data or {}).get("qr_data_url")
            if qr_data_url:
                import base64 as b64

                qr_b64 = qr_data_url
                if qr_b64.startswith("data:image"):
                    qr_b64 = qr_b64.split(",", 1)[1]
                qr_path = os.path.join(tempfile.gettempdir(), "whatsapp_qr_bridge.png")
                with open(qr_path, "wb") as f:
                    f.write(b64.b64decode(qr_b64))
                webbrowser.open(f"file://{qr_path}")

            ready = await bridge.wait_for_ready(timeout=120.0)
            if not ready:
                return (
                    False,
                    "Timed out waiting for QR scan. Run /whatsapp_web login again.",
                )

            owner_phone = bridge.owner_phone or ""
            owner_name = bridge.owner_name or ""
            save_credential(
                self.spec.cred_file,
                WhatsAppWebCredential(
                    session_id="bridge",
                    owner_phone=owner_phone,
                    owner_name=owner_name,
                ),
            )
            display = owner_phone or owner_name or "connected"
            return True, f"WhatsApp Web connected: +{display}"

        return (
            False,
            "Timed out waiting for WhatsApp bridge. Run /whatsapp_web login again.",
        )

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No WhatsApp credentials found."
        remove_credential(self.spec.cred_file)
        try:
            from ._bridge_client import get_whatsapp_bridge

            bridge = get_whatsapp_bridge()
            # ``logout()`` (not ``stop()``) — calls wwebjs's ``client.logout()``
            # which invalidates the session server-side and wipes the LocalAuth
            # data on disk. Without this, the next connect would silently
            # auto-restore the session and skip the QR scan, which makes the
            # disconnect ineffectual from the user's point of view.
            if bridge.is_running:
                await bridge.logout()
            else:
                # Bridge isn't running but LocalAuth data may still exist
                # from a previous session — wipe it directly.
                import shutil
                from pathlib import Path
                from ...config import ConfigStore

                shutil.rmtree(
                    Path(ConfigStore.project_root)
                    / ".credentials"
                    / "whatsapp_wwebjs_auth",
                    ignore_errors=True,
                )
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
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
        return {"status": "success" if result.get("success") else "error", **result}

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
        return {"status": "success" if result.get("success") else "error", **result}

    async def send_location(
        self, recipient: str, latitude: float, longitude: float, description: str = ""
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        result = await bridge.send_location(resolved, latitude, longitude, description)
        return {"status": "success" if result.get("success") else "error", **result}

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
        return {"status": "success" if result.get("success") else "error", **result}

    async def edit_message(self, message_id: str, new_body: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.edit_message(message_id, new_body)
        return {"status": "success" if result.get("success") else "error", **result}

    async def delete_message(
        self, message_id: str, everyone: bool = False
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.delete_message(message_id, everyone)
        return {"status": "success" if result.get("success") else "error", **result}

    async def forward_message(self, message_id: str, recipient: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        result = await bridge.forward_message(message_id, resolved)
        return {"status": "success" if result.get("success") else "error", **result}

    async def react_message(self, message_id: str, emoji: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.react_message(message_id, emoji)
        return {"status": "success" if result.get("success") else "error", **result}

    async def star_message(
        self, message_id: str, starred: bool = True
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.star_message(message_id, starred)
        return {"status": "success" if result.get("success") else "error", **result}

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
            return {"status": "error", **result}
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
        return {"status": "success" if result.get("success") else "error", **result}

    # ----- Chat operations -----

    async def mark_chat_read(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.mark_chat_read(chat_id))}

    async def mark_chat_unread(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.mark_chat_unread(chat_id))}

    async def archive_chat(self, chat_id: str, archive: bool = True) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.archive_chat(chat_id, archive))}

    async def pin_chat(self, chat_id: str, pin: bool = True) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.pin_chat(chat_id, pin))}

    async def mute_chat(
        self, chat_id: str, mute: bool = True, unmute_date: Optional[int] = None
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.mute_chat(chat_id, mute, unmute_date)),
        }

    async def clear_chat_messages(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.clear_chat_messages(chat_id))}

    async def delete_chat(self, chat_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.delete_chat(chat_id))}

    async def send_typing_state(
        self, chat_id: str, state: str = "typing"
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.send_typing_state(chat_id, state))}

    # ----- Groups -----

    async def create_group(self, name: str, participants: list) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        result = await bridge.create_group(name, participants)
        return {"status": "success" if result.get("success") else "error", **result}

    async def group_add_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.group_add_participants(group_id, participants)),
        }

    async def group_remove_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.group_remove_participants(group_id, participants)),
        }

    async def group_promote_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.group_promote_participants(group_id, participants)),
        }

    async def group_demote_participants(
        self, group_id: str, participants: list
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.group_demote_participants(group_id, participants)),
        }

    async def group_set_subject(self, group_id: str, subject: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.group_set_subject(group_id, subject)),
        }

    async def group_set_description(
        self, group_id: str, description: str
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.group_set_description(group_id, description)),
        }

    async def group_get_info(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.group_get_info(group_id))}

    async def group_leave(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.group_leave(group_id))}

    async def group_invite_code(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.group_invite_code(group_id))}

    async def group_revoke_invite(self, group_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.group_revoke_invite(group_id))}

    async def accept_group_invite(self, invite_code: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.accept_group_invite(invite_code))}

    # ----- Contacts -----

    async def block_contact(
        self, contact_id: str, block: bool = True
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.block_contact(contact_id, block))}

    async def get_profile_pic_url(self, contact_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.get_profile_pic_url(contact_id))}

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.get_contact(contact_id))}

    async def get_all_contacts(
        self, my_contacts_only: bool = True, limit: int = 500
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {
            "status": "success",
            **(await bridge.get_all_contacts(my_contacts_only, limit)),
        }

    async def check_number_on_whatsapp(self, number: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        return {"status": "success", **(await bridge.check_number_on_whatsapp(number))}

    async def get_chat_messages(
        self, phone_number: str, limit: int = 50
    ) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.get_chat_messages(chat_id=phone_number, limit=limit)
        return {"status": "success" if result.get("success") else "error", **result}

    async def get_unread_chats(self) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.get_unread_chats()
        return {"status": "success" if result.get("success") else "error", **result}

    async def search_contact(self, name: str) -> Dict[str, Any]:
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.search_contact(name=name)
        return {"status": "success" if result.get("success") else "error", **result}

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

    async def start_listening(self, callback) -> None:
        if self._listening:
            # Already wired to the bridge — just point at the new callback.
            # Lets a new integration manager rewire onto a still-running
            # bridge (e.g. between test_live tests) without tearing down
            # and reattaching the wwebjs Playwright session. Production
            # only calls start_listening once at boot, so this is a no-op
            # there.
            self._message_callback = callback
            return
        self._cred = None
        bridge = self._get_bridge()

        # Register the callback up-front so any event the bridge emits during
        # startup (incl. a late "ready" after we return) flows through to us.
        self._message_callback = callback
        bridge.set_event_callback(self._on_bridge_event)

        if bridge.is_running and bridge.is_ready:
            event_type = "ready"
        else:
            if bridge.is_running:
                await bridge.stop()
                await asyncio.sleep(2)
            await bridge.start()
            # 180s gives whatsapp-web.js room to finish post-auth chat sync;
            # on slower restarts the "ready" event can lag well behind the
            # "authenticated" event.
            event_type, _ = await bridge.wait_for_qr_or_ready(timeout=180.0)

        if event_type == "qr":
            # Need a fresh QR scan — credentials are stale, tear down.
            bridge.set_event_callback(None)
            await bridge.abandon()
            self._message_callback = None
            return

        # If wwebjs hasn't fired "ready" yet (timeout), don't fail —
        # leave the bridge running with our callback wired. The "ready"
        # event will arrive eventually (or won't, but the user will see
        # status="waiting" rather than us tearing the session down).
        if event_type != "ready":
            logger.warning(
                "[WHATSAPP_WEB] Bridge authenticated but 'ready' event not "
                "received within 180s — leaving bridge running, listener will "
                "activate when wwebjs finishes syncing."
            )
            self._listening = True
            return

        if bridge.owner_phone or bridge.owner_name:
            cred = self._load()
            if (
                cred.owner_phone != bridge.owner_phone
                or cred.owner_name != bridge.owner_name
            ):
                updated = WhatsAppWebCredential(
                    session_id=cred.session_id,
                    owner_phone=bridge.owner_phone or cred.owner_phone,
                    owner_name=bridge.owner_name or cred.owner_name,
                )
                save_credential(self.spec.cred_file, updated)
                self._cred = updated

        self._listening = True
        self._connected = True

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        bridge = self._get_bridge()
        bridge.set_event_callback(None)
        # Send the bridge a clean ``shutdown`` command so wwebjs runs
        # ``client.destroy()`` before the Node subprocess exits. Without this,
        # the agent's Python process dies and Node gets killed by OS cleanup
        # — WhatsApp's server treats that as a crash and invalidates the
        # session faster than it would for a clean disconnect (which is what
        # the desktop app sends on quit).
        try:
            await bridge.stop()
        except Exception as e:
            logger.warning(f"[WHATSAPP_WEB] Bridge stop error: {e}")

    async def _on_bridge_event(self, event: str, data: Dict[str, Any]) -> None:
        if event == "message":
            await self._handle_incoming_message(data)
        elif event == "message_sent":
            await self._handle_sent_message(data)
        elif event == "disconnected":
            self._connected = False
        elif event == "ready":
            self._connected = True

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
            return

        msg_id = data.get("id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids.add(msg_id)

        if data.get("from_me", False):
            return

        body = data.get("body", "")
        if not body:
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
            return
        if not data.get("is_self_chat", False):
            return

        msg_id = data.get("id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids.add(msg_id)

        if msg_id and msg_id in self._agent_sent_ids:
            self._agent_sent_ids.discard(msg_id)
            return

        body = data.get("body", "")
        if not body or body.startswith(self._agent_prefix):
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
# QR-session helpers — for non-blocking UIs that poll
# ════════════════════════════════════════════════════════════════════════

_qr_sessions: Dict[str, Any] = {}


async def start_qr_session() -> Dict[str, Any]:
    """Start the bridge and return either ``qr_ready`` (with QR data URL) or
    ``connected`` (already authenticated). Caller polls
    ``check_qr_session_status(session_id)`` until ``connected``."""
    try:
        from ._bridge_client import get_whatsapp_bridge
    except ImportError:
        return {
            "success": False,
            "status": "error",
            "message": "WhatsApp bridge not available. Ensure Node.js >= 18 is installed.",
        }

    try:
        bridge = get_whatsapp_bridge()
        if not bridge.is_running:
            await bridge.start()
        event_type, event_data = await bridge.wait_for_qr_or_ready(timeout=60.0)

        if event_type == "ready":
            owner_phone = bridge.owner_phone or ""
            owner_name = bridge.owner_name or ""
            save_credential(
                WHATSAPP_WEB.cred_file,
                WhatsAppWebCredential(
                    session_id="bridge",
                    owner_phone=owner_phone,
                    owner_name=owner_name,
                ),
            )
            display = owner_phone or owner_name or "connected"
            return {
                "success": True,
                "session_id": "bridge",
                "qr_code": "",
                "status": "connected",
                "message": f"WhatsApp already connected: +{display}",
            }

        if event_type == "qr":
            qr_data = (event_data or {}).get("qr_data_url", "")
            if not qr_data:
                qr_string = (event_data or {}).get("qr_string", "")
                if qr_string:
                    try:
                        import qrcode
                        import io
                        import base64

                        qr = qrcode.QRCode(border=1)
                        qr.add_data(qr_string)
                        qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white")
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        qr_data = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
                    except Exception as e:
                        logger.warning(f"Failed to generate QR image: {e}")

            if not qr_data:
                await bridge.stop()
                return {
                    "success": False,
                    "status": "error",
                    "message": "Failed to generate QR code.",
                }
            if qr_data and not qr_data.startswith("data:"):
                qr_data = f"data:image/png;base64,{qr_data}"

            session_id = "bridge"
            _qr_sessions[session_id] = bridge
            return {
                "success": True,
                "session_id": session_id,
                "qr_code": qr_data,
                "status": "qr_ready",
                "message": "Scan the QR code with your WhatsApp mobile app",
            }

        await bridge.stop()
        return {
            "success": False,
            "status": "error",
            "message": "Timed out waiting for WhatsApp bridge.",
        }
    except Exception as e:
        logger.error(f"Failed to start WhatsApp QR session: {e}")
        return {
            "success": False,
            "status": "error",
            "message": f"Failed to start session: {e}",
        }


async def check_qr_session_status(session_id: str) -> Dict[str, Any]:
    """Poll a started QR session. On ``connected`` it saves the credential
    and starts the platform listener if a manager is running."""
    bridge = _qr_sessions.get(session_id)
    if bridge is None:
        return {
            "success": False,
            "status": "error",
            "connected": False,
            "message": "Session not found. Please start a new session.",
        }

    try:
        if bridge.is_ready:
            try:
                owner_phone = bridge.owner_phone or ""
                owner_name = bridge.owner_name or ""
                save_credential(
                    WHATSAPP_WEB.cred_file,
                    WhatsAppWebCredential(
                        session_id="bridge",
                        owner_phone=owner_phone,
                        owner_name=owner_name,
                    ),
                )
                del _qr_sessions[session_id]

                # Best-effort: start the listener if a manager is running.
                try:
                    from ...manager import get_external_comms_manager

                    manager = get_external_comms_manager()
                    if manager:
                        await manager.start_platform(WHATSAPP_WEB.platform_id)
                except Exception:
                    pass

                display = owner_phone or owner_name or "connected"
                return {
                    "success": True,
                    "status": "connected",
                    "connected": True,
                    "message": f"WhatsApp connected: +{display}",
                }
            except Exception as e:
                logger.error(f"Failed to store WhatsApp credential: {e}")
                return {
                    "success": False,
                    "status": "error",
                    "connected": False,
                    "message": f"Connected but failed to save: {e}",
                }
        elif not bridge.is_running:
            if session_id in _qr_sessions:
                del _qr_sessions[session_id]
            return {
                "success": False,
                "status": "error",
                "connected": False,
                "message": "WhatsApp bridge stopped unexpectedly. Please try again.",
            }
        else:
            return {
                "success": True,
                "status": "qr_ready",
                "connected": False,
                "message": "Waiting for QR code scan...",
            }
    except Exception as e:
        logger.error(f"Failed to check WhatsApp session status: {e}")
        return {
            "success": False,
            "status": "error",
            "connected": False,
            "message": f"Status check failed: {e}",
        }


def cancel_qr_session(session_id: str) -> Dict[str, Any]:
    bridge = _qr_sessions.pop(session_id, None)
    if bridge is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(bridge.stop())
            else:
                loop.run_until_complete(bridge.stop())
        except Exception:
            pass
        return {"success": True, "message": "Session cancelled."}
    return {"success": True, "message": "Session not found or already cancelled."}
