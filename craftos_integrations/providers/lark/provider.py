"""Lark (messaging) bridge provider — account-bound wrapper over ``LarkClient``.

Family member of ``_lark.LarkProviderBase`` (family="lark"): shares one
Custom App account (app_id identity) with lark_calendar / lark_drive.

Listener: the API client's lark-oapi persistent-connection WebSocket
loop (``supports_listening = True``) is reused verbatim via
``ClientListenerAdapter`` — the WS authenticates with app_id/app_secret
from the bound credential, so no extra plumbing is needed.

verify_token adds one extra: a best-effort
``GET /bot/v3/info`` to capture ``bot_name``/``bot_open_id`` (the latter
is what the dispatch loop uses to drop the bot's own echoed messages).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ...helpers import request as http_request
from .._lark_common import LARK_API_BASE
from .client import LarkClient
from .._lark import LarkClientBinding, LarkProviderBase


class BoundLarkClient(LarkClientBinding, LarkClient):
    """LarkClient with per-account credential binding (see LarkClientBinding)."""


class LarkProvider(LarkProviderBase):
    id = "lark"
    display_name = "Lark"
    # ----- UI metadata -----
    description = "Two-way messaging via Lark (send + receive)"
    icon = "lark"
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
    connect_help = [
        "Open Lark Developer Console: open.larksuite.com/app and sign in",
        "Create Custom App → give it a name",
        "Add Features (left sidebar) → Bot → Add",
        "Events & Callbacks → Event Configuration → Subscription Mode: select 'Receive callbacks through persistent connection'",
        "Events & Callbacks → Event Configuration → Add Event: subscribe to 'im.message.receive_v1' (Receive Message) - without this, no DMs reach CraftBot",
        "Events & Callbacks → Encryption Strategy: leave Encryption Key empty (this integration does not yet support encrypted events)",
        "Permissions & Scopes → enable: im:message, im:message.p2p_msg, im:message.group_at_msg:readonly (the last is for group @-mentions and only appears after Bot is added)",
        "Version Management → Create Version → submit for tenant admin approval - events do NOT flow until the version is Released",
        "Credentials & Basic Info → copy App ID + App Secret and paste them below",
    ]

    client_cls = BoundLarkClient
    has_listener = True  # lark-oapi WebSocket loop on the messaging client

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Family-base mint + the messaging-only bot-info fetch, mirroring
        the connect flow: falls back gracefully if the bot capability
        isn't enabled yet on the app."""
        ok, msg, credential = super().verify_token(credentials)
        if not ok or credential is None:
            return ok, msg, credential

        bot_name = ""
        bot_open_id = ""
        info = http_request(
            "GET",
            f"{LARK_API_BASE}/bot/v3/info",
            headers={"Authorization": f"Bearer {credential['tenant_access_token']}"},
            expected=(200,),
        )
        if "error" not in info:
            bot = info.get("result", {}).get("bot", {})
            bot_name = bot.get("app_name", "")
            bot_open_id = bot.get("open_id", "")
        credential["bot_name"] = bot_name
        credential["bot_open_id"] = bot_open_id

        label = bot_name or credential["app_id"]
        return True, f"Lark connected: {label}", credential
