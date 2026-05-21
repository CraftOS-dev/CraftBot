# -*- coding: utf-8 -*-
"""Discord integration - bot + user account + voice (lazy)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as _url_quote

import httpx

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
from ...helpers import Result, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
GATEWAY_INTENTS = (1 << 9) | (1 << 12) | (1 << 15)  # 37376


@dataclass
class DiscordCredential:
    bot_token: str = ""
    user_token: str = ""
    bot_id: str = ""
    bot_username: str = ""


@dataclass
class DiscordConfig:
    """Runtime knobs persisted to ``discord_config.json``.

    Two-tier permission model:

    * **Third-party** lists - users/roles whose messages reach the agent as
      incoming external chatter (``raw.is_self_message = False``). Use for
      letting a server's general members @-the-bot for help.
    * **Self** lists - users/roles whose messages reach the agent as if the
      bot owner sent them (``raw.is_self_message = True``). Use for trusted
      admins who can drive the bot like its owner - issue commands, change
      settings, etc.

    Filter behaviour:

    * If ``mention_only`` is set, the bot must be @-mentioned regardless of
      the lists below.
    * Self matches always win over third-party matches.
    * If **all four** allow lists are empty, the filter is fully open and
      every message is classified as third-party (current default).
    * If any list has entries, users matching neither list are dropped.
    """
    # When True, the bot only forwards messages where it was @-mentioned.
    # Default False = the bot processes every message it can see in any
    # channel/guild it's a member of.
    mention_only: bool = False

    # ----- Third-party allowlist (forwarded as external messages) -----
    # Comma-separated Discord usernames / display names. Matched
    # case-insensitively against both ``author.username`` and
    # ``author.global_name``. Empty = skip this sub-check.
    third_party_usernames: List[str] = field(default_factory=list)
    # Comma-separated guild role names. Resolved against the guild's role
    # list (cached 10 min per guild). Empty = skip this sub-check.
    # No effect on DMs (no guild context).
    third_party_role_names: List[str] = field(default_factory=list)

    # ----- Self allowlist (forwarded as if the bot owner sent them) -----
    # Same matching semantics as the third-party fields above.
    self_usernames: List[str] = field(default_factory=list)
    self_role_names: List[str] = field(default_factory=list)


DISCORD = IntegrationSpec(
    name="discord",
    cred_class=DiscordCredential,
    cred_file="discord.json",
    platform_id="discord",
)


def _discord_config_file() -> str:
    """``discord.json`` â†’ ``discord_config.json``."""
    stem = DISCORD.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------

@register_handler(DISCORD.name)
class DiscordHandler(IntegrationHandler):
    spec = DISCORD
    display_name = "Discord"
    description = "Community chat"
    auth_type = "token"
    icon = "discord"
    connect_help = [
        "Open Discord Developer Portal: discord.com/developers/applications",
        "Click 'New Application' and give it a name",
        "Open the 'Bot' tab in the left sidebar",
        "Click 'Reset Token' (or 'Copy' if it's already shown)",
        "Paste the bot token into the field below",
    ]
    fields = [
        {"key": "bot_token", "label": "Bot Token", "placeholder": "Enter bot token", "password": True},
    ]

    config_class = DiscordConfig
    config_fields = [
        {"key": "mention_only", "label": "Only when @-mentioned", "type": "checkbox",
         "help": "When on, the bot only forwards messages where it's directly @-mentioned. "
                 "When off, every message in every channel the bot can see is considered."},
        {"key": "third_party_usernames", "label": "Third-party users", "type": "list",
         "placeholder": "alice, bob.s",
         "help": "Their messages reach the agent as external incoming messages. "
                 "Comma-separated Discord usernames/display names, case-insensitive. "
                 "Leave empty to skip this sub-check."},
        {"key": "third_party_role_names", "label": "Third-party roles", "type": "list",
         "placeholder": "Member, Contributor",
         "help": "Same as Third-party users, but matched on Discord role names in the "
                 "message's guild. DMs ignore this list. Leave empty to skip."},
        {"key": "self_usernames", "label": "Self users", "type": "list",
         "placeholder": "ahmad",
         "help": "Their messages are treated as if you (the bot owner) sent them - used "
                 "for trusted admins who can drive the bot like its owner. Self matches "
                 "win over third-party matches. Leave empty to skip."},
        {"key": "self_role_names", "label": "Self roles", "type": "list",
         "placeholder": "Admin, Owner",
         "help": "Same as Self users, but matched on role names. DMs ignore this list. "
                 "Leave empty to skip. Note: if all four allow lists are empty, the filter "
                 "is fully open and every message is treated as third-party (default)."},
    ]

    @property
    def subcommands(self) -> List[str]:
        return ["login", "logout", "status"]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, "Usage: /discord login <bot_token>"
        bot_token = args[0]
        try:
            r = httpx.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {bot_token}"},
                timeout=15,
            )
            if r.status_code != 200:
                return False, f"Invalid bot token: {r.status_code}"
            data = r.json()
        except Exception as e:
            return False, f"Discord connection error: {e}"

        save_credential(self.spec.cred_file, DiscordCredential(
            bot_token=bot_token,
            bot_id=str(data.get("id") or ""),
            bot_username=data.get("username") or "",
        ))
        return True, f"Discord bot connected: {data.get('username')} ({data.get('id')})"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Discord credentials found."
        try:
            from ...manager import get_external_comms_manager
            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed Discord credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Discord: Not connected"
        cred = load_credential(self.spec.cred_file, DiscordCredential)
        if not cred or not cred.bot_token:
            return True, "Discord: Not connected"
        # Emit a parseable account row so the Manage modal's "Connected
        # Accounts" section populates. Falls back to the literal "bot" if
        # we don't have the cached username/id (older creds pre-migration).
        name = cred.bot_username or "Discord bot"
        ident = cred.bot_id or "bot"
        return True, f"Discord: Connected\n  - {name} ({ident})"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------

@register_client
class DiscordClient(BasePlatformClient):
    """Unified Discord client exposing bot, user, and voice operations."""
    spec = DISCORD
    PLATFORM_ID = DISCORD.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[DiscordCredential] = None
        self._ws = None
        self._ws_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval: float = 41.25
        self._last_sequence: Optional[int] = None
        self._bot_user_id: Optional[str] = None
        self._catchup_done: bool = False
        # Lazy voice manager - created/started on first voice call, reused after
        self._voice_mgr: Optional[Any] = None
        # Per-guild role-name cache: guild_id -> ({role_id: lower_name}, expires_at).
        # Refreshed on miss / 10-minute expiry so role renames or new roles
        # propagate without an agent restart.
        self._role_name_cache: Dict[str, Tuple[Dict[str, str], float]] = {}

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> DiscordCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, DiscordCredential)
        if self._cred is None:
            raise RuntimeError("No Discord credentials. Use /discord login first.")
        return self._cred

    def _bot_token(self) -> str:
        cred = self._load()
        if not cred.bot_token:
            raise RuntimeError("No Discord bot_token configured.")
        return cred.bot_token

    def _user_token(self) -> str:
        cred = self._load()
        if not cred.user_token:
            raise RuntimeError("No Discord user_token configured.")
        return cred.user_token

    def _bot_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bot {self._bot_token()}", "Content-Type": "application/json"}

    def _user_headers(self) -> Dict[str, str]:
        return {"Authorization": self._user_token(), "Content-Type": "application/json"}

    async def connect(self) -> None:
        self._load()
        self._connected = True

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return
        self._message_callback = callback
        cred = self._load()
        if not cred.bot_token:
            raise RuntimeError("No Discord bot token for Gateway connection")

        bot_info = self.get_bot_user()
        if "error" in bot_info:
            raise RuntimeError(f"Invalid Discord bot token: {bot_info.get('error')}")
        self._bot_user_id = bot_info["result"]["id"]

        self._listening = True
        self._catchup_done = False
        self._ws_task = asyncio.create_task(self._gateway_loop())

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        self._ws_task = None

    async def _gateway_loop(self) -> None:
        import websockets
        while self._listening:
            try:
                async with websockets.connect(
                    DISCORD_GATEWAY_URL,
                    open_timeout=None,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=None,
                ) as ws:
                    self._ws = ws
                    await self._handle_gateway(ws)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DISCORD] Gateway error: {e}")
                if self._listening:
                    await asyncio.sleep(5)

    async def _handle_gateway(self, ws) -> None:
        try:
            async for raw in ws:
                if not self._listening:
                    break
                try:
                    data = json.loads(raw)
                    await self._process_gateway_event(ws, data)
                except Exception as e:
                    logger.error(f"[DISCORD] Error processing Gateway event: {e}")
        except Exception as e:
            logger.debug(f"[DISCORD] Gateway socket closed: {e}")

    async def _process_gateway_event(self, ws, data: dict) -> None:
        op = data.get("op")
        t = data.get("t")
        d = data.get("d")
        s = data.get("s")
        if s is not None:
            self._last_sequence = s

        if op == 10:
            self._heartbeat_interval = d["heartbeat_interval"] / 1000.0
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
            await ws.send(json.dumps({
                "op": 2,
                "d": {
                    "token": self._bot_token(),
                    "intents": GATEWAY_INTENTS,
                    "properties": {"os": "windows", "browser": "craftosbot", "device": "craftosbot"},
                },
            }))
        elif op == 0:
            if t == "READY":
                asyncio.get_running_loop().call_later(2.0, self._mark_catchup_done)
            elif t == "MESSAGE_CREATE" and d:
                await self._handle_message_create(d)
        elif op == 1:
            await ws.send(json.dumps({"op": 1, "d": self._last_sequence}))
        elif op in (7, 9):
            # 7 = reconnect requested, 9 = invalid session - both close the socket
            await ws.close()

    def _mark_catchup_done(self) -> None:
        self._catchup_done = True

    async def _heartbeat_loop(self, ws) -> None:
        try:
            while self._listening:
                await ws.send(json.dumps({"op": 1, "d": self._last_sequence}))
                await asyncio.sleep(self._heartbeat_interval)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _handle_message_create(self, d: dict) -> None:
        author = d.get("author", {})
        if author.get("id") == self._bot_user_id or author.get("bot"):
            return
        content = d.get("content", "")
        if not content or not self._catchup_done:
            return

        # ----- Filter + classify -----
        # Two-stage:
        #   1. mention_only - drop if bot wasn't @-mentioned (when enabled)
        #   2. allowlists - try self first; if matched, classify as
        #      ``is_self_message=True``. Else try third-party. If neither
        #      list matches AND any list is configured, drop. If all four
        #      lists are empty, the filter is fully open (current default).
        cfg = load_config(_discord_config_file(), DiscordConfig) or DiscordConfig()

        if cfg.mention_only:
            mentions = d.get("mentions") or []
            mentioned_ids = {str(m.get("id")) for m in mentions if isinstance(m, dict)}
            if self._bot_user_id and self._bot_user_id not in mentioned_ids:
                return

        guild_id = d.get("guild_id")
        member = d.get("member") or {}
        role_ids = [str(r) for r in (member.get("roles") or [])]
        author_username_candidates = {
            (author.get("username") or "").lower(),
            (author.get("global_name") or "").lower(),
        }
        # Resolve role names lazily - only fetch if any role list is set.
        # Cached 10 min per guild, async helper takes a thread off the event loop.
        user_role_names: set = set()
        any_role_list = (cfg.self_role_names or cfg.third_party_role_names)
        if any_role_list and guild_id and role_ids:
            role_map = await self._resolve_guild_role_names(str(guild_id))
            user_role_names = {role_map.get(rid, "") for rid in role_ids if role_map.get(rid)}

        def _matches(usernames: list, role_names: list) -> bool:
            uns = {u.lower().strip() for u in (usernames or []) if u.strip()}
            rns = {r.lower().strip() for r in (role_names or []) if r.strip()}
            if uns and any(c and c in uns for c in author_username_candidates):
                return True
            if rns and user_role_names and (rns & user_role_names):
                return True
            return False

        any_self = bool(cfg.self_usernames or cfg.self_role_names)
        any_tp = bool(cfg.third_party_usernames or cfg.third_party_role_names)

        is_self_message = False
        if any_self and _matches(cfg.self_usernames, cfg.self_role_names):
            is_self_message = True
        elif any_tp and _matches(cfg.third_party_usernames, cfg.third_party_role_names):
            is_self_message = False
        elif any_self or any_tp:
            # At least one list configured but the user matched none â†’ drop.
            return
        # else: all four lists empty â†’ fall through, classify as third-party.

        author_name = author.get("username", "Unknown")
        channel_id = d.get("channel_id", "")
        guild_id = d.get("guild_id", "")
        channel_name = f"#{channel_id}" if guild_id else "DM"

        ts = None
        try:
            ts = datetime.fromisoformat(d.get("timestamp", ""))
        except Exception:
            pass

        if self._message_callback:
            await self._message_callback(PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=author.get("id", ""),
                sender_name=author_name,
                text=content,
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=d.get("id", ""),
                timestamp=ts,
                raw={"guild_id": guild_id, "is_self_message": is_self_message},
            ))

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return self.bot_send_message(channel_id=recipient, content=text, **kwargs)

    # ----- Bot REST API -----
    def get_bot_user(self) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/@me",
            headers=self._bot_headers(),
            transform=lambda d: {
                "id": d.get("id"), "username": d.get("username"),
                "discriminator": d.get("discriminator"), "avatar": d.get("avatar"),
                "bot": d.get("bot", True),
            },
        )

    def get_bot_guilds(self, limit: int = 100) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/@me/guilds",
            headers=self._bot_headers(), params={"limit": limit},
            transform=lambda d: {"guilds": d},
        )

    def get_guild_channels(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
            headers=self._bot_headers(),
            transform=lambda channels: {
                "all_channels": channels,
                "text_channels": [c for c in channels if c.get("type") == 0],
                "voice_channels": [c for c in channels if c.get("type") == 2],
                "categories": [c for c in channels if c.get("type") == 4],
            },
        )

    def get_guild_roles(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/roles",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda roles: {"roles": roles},
        )

    async def _resolve_guild_role_names(self, guild_id: str) -> Dict[str, str]:
        """Return ``{role_id: lower-cased role_name}`` for ``guild_id``, cached 10 min.

        Used by the listener's role-name allowlist filter. Falls back to an
        empty mapping on REST failure so a transient API blip doesn't lock
        the agent out of its own messages - the role check is bypassed in
        that case (handled by the caller).
        """
        now = time.time()
        cached = self._role_name_cache.get(guild_id)
        if cached and cached[1] > now:
            return cached[0]
        try:
            result = await asyncio.to_thread(self.get_guild_roles, guild_id)
            roles = result.get("result", {}).get("roles", []) if "error" not in result else []
            mapping = {str(r.get("id")): (r.get("name") or "").lower()
                       for r in roles if isinstance(r, dict)}
        except Exception as e:
            logger.debug(f"[DISCORD] role lookup for {guild_id} failed: {e}")
            mapping = {}
        self._role_name_cache[guild_id] = (mapping, now + 600.0)
        return mapping

    def get_channel(self, channel_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{channel_id}",
            headers=self._bot_headers(),
        )

    def bot_send_message(self, channel_id: str, content: str,
                         embed: Optional[Dict[str, Any]] = None,
                         reply_to: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {"content": content}
        if embed:
            payload["embeds"] = [embed]
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=self._bot_headers(), json=payload,
            transform=lambda d: {
                "message_id": d.get("id"), "channel_id": d.get("channel_id"),
                "content": d.get("content"), "timestamp": d.get("timestamp"),
            },
        )

    def get_messages(self, channel_id: str, limit: int = 50,
                     before: Optional[str] = None, after: Optional[str] = None) -> Result:
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=self._bot_headers(), params=params, expected=(200,),
            transform=lambda messages: {
                "messages": [
                    {"id": m.get("id"), "content": m.get("content"),
                     "author": {"id": m.get("author", {}).get("id"),
                                "username": m.get("author", {}).get("username"),
                                "bot": m.get("author", {}).get("bot", False)},
                     "timestamp": m.get("timestamp"),
                     "attachments": m.get("attachments", []),
                     "embeds": m.get("embeds", [])}
                    for m in messages
                ],
                "count": len(messages),
            },
        )

    def edit_message(self, channel_id: str, message_id: str, content: str) -> Result:
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers=self._bot_headers(), json={"content": content}, expected=(200,),
        )

    def delete_message(self, channel_id: str, message_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"deleted": True},
        )

    def create_dm_channel(self, recipient_id: str) -> Result:
        return http_request(
            "POST", f"{DISCORD_API_BASE}/users/@me/channels",
            headers=self._bot_headers(), json={"recipient_id": recipient_id},
            transform=lambda d: {
                "channel_id": d.get("id"), "type": d.get("type"),
                "recipients": d.get("recipients", []),
            },
        )

    def send_dm(self, recipient_id: str, content: str,
                embed: Optional[Dict[str, Any]] = None) -> Result:
        dm_result = self.create_dm_channel(recipient_id)
        if "error" in dm_result:
            return dm_result
        return self.bot_send_message(dm_result["result"]["channel_id"], content, embed)

    def get_user(self, user_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/{user_id}",
            headers=self._bot_headers(), expected=(200,),
        )

    def get_guild_member(self, guild_id: str, user_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
            headers=self._bot_headers(), expected=(200,),
        )

    def list_guild_members(self, guild_id: str, limit: int = 100) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/members",
            headers=self._bot_headers(), params={"limit": min(limit, 1000)}, expected=(200,),
            transform=lambda members: {"members": members},
        )

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> Result:
        encoded_emoji = _url_quote(emoji, safe="")
        return http_request(
            "PUT",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"added": True, "emoji": emoji},
        )

    # ----- User-account methods -----
    def user_get_current_user(self) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/@me",
            headers=self._user_headers(), expected=(200,),
            transform=lambda d: {
                "id": d.get("id"), "username": d.get("username"),
                "discriminator": d.get("discriminator"), "email": d.get("email"),
                "avatar": d.get("avatar"),
            },
        )

    def user_get_guilds(self, limit: int = 100) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/@me/guilds",
            headers=self._user_headers(), params={"limit": limit}, expected=(200,),
            transform=lambda d: {"guilds": d},
        )

    def user_get_dm_channels(self) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/@me/channels",
            headers=self._user_headers(), expected=(200,),
            transform=lambda channels: {
                "dm_channels": [
                    {"id": c.get("id"), "type": c.get("type"),
                     "recipients": [{"id": rec.get("id"), "username": rec.get("username")}
                                    for rec in c.get("recipients", [])],
                     "last_message_id": c.get("last_message_id")}
                    for c in channels
                ],
                "count": len(channels),
            },
        )

    def user_send_message(self, channel_id: str, content: str,
                          reply_to: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {"content": content}
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=self._user_headers(), json=payload,
            transform=lambda d: {
                "message_id": d.get("id"), "channel_id": d.get("channel_id"),
                "content": d.get("content"), "timestamp": d.get("timestamp"),
            },
        )

    def user_get_messages(self, channel_id: str, limit: int = 50,
                          before: Optional[str] = None, after: Optional[str] = None) -> Result:
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=self._user_headers(), params=params, expected=(200,),
            transform=lambda messages: {
                "messages": [
                    {"id": m.get("id"), "content": m.get("content"),
                     "author": {"id": m.get("author", {}).get("id"),
                                "username": m.get("author", {}).get("username")},
                     "timestamp": m.get("timestamp"),
                     "attachments": m.get("attachments", [])}
                    for m in messages
                ],
                "count": len(messages),
            },
        )

    def user_send_dm(self, recipient_id: str, content: str) -> Result:
        result = http_request(
            "POST", f"{DISCORD_API_BASE}/users/@me/channels",
            headers=self._user_headers(), json={"recipient_id": recipient_id},
        )
        if "error" in result:
            return result
        channel_id = result.get("result", {}).get("id")
        return self.user_send_message(channel_id, content)

    def user_get_relationships(self) -> Result:
        def _shape(relationships):
            friends = [r for r in relationships if r.get("type") == 1]
            return {
                "friends": [{"id": r.get("id"),
                             "username": r.get("user", {}).get("username")} for r in friends],
                "blocked": [r for r in relationships if r.get("type") == 2],
                "incoming_requests": [r for r in relationships if r.get("type") == 3],
                "outgoing_requests": [r for r in relationships if r.get("type") == 4],
                "total_friends": len(friends),
            }
        return http_request(
            "GET", f"{DISCORD_API_BASE}/users/@me/relationships",
            headers=self._user_headers(), expected=(200,), transform=_shape,
        )

    def user_search_guild_messages(self, guild_id: str, query: str, limit: int = 25) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/messages/search",
            headers=self._user_headers(),
            params={"content": query, "limit": limit}, expected=(200,), timeout=30,
            transform=lambda d: {
                "total_results": d.get("total_results"),
                "messages": d.get("messages", []),
            },
        )

    # ----- Voice (lazy import + cached manager) -----
    async def _voice_manager(self):
        """Lazy-create + start the DiscordVoiceManager once and reuse it.

        Previous behaviour created a fresh manager + started a new bot
        connection on every voice call, leaking connections.
        """
        if self._voice_mgr is None:
            from . import _discord_voice
            self._voice_mgr = _discord_voice.DiscordVoiceManager(self._bot_token())
        if not getattr(self._voice_mgr, "_running", False):
            await self._voice_mgr.start()
        return self._voice_mgr

    async def join_voice(self, guild_id: str, channel_id: str,
                         self_deaf: bool = False, self_mute: bool = False) -> Result:
        try:
            mgr = await self._voice_manager()
            return await mgr.join_voice(guild_id, channel_id, self_deaf=self_deaf, self_mute=self_mute)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    async def leave_voice(self, guild_id: str) -> Result:
        try:
            mgr = await self._voice_manager()
            return await mgr.leave_voice(guild_id)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    async def speak_tts(self, guild_id: str, text: str,
                        tts_provider: str = "openai", voice: str = "alloy") -> Result:
        try:
            mgr = await self._voice_manager()
            return await mgr.speak_text(guild_id, text, tts_provider=tts_provider, voice=voice)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    async def get_voice_status(self, guild_id: str) -> Result:
        try:
            mgr = await self._voice_manager()
            return mgr.get_voice_status(guild_id)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    # ==================================================================
    # Messages (extended): bulk delete, crosspost, pins, reactions
    # ==================================================================

    def bulk_delete_messages(self, channel_id: str,
                             message_ids: List[str]) -> Result:
        """Delete 2-100 messages, all <14 days old. Returns 204."""
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/messages/bulk-delete",
            headers=self._bot_headers(),
            json={"messages": message_ids}, expected=(204,),
            transform=lambda _: {"deleted": len(message_ids)},
        )

    def crosspost_message(self, channel_id: str, message_id: str) -> Result:
        """Publish a message from an announcement channel to following channels."""
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/crosspost",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda d: {"id": d.get("id"), "flags": d.get("flags")},
        )

    def pin_message(self, channel_id: str, message_id: str) -> Result:
        return http_request(
            "PUT", f"{DISCORD_API_BASE}/channels/{channel_id}/pins/{message_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"pinned": True, "message_id": message_id},
        )

    def unpin_message(self, channel_id: str, message_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/channels/{channel_id}/pins/{message_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"unpinned": True, "message_id": message_id},
        )

    def list_pinned_messages(self, channel_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{channel_id}/pins",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda messages: {"messages": messages, "count": len(messages)},
        )

    def remove_user_reaction(self, channel_id: str, message_id: str,
                             emoji: str, user_id: str) -> Result:
        encoded = _url_quote(emoji, safe="")
        return http_request(
            "DELETE",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/{user_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"removed": True, "emoji": emoji, "user_id": user_id},
        )

    def remove_own_reaction(self, channel_id: str, message_id: str,
                            emoji: str) -> Result:
        encoded = _url_quote(emoji, safe="")
        return http_request(
            "DELETE",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"removed": True, "emoji": emoji},
        )

    def list_reaction_users(self, channel_id: str, message_id: str,
                            emoji: str, limit: int = 100) -> Result:
        encoded = _url_quote(emoji, safe="")
        return http_request(
            "GET",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}",
            headers=self._bot_headers(),
            params={"limit": min(limit, 100)}, expected=(200,),
            transform=lambda users: {"users": users, "count": len(users)},
        )

    def clear_reactions(self, channel_id: str, message_id: str,
                        emoji: Optional[str] = None) -> Result:
        """Clear all reactions, or just one emoji's reactions."""
        if emoji:
            encoded = _url_quote(emoji, safe="")
            url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}"
        else:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions"
        return http_request(
            "DELETE", url, headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"cleared": True, "emoji": emoji or "*"},
        )

    # ==================================================================
    # Threads
    # ==================================================================

    def create_thread_from_message(self, channel_id: str, message_id: str,
                                   name: str,
                                   auto_archive_duration: int = 1440) -> Result:
        """auto_archive_duration in minutes: 60, 1440, 4320, 10080."""
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/threads",
            headers=self._bot_headers(),
            json={"name": name, "auto_archive_duration": auto_archive_duration},
            expected=(201,),
            transform=lambda d: {"thread_id": d.get("id"), "name": d.get("name"),
                                 "parent_id": d.get("parent_id")},
        )

    def create_thread(self, channel_id: str, name: str,
                      thread_type: int = 11,
                      auto_archive_duration: int = 1440,
                      invitable: bool = True,
                      rate_limit_per_user: Optional[int] = None) -> Result:
        """thread_type: 10=announcement, 11=public, 12=private. Default 11 (public)."""
        payload: Dict[str, Any] = {
            "name": name,
            "type": thread_type,
            "auto_archive_duration": auto_archive_duration,
            "invitable": invitable,
        }
        if rate_limit_per_user is not None:
            payload["rate_limit_per_user"] = rate_limit_per_user
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/threads",
            headers=self._bot_headers(), json=payload, expected=(201,),
            transform=lambda d: {"thread_id": d.get("id"), "name": d.get("name"),
                                 "type": d.get("type"), "parent_id": d.get("parent_id")},
        )

    def join_thread(self, thread_id: str) -> Result:
        return http_request(
            "PUT", f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members/@me",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"joined": True, "thread_id": thread_id},
        )

    def leave_thread(self, thread_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members/@me",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"left": True, "thread_id": thread_id},
        )

    def add_thread_member(self, thread_id: str, user_id: str) -> Result:
        return http_request(
            "PUT", f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members/{user_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"added": True, "user_id": user_id},
        )

    def remove_thread_member(self, thread_id: str, user_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members/{user_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"removed": True, "user_id": user_id},
        )

    def list_thread_members(self, thread_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda m: {"members": m, "count": len(m)},
        )

    def list_active_threads(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/threads/active",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda d: {"threads": d.get("threads", []),
                                 "members": d.get("members", [])},
        )

    def archive_thread(self, thread_id: str) -> Result:
        """Archive by PATCHing the thread with archived=true."""
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/channels/{thread_id}",
            headers=self._bot_headers(),
            json={"archived": True}, expected=(200,),
            transform=lambda d: {"archived": True, "thread_id": d.get("id")},
        )

    def unarchive_thread(self, thread_id: str) -> Result:
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/channels/{thread_id}",
            headers=self._bot_headers(),
            json={"archived": False}, expected=(200,),
            transform=lambda d: {"archived": False, "thread_id": d.get("id")},
        )

    # ==================================================================
    # Channels (CRUD + invites + permission overwrites)
    # ==================================================================

    def create_guild_channel(self, guild_id: str, name: str,
                             channel_type: int = 0,
                             topic: Optional[str] = None,
                             parent_id: Optional[str] = None,
                             nsfw: bool = False,
                             rate_limit_per_user: Optional[int] = None,
                             position: Optional[int] = None,
                             permission_overwrites: Optional[List[Dict[str, Any]]] = None,
                             bitrate: Optional[int] = None,
                             user_limit: Optional[int] = None) -> Result:
        """channel_type: 0=text, 2=voice, 4=category, 5=announcement, 13=stage, 15=forum."""
        payload: Dict[str, Any] = {"name": name, "type": channel_type, "nsfw": nsfw}
        if topic is not None: payload["topic"] = topic
        if parent_id: payload["parent_id"] = parent_id
        if rate_limit_per_user is not None: payload["rate_limit_per_user"] = rate_limit_per_user
        if position is not None: payload["position"] = position
        if permission_overwrites is not None: payload["permission_overwrites"] = permission_overwrites
        if bitrate is not None: payload["bitrate"] = bitrate
        if user_limit is not None: payload["user_limit"] = user_limit
        return http_request(
            "POST", f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
            headers=self._bot_headers(), json=payload, expected=(201,),
            transform=lambda d: {"channel_id": d.get("id"), "name": d.get("name"),
                                 "type": d.get("type")},
        )

    def modify_channel(self, channel_id: str, name: Optional[str] = None,
                       topic: Optional[str] = None,
                       nsfw: Optional[bool] = None,
                       rate_limit_per_user: Optional[int] = None,
                       parent_id: Optional[str] = None,
                       position: Optional[int] = None,
                       bitrate: Optional[int] = None,
                       user_limit: Optional[int] = None,
                       archived: Optional[bool] = None,
                       locked: Optional[bool] = None) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None: payload["name"] = name
        if topic is not None: payload["topic"] = topic
        if nsfw is not None: payload["nsfw"] = nsfw
        if rate_limit_per_user is not None: payload["rate_limit_per_user"] = rate_limit_per_user
        if parent_id is not None: payload["parent_id"] = parent_id
        if position is not None: payload["position"] = position
        if bitrate is not None: payload["bitrate"] = bitrate
        if user_limit is not None: payload["user_limit"] = user_limit
        if archived is not None: payload["archived"] = archived
        if locked is not None: payload["locked"] = locked
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/channels/{channel_id}",
            headers=self._bot_headers(), json=payload, expected=(200,),
            transform=lambda d: {"channel_id": d.get("id"), "name": d.get("name"),
                                 "topic": d.get("topic")},
        )

    def delete_channel(self, channel_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/channels/{channel_id}",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda d: {"deleted": True, "channel_id": d.get("id")},
        )

    def edit_channel_permissions(self, channel_id: str, overwrite_id: str,
                                 allow: str = "0", deny: str = "0",
                                 type: int = 0) -> Result:
        """type: 0=role, 1=member. allow/deny are bitfields as decimal strings."""
        return http_request(
            "PUT", f"{DISCORD_API_BASE}/channels/{channel_id}/permissions/{overwrite_id}",
            headers=self._bot_headers(),
            json={"allow": allow, "deny": deny, "type": type}, expected=(204,),
            transform=lambda _: {"updated": True, "overwrite_id": overwrite_id},
        )

    def delete_channel_permission(self, channel_id: str, overwrite_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/channels/{channel_id}/permissions/{overwrite_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"deleted": True, "overwrite_id": overwrite_id},
        )

    def list_channel_invites(self, channel_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{channel_id}/invites",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda invites: {"invites": invites, "count": len(invites)},
        )

    def create_channel_invite(self, channel_id: str,
                              max_age: int = 86400, max_uses: int = 0,
                              temporary: bool = False, unique: bool = False) -> Result:
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/invites",
            headers=self._bot_headers(),
            json={"max_age": max_age, "max_uses": max_uses,
                  "temporary": temporary, "unique": unique},
            expected=(200, 201),
            transform=lambda d: {"code": d.get("code"), "url": f"https://discord.gg/{d.get('code')}",
                                 "max_age": d.get("max_age"), "max_uses": d.get("max_uses")},
        )

    def delete_invite(self, invite_code: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/invites/{invite_code}",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda d: {"deleted": True, "code": d.get("code")},
        )

    # ==================================================================
    # Webhooks
    # ==================================================================

    def list_channel_webhooks(self, channel_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/channels/{channel_id}/webhooks",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda webhooks: {"webhooks": webhooks, "count": len(webhooks)},
        )

    def create_webhook(self, channel_id: str, name: str,
                       avatar: Optional[str] = None) -> Result:
        """avatar is a data-URI string (data:image/png;base64,...)."""
        payload: Dict[str, Any] = {"name": name}
        if avatar: payload["avatar"] = avatar
        return http_request(
            "POST", f"{DISCORD_API_BASE}/channels/{channel_id}/webhooks",
            headers=self._bot_headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "token": d.get("token"),
                                 "url": d.get("url"), "name": d.get("name")},
        )

    def get_webhook(self, webhook_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/webhooks/{webhook_id}",
            headers=self._bot_headers(), expected=(200,),
        )

    def modify_webhook(self, webhook_id: str, name: Optional[str] = None,
                       avatar: Optional[str] = None,
                       channel_id: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None: payload["name"] = name
        if avatar is not None: payload["avatar"] = avatar
        if channel_id is not None: payload["channel_id"] = channel_id
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/webhooks/{webhook_id}",
            headers=self._bot_headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("name")},
        )

    def delete_webhook(self, webhook_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/webhooks/{webhook_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"deleted": True, "webhook_id": webhook_id},
        )

    def execute_webhook(self, webhook_id: str, webhook_token: str,
                        content: Optional[str] = None,
                        username: Optional[str] = None,
                        avatar_url: Optional[str] = None,
                        embeds: Optional[List[Dict[str, Any]]] = None,
                        wait: bool = False) -> Result:
        """Post via webhook URL (no bot token needed for execute)."""
        payload: Dict[str, Any] = {}
        if content: payload["content"] = content
        if username: payload["username"] = username
        if avatar_url: payload["avatar_url"] = avatar_url
        if embeds: payload["embeds"] = embeds
        params: Dict[str, Any] = {}
        if wait: params["wait"] = "true"
        return http_request(
            "POST", f"{DISCORD_API_BASE}/webhooks/{webhook_id}/{webhook_token}",
            headers={"Content-Type": "application/json"},
            json=payload, params=params, expected=(200, 204),
            transform=lambda d: {"sent": True, "message_id": (d or {}).get("id")},
        )

    # ==================================================================
    # Members (moderation: nickname, roles, kick, ban, timeout)
    # ==================================================================

    def modify_guild_member(self, guild_id: str, user_id: str,
                            nick: Optional[str] = None,
                            roles: Optional[List[str]] = None,
                            mute: Optional[bool] = None,
                            deaf: Optional[bool] = None,
                            channel_id: Optional[str] = None,
                            communication_disabled_until: Optional[str] = None) -> Result:
        """Modify a guild member. communication_disabled_until is an ISO 8601 timestamp for timeout (max 28 days)."""
        payload: Dict[str, Any] = {}
        if nick is not None: payload["nick"] = nick
        if roles is not None: payload["roles"] = roles
        if mute is not None: payload["mute"] = mute
        if deaf is not None: payload["deaf"] = deaf
        if channel_id is not None: payload["channel_id"] = channel_id
        if communication_disabled_until is not None:
            payload["communication_disabled_until"] = communication_disabled_until
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
            headers=self._bot_headers(), json=payload, expected=(200,),
            transform=lambda d: {"nick": d.get("nick"),
                                 "roles": d.get("roles", []),
                                 "communication_disabled_until": d.get("communication_disabled_until")},
        )

    def modify_current_member_nick(self, guild_id: str,
                                   nick: Optional[str]) -> Result:
        """Set the bot's own nickname in a guild."""
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/@me",
            headers=self._bot_headers(), json={"nick": nick}, expected=(200,),
            transform=lambda d: {"nick": d.get("nick")},
        )

    def add_guild_member_role(self, guild_id: str, user_id: str,
                              role_id: str) -> Result:
        return http_request(
            "PUT", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"added": True, "role_id": role_id},
        )

    def remove_guild_member_role(self, guild_id: str, user_id: str,
                                 role_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"removed": True, "role_id": role_id},
        )

    def kick_guild_member(self, guild_id: str, user_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"kicked": True, "user_id": user_id},
        )

    def ban_guild_member(self, guild_id: str, user_id: str,
                         delete_message_seconds: int = 0) -> Result:
        """delete_message_seconds: 0..604800 (7 days)."""
        return http_request(
            "PUT", f"{DISCORD_API_BASE}/guilds/{guild_id}/bans/{user_id}",
            headers=self._bot_headers(),
            json={"delete_message_seconds": delete_message_seconds},
            expected=(204,),
            transform=lambda _: {"banned": True, "user_id": user_id},
        )

    def unban_guild_member(self, guild_id: str, user_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/guilds/{guild_id}/bans/{user_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"unbanned": True, "user_id": user_id},
        )

    def list_guild_bans(self, guild_id: str, limit: int = 100) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/bans",
            headers=self._bot_headers(),
            params={"limit": min(limit, 1000)}, expected=(200,),
            transform=lambda bans: {"bans": bans, "count": len(bans)},
        )

    def search_guild_members(self, guild_id: str, query: str,
                             limit: int = 10) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/members/search",
            headers=self._bot_headers(),
            params={"query": query, "limit": min(limit, 1000)}, expected=(200,),
            transform=lambda members: {"members": members, "count": len(members)},
        )

    # ==================================================================
    # Guild: roles + emojis + stickers + scheduled events + audit log + invites
    # ==================================================================

    def get_guild(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}",
            headers=self._bot_headers(), expected=(200,),
        )

    def create_guild_role(self, guild_id: str, name: str,
                          permissions: Optional[str] = None,
                          color: Optional[int] = None,
                          hoist: bool = False,
                          mentionable: bool = False) -> Result:
        payload: Dict[str, Any] = {"name": name, "hoist": hoist, "mentionable": mentionable}
        if permissions is not None: payload["permissions"] = permissions
        if color is not None: payload["color"] = color
        return http_request(
            "POST", f"{DISCORD_API_BASE}/guilds/{guild_id}/roles",
            headers=self._bot_headers(), json=payload, expected=(200,),
            transform=lambda d: {"role_id": d.get("id"), "name": d.get("name"),
                                 "color": d.get("color")},
        )

    def modify_guild_role(self, guild_id: str, role_id: str,
                          name: Optional[str] = None,
                          permissions: Optional[str] = None,
                          color: Optional[int] = None,
                          hoist: Optional[bool] = None,
                          mentionable: Optional[bool] = None) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None: payload["name"] = name
        if permissions is not None: payload["permissions"] = permissions
        if color is not None: payload["color"] = color
        if hoist is not None: payload["hoist"] = hoist
        if mentionable is not None: payload["mentionable"] = mentionable
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/guilds/{guild_id}/roles/{role_id}",
            headers=self._bot_headers(), json=payload, expected=(200,),
        )

    def delete_guild_role(self, guild_id: str, role_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/guilds/{guild_id}/roles/{role_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"deleted": True, "role_id": role_id},
        )

    def list_guild_emojis(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/emojis",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda emojis: {"emojis": emojis, "count": len(emojis)},
        )

    def create_guild_emoji(self, guild_id: str, name: str,
                           image: str, roles: Optional[List[str]] = None) -> Result:
        """image is a data-URI: 'data:image/png;base64,<base64>'."""
        payload: Dict[str, Any] = {"name": name, "image": image}
        if roles: payload["roles"] = roles
        return http_request(
            "POST", f"{DISCORD_API_BASE}/guilds/{guild_id}/emojis",
            headers=self._bot_headers(), json=payload, expected=(201,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("name")},
        )

    def delete_guild_emoji(self, guild_id: str, emoji_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/guilds/{guild_id}/emojis/{emoji_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"deleted": True, "emoji_id": emoji_id},
        )

    def list_guild_stickers(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/stickers",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda s: {"stickers": s, "count": len(s)},
        )

    def list_scheduled_events(self, guild_id: str,
                              with_user_count: bool = False) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/scheduled-events",
            headers=self._bot_headers(),
            params={"with_user_count": str(with_user_count).lower()},
            expected=(200,),
            transform=lambda events: {"events": events, "count": len(events)},
        )

    def create_scheduled_event(self, guild_id: str, name: str,
                               scheduled_start_time: str,
                               entity_type: int,
                               privacy_level: int = 2,
                               scheduled_end_time: Optional[str] = None,
                               channel_id: Optional[str] = None,
                               entity_metadata: Optional[Dict[str, Any]] = None,
                               description: Optional[str] = None) -> Result:
        """entity_type: 1=stage_instance, 2=voice, 3=external. privacy_level: 2=guild_only."""
        payload: Dict[str, Any] = {
            "name": name,
            "scheduled_start_time": scheduled_start_time,
            "entity_type": entity_type,
            "privacy_level": privacy_level,
        }
        if scheduled_end_time is not None: payload["scheduled_end_time"] = scheduled_end_time
        if channel_id is not None: payload["channel_id"] = channel_id
        if entity_metadata is not None: payload["entity_metadata"] = entity_metadata
        if description is not None: payload["description"] = description
        return http_request(
            "POST", f"{DISCORD_API_BASE}/guilds/{guild_id}/scheduled-events",
            headers=self._bot_headers(), json=payload, expected=(200,),
            transform=lambda d: {"event_id": d.get("id"), "name": d.get("name")},
        )

    def modify_scheduled_event(self, guild_id: str, event_id: str,
                               **fields) -> Result:
        return http_request(
            "PATCH", f"{DISCORD_API_BASE}/guilds/{guild_id}/scheduled-events/{event_id}",
            headers=self._bot_headers(), json=fields, expected=(200,),
        )

    def delete_scheduled_event(self, guild_id: str, event_id: str) -> Result:
        return http_request(
            "DELETE", f"{DISCORD_API_BASE}/guilds/{guild_id}/scheduled-events/{event_id}",
            headers=self._bot_headers(), expected=(204,),
            transform=lambda _: {"deleted": True, "event_id": event_id},
        )

    def get_audit_log(self, guild_id: str,
                      user_id: Optional[str] = None,
                      action_type: Optional[int] = None,
                      before: Optional[str] = None,
                      limit: int = 50) -> Result:
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if user_id: params["user_id"] = user_id
        if action_type is not None: params["action_type"] = action_type
        if before: params["before"] = before
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/audit-logs",
            headers=self._bot_headers(), params=params, expected=(200,),
            transform=lambda d: {"audit_log_entries": d.get("audit_log_entries", []),
                                 "users": d.get("users", []),
                                 "webhooks": d.get("webhooks", [])},
        )

    def list_guild_invites(self, guild_id: str) -> Result:
        return http_request(
            "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/invites",
            headers=self._bot_headers(), expected=(200,),
            transform=lambda invites: {"invites": invites, "count": len(invites)},
        )
