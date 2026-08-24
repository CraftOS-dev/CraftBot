"""Lark (messaging) bridge provider — auth-layer port of ``LarkClient``.

Family member of ``_lark.LarkProviderBase`` (family="lark"): shares one
Custom App account (app_id identity) with lark_calendar / lark_drive.

Listener: the legacy client's lark-oapi persistent-connection WebSocket
loop (``supports_listening = True``) is reused verbatim via
``LegacyListenerAdapter`` — the WS authenticates with app_id/app_secret
from the bound credential, so no extra plumbing is needed.

verify_token adds the legacy ``LarkHandler.login()`` extra: a best-effort
``GET /bot/v3/info`` to capture ``bot_name``/``bot_open_id`` (the latter
is what the dispatch loop uses to drop the bot's own echoed messages).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ...helpers import request as http_request
from ...integrations._lark_common import LARK_API_BASE
from ...integrations.lark import LarkClient
from .._lark import LarkClientBinding, LarkProviderBase


class BoundLarkClient(LarkClientBinding, LarkClient):
    """LarkClient with per-account credential binding (see LarkClientBinding)."""


class LarkProvider(LarkProviderBase):
    id = "lark"
    display_name = "Lark"
    client_cls = BoundLarkClient
    has_listener = True  # lark-oapi WebSocket loop on the messaging client

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Family-base mint + the messaging-only bot-info fetch, mirroring
        the legacy handler: falls back gracefully if the bot capability
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
