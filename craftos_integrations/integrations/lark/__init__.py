# -*- coding: utf-8 -*-
"""Lark integration - bidirectional messaging.

Lark is ByteDance's enterprise messaging platform (the China-region twin
``Feishu`` shares the API; the only difference is the API host). This
integration targets **global Lark** (``open.larksuite.com``) with a
custom-app, tenant-access-token auth flow.

Sending: REST via ``/im/v1/messages`` with an auto-refreshing
``tenant_access_token`` (2-hour TTL, refreshed within 60s of expiry).

Receiving: persistent-connection WebSocket via the official ``lark-oapi``
SDK. The SDK's blocking ``Client.start()`` runs on a daemon thread and
events are dispatched back to the agent's asyncio loop via
``run_coroutine_threadsafe``. Auto-reconnect is delegated to the SDK.

Setup gotcha worth knowing up-front: events do **not** flow until the
app version is approved by the tenant admin. The WS will connect and
authenticate (no errors) but messages won't arrive until approval lands.

Auth flow:
  1. User creates a Custom App at ``open.larksuite.com/app``.
  2. Adds the Bot feature, subscribes to ``im.message.receive_v1``, picks
     'Receive callbacks through persistent connection' as subscription mode.
  3. Enables permissions: ``im:message``, ``im:message.p2p_msg``,
     ``im:message.group_at_msg:readonly``.
  4. Submits a version for tenant admin approval.
  5. Grabs App ID + App Secret from Credentials & Basic Info.
  6. CraftBot mints a ``tenant_access_token`` via the
     ``/open-apis/auth/v3/tenant_access_token/internal`` endpoint and
     refreshes it before the 2-hour expiry on every send.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    PlatformMessage,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._lark_common import (
    LARK_API_BASE,
    LarkCredential,
    make_headers,
    validate_and_mint_token,
)

logger = get_logger(__name__)


LARK = IntegrationSpec(
    name="lark",
    cred_class=LarkCredential,
    cred_file="lark.json",
    platform_id="lark",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(LARK.name)
class LarkHandler(IntegrationHandler):
    spec = LARK
    display_name = "Lark"
    description = "Two-way messaging via Lark (send + receive)"
    auth_type = "token"
    icon = "lark"
    connect_help = [
        "Open Lark Developer Console: open.larksuite.com/app and sign in",
        "Create Custom App â†’ give it a name",
        "Add Features (left sidebar) â†’ Bot â†’ Add",
        "Events & Callbacks â†’ Event Configuration â†’ Subscription Mode: select 'Receive callbacks through persistent connection'",
        "Events & Callbacks â†’ Event Configuration â†’ Add Event: subscribe to 'im.message.receive_v1' (Receive Message) - without this, no DMs reach CraftBot",
        "Events & Callbacks â†’ Encryption Strategy: leave Encryption Key empty (this integration does not yet support encrypted events)",
        "Permissions & Scopes â†’ enable: im:message, im:message.p2p_msg, im:message.group_at_msg:readonly (the last is for group @-mentions and only appears after Bot is added)",
        "Version Management â†’ Create Version â†’ submit for tenant admin approval - events do NOT flow until the version is Released",
        "Credentials & Basic Info â†’ copy App ID + App Secret and paste them below",
    ]
    fields = [
        {
            "key": "app_id",
            "label": "App ID",
            "placeholder": "cli_xxxxxxxxxx",
            "password": False,
        },
        {
            "key": "app_secret",
            "label": "App Secret",
            "placeholder": "From Credentials tab",
            "password": True,
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, (
                "Usage: /lark login <app_id> <app_secret>\n"
                "Get from open.larksuite.com/app â†’ your app â†’ Credentials tab."
            )
        app_id, app_secret = args[0], args[1]

        token, token_expires_at, err = validate_and_mint_token(app_id, app_secret)
        if err:
            return False, err

        # Best-effort: fetch bot info so we can show the bot name in status().
        # Falls back gracefully if the call fails (e.g. bot capability not
        # enabled yet on the app).
        bot_name = ""
        bot_open_id = ""
        info = http_request(
            "GET",
            f"{LARK_API_BASE}/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" not in info:
            bot = info.get("result", {}).get("bot", {})
            bot_name = bot.get("app_name", "")
            bot_open_id = bot.get("open_id", "")

        save_credential(
            self.spec.cred_file,
            LarkCredential(
                app_id=app_id,
                app_secret=app_secret,
                bot_name=bot_name,
                bot_open_id=bot_open_id,
                tenant_access_token=token,
                token_expires_at=token_expires_at,
            ),
        )
        label = bot_name or app_id
        return True, f"Lark connected: {label}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Lark credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Lark credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Lark: Not connected"
        cred = load_credential(self.spec.cred_file, LarkCredential)
        if not cred:
            return True, "Lark: Connected\n  - app configured"
        name = cred.bot_name or "Lark bot"
        ident = cred.bot_open_id or cred.app_id or "app"
        return True, f"Lark: Connected\n  - {name} ({ident})"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class LarkClient(BasePlatformClient):
    spec = LARK
    PLATFORM_ID = LARK.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[LarkCredential] = None
        # WebSocket listener state. ``_ws_client`` is the lark_oapi.ws.Client
        # instance; ``_ws_thread`` is the daemon thread it runs in (the SDK's
        # ``start()`` is blocking so we can't await it). ``_dispatch_loop``
        # captures the agent's asyncio loop at start_listening time so the
        # synchronous WS-thread handler can ``run_coroutine_threadsafe`` back
        # onto the right loop when forwarding messages to the agent.
        self._ws_client: Optional[Any] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._dispatch_loop: Optional[asyncio.AbstractEventLoop] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> LarkCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, LarkCredential)
        if self._cred is None:
            raise RuntimeError("No Lark credentials. Use /lark login first.")
        return self._cred

    def _headers(self) -> Dict[str, str]:
        return make_headers(self._load(), self.spec.cred_file)

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        # Default to open_id for the receive_id type - covers DM-to-user case.
        # Callers that need group/email/user_id can use ``send_text`` directly.
        receive_id_type = kwargs.get("receive_id_type", "open_id")
        return self.send_text(recipient, text, receive_id_type=receive_id_type)

    @property
    def supports_listening(self) -> bool:
        return True

    # ----- Listener (WebSocket via lark_oapi SDK) -----

    async def start_listening(self, callback) -> None:
        """Open a Long-Connection WebSocket to Lark and forward messages.

        Uses ``lark_oapi.ws.Client`` which is the official SDK from ByteDance.
        The SDK's ``start()`` is blocking + synchronous, so we run it on a
        daemon thread and dispatch events back to the agent's asyncio loop
        via ``run_coroutine_threadsafe``.

        Auto-reconnect is enabled in the SDK - we don't need our own retry
        loop. If the network drops, the SDK reconnects with backoff.
        """
        if self._listening:
            return
        try:
            import lark_oapi as lark
        except ImportError:
            raise RuntimeError("lark-oapi not installed. Run: pip install lark-oapi")

        cred = self._load()
        self._message_callback = callback
        self._dispatch_loop = asyncio.get_running_loop()

        def _on_message(event: Any) -> None:
            """Synchronous handler running on the SDK's WS thread."""
            logger.info(f"[LARK] WS event received: {type(event).__name__}")
            try:
                msg = event.event.message
                sender = event.event.sender
            except AttributeError as e:
                logger.warning(f"[LARK] unexpected event shape: {e}")
                return
            # Bounce back onto the agent's loop for the actual dispatch
            loop = self._dispatch_loop
            if loop and not loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self._dispatch_message(msg, sender),
                    loop,
                )

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_message)
            .build()
        )
        self._ws_client = lark.ws.Client(
            cred.app_id,
            cred.app_secret,
            event_handler=handler,
            domain="https://open.larksuite.com",
            auto_reconnect=True,
            log_level=lark.LogLevel.INFO,
        )

        def _run_ws() -> None:
            try:
                self._ws_client.start()
            except Exception as e:
                logger.error(f"[LARK] WS client crashed: {e}")

        self._ws_thread = threading.Thread(
            target=_run_ws,
            name="lark-ws",
            daemon=True,
        )
        self._ws_thread.start()
        self._listening = True
        logger.info("[LARK] Started WebSocket listener")

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        # The SDK doesn't expose a clean ``stop()`` - the WS thread is a
        # daemon, so it dies when the agent process exits. For mid-run
        # disconnect (logout) we drop our reference; the SDK's reconnect
        # loop will keep running but no callback will fire (because
        # ``_dispatch_loop`` is gone after this method).
        self._ws_client = None
        self._ws_thread = None
        self._dispatch_loop = None
        logger.info("[LARK] Stopped WebSocket listener")

    async def _dispatch_message(self, msg: Any, sender: Any) -> None:
        """Convert a Lark P2ImMessageReceiveV1 event into a PlatformMessage."""
        if not self._listening or not self._message_callback:
            return

        # Skip messages sent by the bot itself (Lark echoes our sends back).
        cred = self._cred
        bot_open_id = cred.bot_open_id if cred else ""
        sender_id = getattr(sender, "sender_id", None)
        sender_open_id = getattr(sender_id, "open_id", "") if sender_id else ""
        if bot_open_id and sender_open_id == bot_open_id:
            return

        # Lark message ``content`` is a JSON-encoded string. Text messages:
        # ``{"text": "Hello"}``. Other types (post/image/file) we surface as
        # the raw JSON for now - agent decides what to do with them.
        msg_type = getattr(msg, "message_type", "") or ""
        raw_content = getattr(msg, "content", "") or ""
        text = ""
        try:
            parsed = json.loads(raw_content) if raw_content else {}
            if msg_type == "text":
                text = parsed.get("text", "")
            else:
                text = raw_content  # surface raw JSON for non-text types
        except (json.JSONDecodeError, ValueError):
            text = raw_content

        if not text:
            return

        ts: Optional[datetime] = None
        try:
            create_time = getattr(msg, "create_time", None)
            if create_time:
                # Lark's create_time is millis since epoch as a string
                ts = datetime.fromtimestamp(int(create_time) / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError):
            pass

        chat_id = getattr(msg, "chat_id", "") or ""
        message_id = getattr(msg, "message_id", "") or ""
        chat_type = getattr(msg, "chat_type", "") or ""

        await self._message_callback(
            PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=sender_open_id or "unknown",
                sender_name=sender_open_id or "Lark user",
                text=text,
                channel_id=chat_id,
                channel_name=f"Lark {chat_type}" if chat_type else "Lark",
                message_id=message_id,
                timestamp=ts,
                raw={
                    "source": "Lark",
                    "integrationType": "lark",
                    "is_self_message": False,
                    "is_group": chat_type == "group",
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "message_type": msg_type,
                    "raw_content": raw_content,
                },
            )
        )

    # ----- REST methods -----

    def send_text(
        self, receive_id: str, text: str, receive_id_type: str = "open_id"
    ) -> Result:
        """Send a text message.

        ``receive_id_type`` selects how Lark interprets ``receive_id``:
          - ``open_id`` - a user's open_id (default, returned by user lookup)
          - ``user_id`` - Lark's enterprise user_id
          - ``email`` - the user's company email
          - ``chat_id`` - a group chat id (oc_...)
          - ``union_id`` - cross-app stable id

        Lark's API quirk: the ``content`` field must be a JSON-encoded
        STRING, not an object. Hence the literal ``\"`` escaping below.
        """
        import json as _json

        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": _json.dumps({"text": text}, ensure_ascii=False),
        }
        return http_request(
            "POST",
            f"{LARK_API_BASE}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def reply_text(self, message_id: str, text: str) -> Result:
        """Threaded reply to an existing message id (om_...)."""
        import json as _json

        return http_request(
            "POST",
            f"{LARK_API_BASE}/im/v1/messages/{message_id}/reply",
            headers=self._headers(),
            json={
                "msg_type": "text",
                "content": _json.dumps({"text": text}, ensure_ascii=False),
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_user_by_email(self, email: str) -> Result:
        """Resolve a user's open_id from a company email.

        Uses Lark's batch-get endpoint with a single email; convenient
        for "send a message to alice@company.com" workflows where the
        caller doesn't know the open_id."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/contact/v3/users/batch_get_id",
            params={"user_id_type": "open_id"},
            headers=self._headers(),
            json={"emails": [email]},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_chats(self, page_size: int = 50) -> Result:
        """List groups the bot is a member of."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/im/v1/chats",
            params={"page_size": min(page_size, 100)},
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_bot_info(self) -> Result:
        """Connected bot's own profile (app_name, open_id, etc.)."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bot/v3/info",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("bot", d),
        )

    # ==================================================================
    # Messages — extended lifecycle / content / reactions / pins
    # ==================================================================

    @staticmethod
    def _msg_content(msg_type: str, body: Dict[str, Any]) -> str:
        """Lark's content field is always a JSON-encoded STRING (not an object)."""
        import json as _json
        return _json.dumps(body, ensure_ascii=False)

    def send_message(self, receive_id: str, msg_type: str,
                     content: Dict[str, Any],
                     receive_id_type: str = "open_id",
                     uuid: Optional[str] = None) -> Result:
        """Generic send. msg_type: text | post | image | file | audio | media | sticker | interactive | share_chat | share_user. content is the per-type dict (this method JSON-encodes it)."""
        import json as _json
        payload: Dict[str, Any] = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": _json.dumps(content, ensure_ascii=False),
        }
        if uuid: payload["uuid"] = uuid
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def send_image_message(self, receive_id: str, image_key: str,
                           receive_id_type: str = "open_id") -> Result:
        return self.send_message(receive_id, "image", {"image_key": image_key},
                                 receive_id_type=receive_id_type)

    def send_file_message(self, receive_id: str, file_key: str,
                          receive_id_type: str = "open_id") -> Result:
        return self.send_message(receive_id, "file", {"file_key": file_key},
                                 receive_id_type=receive_id_type)

    def send_card_message(self, receive_id: str, card: Dict[str, Any],
                          receive_id_type: str = "open_id") -> Result:
        """card is a Lark interactive-card JSON schema."""
        return self.send_message(receive_id, "interactive", card,
                                 receive_id_type=receive_id_type)

    def send_post_message(self, receive_id: str, post: Dict[str, Any],
                          receive_id_type: str = "open_id") -> Result:
        """post is Lark's rich-text 'post' format: {zh_cn: {title, content: [[{tag,text/...}]]}}."""
        return self.send_message(receive_id, "post", post,
                                 receive_id_type=receive_id_type)

    def reply_message(self, message_id: str, msg_type: str,
                      content: Dict[str, Any],
                      reply_in_thread: bool = False) -> Result:
        """Reply to message_id. reply_in_thread starts a thread off the parent."""
        import json as _json
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/messages/{message_id}/reply",
            headers=self._headers(),
            json={"msg_type": msg_type,
                  "content": _json.dumps(content, ensure_ascii=False),
                  "reply_in_thread": reply_in_thread},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_message(self, message_id: str) -> Result:
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/messages/{message_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_message(self, message_id: str) -> Result:
        """Recall a message the bot sent (within Lark's recall window)."""
        return http_request(
            "DELETE", f"{LARK_API_BASE}/im/v1/messages/{message_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", {"recalled": True, "message_id": message_id}),
        )

    def update_message(self, message_id: str, msg_type: str,
                       content: Dict[str, Any]) -> Result:
        """Edit text/interactive content of a bot-sent message."""
        import json as _json
        return http_request(
            "PUT", f"{LARK_API_BASE}/im/v1/messages/{message_id}",
            headers=self._headers(),
            json={"msg_type": msg_type,
                  "content": _json.dumps(content, ensure_ascii=False)},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def forward_message(self, message_id: str, receive_id: str,
                        receive_id_type: str = "open_id",
                        uuid: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {"receive_id": receive_id}
        if uuid: payload["uuid"] = uuid
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/messages/{message_id}/forward",
            params={"receive_id_type": receive_id_type},
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_messages(self, container_id: str,
                      container_id_type: str = "chat",
                      start_time: Optional[str] = None,
                      end_time: Optional[str] = None,
                      sort_type: str = "ByCreateTimeAsc",
                      page_size: int = 50,
                      page_token: str = "") -> Result:
        """List a chat's message history. start_time/end_time are unix-seconds strings."""
        params: Dict[str, str] = {
            "container_id": container_id,
            "container_id_type": container_id_type,
            "sort_type": sort_type,
            "page_size": str(min(page_size, 50)),
        }
        if start_time: params["start_time"] = start_time
        if end_time: params["end_time"] = end_time
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/messages",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_message_read_users(self, message_id: str,
                                user_id_type: str = "open_id",
                                page_size: int = 100,
                                page_token: str = "") -> Result:
        """Who has read a message. Returns user identifiers + read_time."""
        params: Dict[str, str] = {
            "user_id_type": user_id_type,
            "page_size": str(min(page_size, 100)),
        }
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/messages/{message_id}/read_users",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def add_reaction(self, message_id: str, emoji_type: str) -> Result:
        """emoji_type is Lark's emoji code, e.g. 'SMILE' / 'HAPPY' / 'THUMBSUP'. See Lark emoji reference."""
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/messages/{message_id}/reactions",
            headers=self._headers(),
            json={"reaction_type": {"emoji_type": emoji_type}}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def remove_reaction(self, message_id: str, reaction_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/im/v1/messages/{message_id}/reactions/{reaction_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", {"removed": True, "reaction_id": reaction_id}),
        )

    def list_reactions(self, message_id: str,
                       emoji_type: Optional[str] = None,
                       page_size: int = 100,
                       page_token: str = "",
                       user_id_type: str = "open_id") -> Result:
        params: Dict[str, str] = {
            "user_id_type": user_id_type,
            "page_size": str(min(page_size, 100)),
        }
        if emoji_type: params["reaction_type"] = emoji_type
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/messages/{message_id}/reactions",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def pin_message(self, message_id: str) -> Result:
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/pins",
            headers=self._headers(),
            json={"message_id": message_id}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def unpin_message(self, message_id: str) -> Result:
        return http_request(
            "DELETE", f"{LARK_API_BASE}/im/v1/pins/{message_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", {"unpinned": True, "message_id": message_id}),
        )

    def list_pinned_messages(self, chat_id: str,
                             page_size: int = 50,
                             page_token: str = "") -> Result:
        params: Dict[str, str] = {
            "chat_id": chat_id,
            "page_size": str(min(page_size, 50)),
        }
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/pins",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def send_urgent(self, message_id: str, user_id_list: List[str],
                    urgent_type: str = "app",
                    user_id_type: str = "open_id") -> Result:
        """urgent_type: app | sms | phone (escalation level). Most useful when a message needs immediate attention."""
        endpoint_map = {"app": "urgent_app", "sms": "urgent_sms", "phone": "urgent_phone"}
        sub = endpoint_map.get(urgent_type, "urgent_app")
        return http_request(
            "PATCH", f"{LARK_API_BASE}/im/v1/messages/{message_id}/{sub}",
            headers=self._headers(),
            params={"user_id_type": user_id_type},
            json={"user_id_list": user_id_list}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_send_message(self, msg_type: str, content: Dict[str, Any],
                           open_ids: Optional[List[str]] = None,
                           user_ids: Optional[List[str]] = None,
                           department_ids: Optional[List[str]] = None) -> Result:
        """Send the same message to many recipients (departments/users/openids) at once."""
        import json as _json
        payload: Dict[str, Any] = {
            "msg_type": msg_type,
            "content": _json.dumps(content, ensure_ascii=False),
        }
        if open_ids: payload["open_ids"] = open_ids
        if user_ids: payload["user_ids"] = user_ids
        if department_ids: payload["department_ids"] = department_ids
        return http_request(
            "POST", f"{LARK_API_BASE}/message/v4/batch_send/",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- IM resources (file/image upload + download) -----

    def upload_image(self, file_path: str,
                     image_type: str = "message") -> Result:
        """image_type: message | avatar. Returns image_key for use in send_image_message."""
        import os
        token = self._headers()["Authorization"]
        try:
            with open(file_path, "rb") as f:
                file_data = f.read()
            return http_request(
                "POST", f"{LARK_API_BASE}/im/v1/images",
                headers={"Authorization": token},
                data={"image_type": image_type},
                files={"image": (os.path.basename(file_path), file_data)},
                expected=(200,),
                transform=lambda d: d.get("data", d),
            )
        except OSError as e:
            return {"error": f"Failed to read {file_path}: {e}"}

    def upload_im_file(self, file_path: str, file_type: str = "stream",
                       file_name: Optional[str] = None,
                       duration: Optional[int] = None) -> Result:
        """file_type: opus | mp4 | pdf | doc | xls | ppt | stream. Returns file_key for send_file_message."""
        import os
        if not file_name:
            file_name = os.path.basename(file_path)
        token = self._headers()["Authorization"]
        try:
            with open(file_path, "rb") as f:
                file_data = f.read()
            form: Dict[str, Any] = {"file_type": file_type, "file_name": file_name}
            if duration is not None:
                form["duration"] = str(duration)
            return http_request(
                "POST", f"{LARK_API_BASE}/im/v1/files",
                headers={"Authorization": token},
                data=form,
                files={"file": (file_name, file_data)},
                expected=(200,),
                transform=lambda d: d.get("data", d),
            )
        except OSError as e:
            return {"error": f"Failed to read {file_path}: {e}"}

    def download_message_resource(self, message_id: str, file_key: str,
                                  dest_path: str,
                                  resource_type: str = "file") -> Result:
        """Download an attached image/file/audio from a message. resource_type: image | file (covers audio/video)."""
        import httpx
        token = self._headers()["Authorization"]
        try:
            with httpx.stream(
                "GET",
                f"{LARK_API_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
                headers={"Authorization": token},
                params={"type": resource_type},
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    return {"error": f"Download failed: HTTP {resp.status_code}",
                            "details": resp.read().decode("utf-8", errors="replace")[:500]}
                bytes_written = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
                        bytes_written += len(chunk)
                return {"ok": True, "result": {"path": dest_path,
                                                "bytes_written": bytes_written}}
        except (httpx.HTTPError, OSError) as e:
            return {"error": f"Download failed: {e}"}

    # ==================================================================
    # Chats — CRUD + members + announcement + search
    # ==================================================================

    def create_chat(self, name: str,
                    description: str = "",
                    owner_id: Optional[str] = None,
                    user_id_list: Optional[List[str]] = None,
                    bot_id_list: Optional[List[str]] = None,
                    chat_mode: str = "group",
                    chat_type: str = "private",
                    user_id_type: str = "open_id") -> Result:
        """chat_mode: group | topic. chat_type: public | private."""
        payload: Dict[str, Any] = {
            "name": name,
            "description": description,
            "chat_mode": chat_mode,
            "chat_type": chat_type,
        }
        if owner_id: payload["owner_id"] = owner_id
        if user_id_list: payload["user_id_list"] = user_id_list
        if bot_id_list: payload["bot_id_list"] = bot_id_list
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/chats",
            params={"user_id_type": user_id_type},
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_chat(self, chat_id: str,
                 user_id_type: str = "open_id") -> Result:
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/chats/{chat_id}",
            params={"user_id_type": user_id_type},
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_chat(self, chat_id: str,
                    name: Optional[str] = None,
                    description: Optional[str] = None,
                    avatar: Optional[str] = None,
                    add_member_permission: Optional[str] = None,
                    share_card_permission: Optional[str] = None,
                    at_all_permission: Optional[str] = None,
                    edit_permission: Optional[str] = None,
                    chat_type: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None: payload["name"] = name
        if description is not None: payload["description"] = description
        if avatar is not None: payload["avatar"] = avatar
        if add_member_permission is not None: payload["add_member_permission"] = add_member_permission
        if share_card_permission is not None: payload["share_card_permission"] = share_card_permission
        if at_all_permission is not None: payload["at_all_permission"] = at_all_permission
        if edit_permission is not None: payload["edit_permission"] = edit_permission
        if chat_type is not None: payload["chat_type"] = chat_type
        return http_request(
            "PUT", f"{LARK_API_BASE}/im/v1/chats/{chat_id}",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def dissolve_chat(self, chat_id: str) -> Result:
        return http_request(
            "DELETE", f"{LARK_API_BASE}/im/v1/chats/{chat_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", {"dissolved": True, "chat_id": chat_id}),
        )

    def list_chat_members(self, chat_id: str,
                          member_id_type: str = "open_id",
                          page_size: int = 100,
                          page_token: str = "") -> Result:
        params: Dict[str, str] = {
            "member_id_type": member_id_type,
            "page_size": str(min(page_size, 100)),
        }
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/chats/{chat_id}/members",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def add_chat_members(self, chat_id: str, id_list: List[str],
                         member_id_type: str = "open_id",
                         succeed_type: int = 0) -> Result:
        """succeed_type: 0 (return error if any fails) | 1 (partial-success allowed) | 2 (return existing-member info)."""
        return http_request(
            "POST", f"{LARK_API_BASE}/im/v1/chats/{chat_id}/members",
            params={"member_id_type": member_id_type, "succeed_type": str(succeed_type)},
            headers=self._headers(),
            json={"id_list": id_list}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def remove_chat_members(self, chat_id: str, id_list: List[str],
                            member_id_type: str = "open_id") -> Result:
        return http_request(
            "DELETE", f"{LARK_API_BASE}/im/v1/chats/{chat_id}/members",
            params={"member_id_type": member_id_type},
            headers=self._headers(),
            json={"id_list": id_list}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def search_chats(self, query: str, page_size: int = 50,
                     page_token: str = "") -> Result:
        params: Dict[str, str] = {
            "query": query,
            "page_size": str(min(page_size, 100)),
        }
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/chats/search",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_chat_announcement(self, chat_id: str) -> Result:
        return http_request(
            "GET", f"{LARK_API_BASE}/im/v1/chats/{chat_id}/announcement",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_chat_announcement(self, chat_id: str, revision: str,
                                 requests: List[Dict[str, Any]]) -> Result:
        """requests is a list of Lark block update operations (same shape as Docx)."""
        return http_request(
            "PATCH", f"{LARK_API_BASE}/im/v1/chats/{chat_id}/announcement",
            headers=self._headers(),
            json={"revision": revision, "requests": requests}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_chat_moderation(self, chat_id: str,
                               moderation_setting: str,
                               user_id_list: Optional[List[str]] = None,
                               user_id_type: str = "open_id") -> Result:
        """moderation_setting: all_members | only_owner | specific_users."""
        payload: Dict[str, Any] = {"moderation_setting": moderation_setting}
        if user_id_list is not None: payload["user_id_list"] = user_id_list
        return http_request(
            "PUT", f"{LARK_API_BASE}/im/v1/chats/{chat_id}/moderation",
            params={"user_id_type": user_id_type},
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ==================================================================
    # Contacts — users / departments
    # ==================================================================

    def get_user(self, user_id: str,
                 user_id_type: str = "open_id",
                 department_id_type: str = "open_department_id") -> Result:
        return http_request(
            "GET", f"{LARK_API_BASE}/contact/v3/users/{user_id}",
            params={"user_id_type": user_id_type,
                    "department_id_type": department_id_type},
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_get_users(self, user_ids: List[str],
                        user_id_type: str = "open_id") -> Result:
        return http_request(
            "GET", f"{LARK_API_BASE}/contact/v3/users/batch",
            params=[("user_id_type", user_id_type)] + [("user_ids", uid) for uid in user_ids],
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_get_user_ids(self,
                           emails: Optional[List[str]] = None,
                           mobiles: Optional[List[str]] = None,
                           user_id_type: str = "open_id") -> Result:
        """Resolve a batch of emails/mobiles to user IDs (extension of get_user_by_email)."""
        payload: Dict[str, Any] = {}
        if emails: payload["emails"] = emails
        if mobiles: payload["mobiles"] = mobiles
        return http_request(
            "POST", f"{LARK_API_BASE}/contact/v3/users/batch_get_id",
            params={"user_id_type": user_id_type},
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_department_users(self, department_id: str,
                              user_id_type: str = "open_id",
                              department_id_type: str = "open_department_id",
                              page_size: int = 50,
                              page_token: str = "") -> Result:
        params: Dict[str, str] = {
            "department_id": department_id,
            "user_id_type": user_id_type,
            "department_id_type": department_id_type,
            "page_size": str(min(page_size, 50)),
        }
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/contact/v3/users/find_by_department",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def search_users_by_name(self, query: str,
                             page_size: int = 50,
                             page_token: str = "") -> Result:
        """User search visible to the app (depends on scope grants)."""
        params: Dict[str, str] = {"query": query, "page_size": str(min(page_size, 50))}
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/contact/v3/users/search",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_department(self, department_id: str,
                       department_id_type: str = "open_department_id",
                       user_id_type: str = "open_id") -> Result:
        return http_request(
            "GET", f"{LARK_API_BASE}/contact/v3/departments/{department_id}",
            params={"department_id_type": department_id_type,
                    "user_id_type": user_id_type},
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_department_children(self, parent_department_id: str,
                                 department_id_type: str = "open_department_id",
                                 fetch_child: bool = False,
                                 page_size: int = 50,
                                 page_token: str = "") -> Result:
        params: Dict[str, str] = {
            "parent_department_id": parent_department_id,
            "department_id_type": department_id_type,
            "fetch_child": str(fetch_child).lower(),
            "page_size": str(min(page_size, 50)),
        }
        if page_token: params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/contact/v3/departments/children",
            headers=self._headers(), params=params, expected=(200,),
            transform=lambda d: d.get("data", d),
        )
