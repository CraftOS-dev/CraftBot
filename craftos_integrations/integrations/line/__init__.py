# -*- coding: utf-8 -*-
"""LINE Messaging API integration.

LINE delivers inbound messages via webhooks only - there is no long-poll
endpoint. The bot needs a public HTTPS URL registered in the LINE
Developers console to receive messages, which a desktop agent cannot
provide directly. This integration is therefore **send-only** out of the
box: ``send_message`` (push) and ``reply_message`` work; ``start_listening``
is not supported.

Credentials come from the LINE Developers console
(https://developers.line.biz/console/) under your provider â†’ Messaging
API channel:
    - Channel access token (long-lived) - for the Authorization header.
    - Channel secret - used to verify webhook signatures (stored for
      future webhook-server use; not required for send-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    has_credential,
    load_config,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"


@dataclass
class LineCredential:
    channel_access_token: str = ""
    channel_secret: str = ""
    bot_user_id: str = ""
    bot_display_name: str = ""


@dataclass
class LineConfig:
    """Runtime knobs persisted to ``line_config.json``."""

    # When True, every outgoing push/multicast/broadcast is sent with
    # ``notificationDisabled: true`` - recipients receive the message but
    # no push alert. Useful for bulk/automated sends that shouldn't wake
    # users up.
    notification_disabled: bool = False
    # Optional prefix prepended to every outgoing text message (e.g.
    # ``"[CraftBot] "``). Empty means no prefix. Helps recipients
    # distinguish bot-generated messages from human ones.
    message_prefix: str = ""


LINE = IntegrationSpec(
    name="line",
    cred_class=LineCredential,
    cred_file="line.json",
    platform_id="line",
)


def _line_config_file() -> str:
    """``line.json`` â†’ ``line_config.json``."""
    stem = LINE.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(LINE.name)
class LineHandler(IntegrationHandler):
    spec = LINE
    display_name = "LINE Business"
    description = "Messaging via LINE Messaging API (send-only)"
    auth_type = "token"
    icon = "line"
    connect_help = [
        "Open LINE Developers Console: developers.line.biz/console",
        "Sign in with your LINE account",
        "Create a Provider, then create a Messaging API channel inside it",
        "Channel Secret â†’ Basic settings tab â†’ 'Channel secret' field",
        "Channel Access Token â†’ Messaging API tab â†’ 'Issue' button under 'Channel access token (long-lived)'",
    ]
    fields = [
        {
            "key": "channel_access_token",
            "label": "Channel Access Token",
            "placeholder": "Long-lived token from LINE Developers console",
            "password": True,
        },
        {
            "key": "channel_secret",
            "label": "Channel Secret",
            "placeholder": "From the same Messaging API channel",
            "password": True,
            "optional": True,
        },
    ]

    config_class = LineConfig
    config_fields = [
        {
            "key": "notification_disabled",
            "label": "Silent delivery",
            "type": "checkbox",
            "help": "Send all push/multicast/broadcast messages with notificationDisabled=true. "
            "Recipients receive the message but get no push alert.",
        },
        {
            "key": "message_prefix",
            "label": "Message prefix",
            "type": "text",
            "placeholder": "[CraftBot] ",
            "help": "Optional prefix prepended to every outgoing text message. Leave empty for none.",
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: /line login <channel_access_token> [channel_secret]\n"
                "Get from https://developers.line.biz/console/ â†’ "
                "Messaging API channel â†’ Channel access token (long-lived)."
            )
        token = args[0]
        secret = args[1] if len(args) > 1 else ""

        result = http_request(
            "GET",
            f"{LINE_API_BASE}/info",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Invalid channel access token: {result['error']}"
        info = result.get("result", {})

        save_credential(
            self.spec.cred_file,
            LineCredential(
                channel_access_token=token,
                channel_secret=secret,
                bot_user_id=info.get("userId", ""),
                bot_display_name=info.get("displayName", ""),
            ),
        )
        label = info.get("displayName") or info.get("userId") or "bot"
        return True, f"LINE connected: {label}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No LINE credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed LINE credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "LINE: Not connected"
        cred = load_credential(self.spec.cred_file, LineCredential)
        if not cred:
            return True, "LINE: Connected\n  - bot configured"
        name = cred.bot_display_name or "LINE bot"
        ident = cred.bot_user_id or "bot configured"
        return True, f"LINE: Connected\n  - {name} ({ident})"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class LineClient(BasePlatformClient):
    spec = LINE
    PLATFORM_ID = LINE.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[LineCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> LineCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, LineCredential)
        if self._cred is None:
            raise RuntimeError("No LINE credentials. Use /line login first.")
        return self._cred

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        return {
            "Authorization": f"Bearer {cred.channel_access_token}",
            "Content-Type": "application/json",
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return self.push_text(recipient, text)

    # LINE delivers inbound messages via webhook only; no long-poll
    # equivalent exists. Listening is intentionally not implemented.
    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def _config(self) -> LineConfig:
        return load_config(_line_config_file(), LineConfig) or LineConfig()

    def _shape_text(self, text: str) -> str:
        prefix = self._config().message_prefix
        return f"{prefix}{text}" if prefix else text

    def push_text(self, to: str, text: str) -> Result:
        """Send a text message to a user/group/room ID via the push endpoint."""
        cfg = self._config()
        payload: Dict[str, Any] = {
            "to": to,
            "messages": [{"type": "text", "text": self._shape_text(text)}],
        }
        if cfg.notification_disabled:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/push",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def reply_text(self, reply_token: str, text: str) -> Result:
        """Reply within the 1-minute window using a reply token from the webhook payload."""
        cfg = self._config()
        payload: Dict[str, Any] = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": self._shape_text(text)}],
        }
        if cfg.notification_disabled:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/reply",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def multicast_text(self, to: List[str], text: str) -> Result:
        """Send the same message to up to 500 user IDs in one call."""
        cfg = self._config()
        payload: Dict[str, Any] = {
            "to": to,
            "messages": [{"type": "text", "text": self._shape_text(text)}],
        }
        if cfg.notification_disabled:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/multicast",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def broadcast_text(self, text: str) -> Result:
        """Send a message to every user that has the bot as a friend."""
        cfg = self._config()
        payload: Dict[str, Any] = {
            "messages": [{"type": "text", "text": self._shape_text(text)}],
        }
        if cfg.notification_disabled:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/broadcast",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def get_profile(self, user_id: str) -> Result:
        """Fetch a user's display name / picture URL by their LINE user ID."""
        return http_request(
            "GET",
            f"{LINE_API_BASE}/profile/{user_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def get_bot_info(self) -> Result:
        """Fetch the connected bot's own profile (userId, displayName, picture)."""
        return http_request(
            "GET",
            f"{LINE_API_BASE}/info",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def get_quota(self) -> Result:
        """Return the bot's monthly push-message quota."""
        return http_request(
            "GET",
            f"{LINE_API_BASE}/message/quota",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )
