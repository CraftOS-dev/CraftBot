"""Discord bridge provider — account-bound wrapper over its API client.

Bridge pattern (see stripe/provider.py and github/provider.py): ``DiscordClient`` keeps its entire API surface (bot
REST, user-account REST, gateway listener, lazy voice); only the
credential plumbing is overridden by a small binding mixin so the
credential is injected per account and never read from
``discord.json``. ``operations()`` is empty and ``guidance()`` blank —
the action functions remain the tool surface; account routing
happens centrally in the host adapter.

Discord is token-only (a bot token per Discord application):
``oauth_spec()`` raises NotImplementedError and there is no
``run_login``. Bot tokens do not expire → ``refresh()`` returns None.

One account = one bot application; identity is the bot's Discord user
id (snowflake) captured from ``GET /users/@me`` at verify time and
stored as ``bot_id`` — the field the connect flow captures.

The credential dataclass also carries an optional ``user_token`` (a
user-account token driving the ``user_*`` client methods). The ``fields`` only expose ``bot_token``, but ``verify_token``
passes an optional ``user_token`` through unverified so a credential
built with one keeps working — verification itself is bot-token-based,
as the connect flow does.

Known limitations (NOT refactored here):
* The listener filter config (``discord_config.json`` — mention_only +
  self/third-party allowlists) is loaded from a single global file
  inside ``_handle_message_create``, so every account shares one filter
  configuration. Listening itself is safe per-instance: all gateway
  state (_ws, _ws_task, _heartbeat_task, _last_sequence, _bot_user_id,
  _role_name_cache) lives on the client instance.
* Voice: ``_discord_voice.DiscordVoiceManager`` is cached per client
  instance (``self._voice_mgr``) and built from the bound bot token, so
  two accounts get two managers — but each manager starts a full
  discord.py bot gateway session in addition to the raw listen gateway,
  and the OpenAI TTS key comes from the process-global
  ``ConfigStore.extras``. Left as-is per the bridge scope.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from .client import (
    DISCORD_API_BASE,
    DiscordClient,
    DiscordConfig,
    DiscordCredential,
)
from .._shared import ClientListenerAdapter

_CRED_FIELDS = {f.name for f in fields(DiscordCredential)}


class DiscordClientBinding:
    """Overrides DiscordClient's disk plumbing: credential is injected per
    account. MRO puts this before the API client:

        class BoundDiscordClient(DiscordClientBinding, DiscordClient): pass

    No token refresh — Discord bot tokens are non-expiring — and the
    API client never writes the credential file outside handler.login,
    so ``_persist`` is never called (kept so the build_client contract is
    uniform across providers).
    """

    _cred: Optional[DiscordCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = DiscordCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> DiscordCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundDiscordClient(DiscordClientBinding, DiscordClient):
    """DiscordClient with per-account credential binding (see DiscordClientBinding)."""


class DiscordProvider:
    id = "discord"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "Discord"
    # ----- UI metadata -----
    description = "Community chat"
    icon = "discord"
    fields = [
        {
            "key": "bot_token",
            "label": "Bot Token",
            "placeholder": "Enter bot token",
            "password": True,
        },
    ]
    connect_help = [
        "Open Discord Developer Portal: discord.com/developers/applications",
        "Click 'New Application' and give it a name",
        "Open the 'Bot' tab in the left sidebar",
        "Click 'Reset Token' (or 'Copy' if it's already shown)",
        "Paste the bot token into the field below",
    ]
    config_class = DiscordConfig
    config_fields = [
        {
            "key": "mention_only",
            "label": "Only when @-mentioned",
            "type": "checkbox",
            "help": "When on, the bot only forwards messages where it's directly @-mentioned. When off, every message in every channel the bot can see is considered.",
        },
        {
            "key": "third_party_usernames",
            "label": "Third-party users",
            "type": "list",
            "placeholder": "alice, bob.s",
            "help": "Their messages reach the agent as external incoming messages. Comma-separated Discord usernames/display names, case-insensitive. Leave empty to skip this sub-check.",
        },
        {
            "key": "third_party_role_names",
            "label": "Third-party roles",
            "type": "list",
            "placeholder": "Member, Contributor",
            "help": "Same as Third-party users, but matched on Discord role names in the message's guild. DMs ignore this list. Leave empty to skip.",
        },
        {
            "key": "self_usernames",
            "label": "Self users",
            "type": "list",
            "placeholder": "ahmad",
            "help": "Their messages are treated as if you (the bot owner) sent them - used for trusted admins who can drive the bot like its owner. Self matches win over third-party matches. Leave empty to skip.",
        },
        {
            "key": "self_role_names",
            "label": "Self roles",
            "type": "list",
            "placeholder": "Admin, Owner",
            "help": "Same as Self users, but matched on role names. DMs ignore this list. Leave empty to skip. Note: if all four allow lists are empty, the filter is fully open and every message is treated as third-party (default).",
        },
    ]

    client_cls = BoundDiscordClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """The bot's Discord user id (snowflake, stored as ``bot_id``),
        stripped/lowercased. None for pre-bridge credentials saved before
        the id was captured and for junk shapes — never raises."""
        try:
            bot_id = credential.get("bot_id")
        except AttributeError:
            return None
        if isinstance(bot_id, str) and bot_id.strip():
            return bot_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        # Deliberate: no Discord OAuth2 flow — each account is a bot
        # application token pasted from the Developer Portal, exactly as
        # the connect flow works.
        raise NotImplementedError("discord is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # Discord bot tokens are non-expiring

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Token verification:
        ``GET /users/@me`` with the ``Bot`` token; same handler ``fields``
        key (``bot_token``). The bot's ``id``/``username`` are captured as
        ``bot_id``/``bot_username`` so ``identity_of`` resolves the
        account immediately.

        An optional ``user_token`` (the credential dataclass's second
        token, driving the ``user_*`` client methods) is passed through
        unverified — the connect flow does not verify it either.
        """
        token = (credentials.get("bot_token") or "").strip()
        if not token:
            return (
                False,
                "A Discord bot token is required. Create one at: "
                "https://discord.com/developers/applications",
                None,
            )
        user_token = (credentials.get("user_token") or "").strip()

        result = http_request(
            "GET",
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bot {token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Invalid Discord bot token: {result['error']}", None
        data = result.get("result") or {}

        credential = asdict(
            DiscordCredential(
                bot_token=token,
                user_token=user_token,
                bot_id=str(data.get("id") or ""),
                bot_username=data.get("username") or "",
            )
        )
        return (
            True,
            f"Discord bot connected: {data.get('username')} ({data.get('id')})",
            credential,
        )

    def operations(self) -> List[Operation]:
        return []  # bridge provider — Discord actions stay in place

    def guidance(self) -> str:
        return ""  # bridge provider — the action surface has its own docs

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> ClientListenerAdapter:
        """Gateway listener — the API client's own websocket loop
        (Discord Gateway v10: identify with the bot token, heartbeat,
        MESSAGE_CREATE → PlatformMessage), reused verbatim via the generic
        adapter. All gateway state is per-instance so two accounts can
        listen concurrently; the shared piece is the global
        ``discord_config.json`` filter config (see module docstring). No
        restart-safe cursor, the poll loop keeps its watermark in memory."""
        return ClientListenerAdapter(client, emit)
