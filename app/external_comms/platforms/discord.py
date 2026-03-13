# -*- coding: utf-8 -*-
"""
Discord API client — combined bot + user + voice via httpx.

Supports three modes:
- Bot mode: uses ``Bot {token}`` auth for server/bot operations.
- User mode: uses bare token auth for self-bot / personal automation.
- Both: store both tokens and call whichever set of methods you need.

Voice methods are thin stubs that lazily import the
``DiscordVoiceManager`` from agent_core to avoid pulling in
discord.py / PyNaCl / FFmpeg unless actually needed.

WARNING: Automating user accounts (self-bots) may violate Discord's
Terms of Service. Use user-mode methods at your own risk.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote as _url_quote

import httpx

from app.external_comms.base import BasePlatformClient, PlatformMessage, MessageCallback
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
CREDENTIAL_FILE = "discord.json"

# Gateway intents: GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT
GATEWAY_INTENTS = (1 << 9) | (1 << 12) | (1 << 15)  # 37376


@dataclass
class DiscordCredential:
    bot_token: str = ""
    user_token: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════════════════

@register_client
class DiscordClient(BasePlatformClient):
    """Unified Discord client exposing bot, user, and voice operations."""

    PLATFORM_ID = "discord"

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

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> DiscordCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, DiscordCredential)
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
        return {
            "Authorization": f"Bot {self._bot_token()}",
            "Content-Type": "application/json",
        }

    def _user_headers(self) -> Dict[str, str]:
        return {
            "Authorization": self._user_token(),
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # BasePlatformClient interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._load()
        self._connected = True

    # ------------------------------------------------------------------
    # Gateway listening (WebSocket)
    # ------------------------------------------------------------------

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback: MessageCallback) -> None:
        """Connect to the Discord Gateway and listen for messages."""
        if self._listening:
            return

        self._message_callback = callback
        cred = self._load()
        if not cred.bot_token:
            raise RuntimeError("No Discord bot token for Gateway connection")

        # Verify token by fetching bot user info
        bot_info = self.get_bot_user()
        if "error" in bot_info:
            raise RuntimeError(f"Invalid Discord bot token: {bot_info.get('error')}")
        self._bot_user_id = bot_info["result"]["id"]

        self._listening = True
        self._catchup_done = False
        self._ws_task = asyncio.create_task(self._gateway_loop())
        logger.info(
            f"[DISCORD] Gateway listener started for bot {bot_info['result'].get('username', 'unknown')}"
        )

    async def stop_listening(self) -> None:
        """Disconnect from the Gateway."""
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

        logger.info("[DISCORD] Gateway listener stopped")

    async def _gateway_loop(self) -> None:
        """Main Gateway reconnection loop."""
        import aiohttp

        while self._listening:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(DISCORD_GATEWAY_URL) as ws:
                        self._ws = ws
                        await self._handle_gateway(ws)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DISCORD] Gateway error: {e}")
                if self._listening:
                    await asyncio.sleep(5)

    async def _handle_gateway(self, ws) -> None:
        """Handle a single Gateway session."""
        import aiohttp as _aiohttp
        async for msg in ws:
            if not self._listening:
                break
            if msg.type == _aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await self._process_gateway_event(ws, data)
                except Exception as e:
                    logger.error(f"[DISCORD] Error processing Gateway event: {e}")
            elif msg.type in (_aiohttp.WSMsgType.ERROR, _aiohttp.WSMsgType.CLOSED):
                break

    async def _process_gateway_event(self, ws, data: dict) -> None:
        """Process a single Gateway event."""
        op = data.get("op")
        t = data.get("t")
        d = data.get("d")
        s = data.get("s")

        if s is not None:
            self._last_sequence = s

        if op == 10:  # Hello — start heartbeat + identify
            self._heartbeat_interval = d["heartbeat_interval"] / 1000.0
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
            # Send Identify
            await ws.send_json({
                "op": 2,
                "d": {
                    "token": self._bot_token(),
                    "intents": GATEWAY_INTENTS,
                    "properties": {
                        "os": "windows",
                        "browser": "craftosbot",
                        "device": "craftosbot",
                    },
                },
            })

        elif op == 0:  # Dispatch
            if t == "READY":
                logger.info("[DISCORD] Gateway READY")
                # Mark catchup as done after a short delay to skip any
                # initial burst of cached messages
                asyncio.get_event_loop().call_later(2.0, self._mark_catchup_done)

            elif t == "MESSAGE_CREATE" and d:
                await self._handle_message_create(d)

        elif op == 1:  # Heartbeat request
            await ws.send_json({"op": 1, "d": self._last_sequence})

        elif op == 9:  # Invalid session
            logger.warning("[DISCORD] Invalid session, reconnecting...")
            await ws.close()

        elif op == 7:  # Reconnect
            logger.info("[DISCORD] Gateway requested reconnect")
            await ws.close()

    def _mark_catchup_done(self) -> None:
        self._catchup_done = True
        logger.info("[DISCORD] Catchup complete — now dispatching messages")

    async def _heartbeat_loop(self, ws) -> None:
        """Send heartbeats at the required interval."""
        try:
            while self._listening:
                await ws.send_json({"op": 1, "d": self._last_sequence})
                await asyncio.sleep(self._heartbeat_interval)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _handle_message_create(self, d: dict) -> None:
        """Process a MESSAGE_CREATE event."""
        # Ignore messages from the bot itself
        author = d.get("author", {})
        if author.get("id") == self._bot_user_id:
            return

        # Ignore bot messages
        if author.get("bot"):
            return

        content = d.get("content", "")
        if not content:
            return

        # Skip during catchup
        if not self._catchup_done:
            return

        author_name = author.get("username", "Unknown")
        channel_id = d.get("channel_id", "")
        guild_id = d.get("guild_id", "")

        # Determine channel name
        channel_name = ""
        if guild_id:
            # It's a guild channel — we don't have the name cached, use ID
            channel_name = f"#{channel_id}"
        else:
            # DM
            channel_name = "DM"

        ts = None
        if d.get("timestamp"):
            try:
                ts = datetime.fromisoformat(d["timestamp"])
            except Exception:
                pass

        platform_msg = PlatformMessage(
            platform="discord",
            sender_id=author.get("id", ""),
            sender_name=author_name,
            text=content,
            channel_id=channel_id,
            channel_name=channel_name,
            message_id=d.get("id", ""),
            timestamp=ts,
            raw={"guild_id": guild_id, "is_self_message": False},
        )

        if self._message_callback:
            await self._message_callback(platform_msg)

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a message to a channel (uses bot token by default)."""
        return self.bot_send_message(channel_id=recipient, content=text, **kwargs)

    # ══════════════════════════════════════════════════════════════════════
    # BOT METHODS
    # ══════════════════════════════════════════════════════════════════════

    # --- Bot info -------------------------------------------------------

    def get_bot_user(self) -> Dict[str, Any]:
        """Get the bot's own user information."""
        try:
            r = httpx.get(f"{DISCORD_API_BASE}/users/@me", headers=self._bot_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "id": data.get("id"),
                        "username": data.get("username"),
                        "discriminator": data.get("discriminator"),
                        "avatar": data.get("avatar"),
                        "bot": data.get("bot", True),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_bot_guilds(self, limit: int = 100) -> Dict[str, Any]:
        """Get guilds (servers) the bot is a member of."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/users/@me/guilds",
                headers=self._bot_headers(),
                params={"limit": limit},
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": {"guilds": r.json()}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # --- Channels -------------------------------------------------------

    def get_guild_channels(self, guild_id: str) -> Dict[str, Any]:
        """Get all channels in a guild."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
                headers=self._bot_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                channels = r.json()
                text_channels = [c for c in channels if c.get("type") == 0]
                voice_channels = [c for c in channels if c.get("type") == 2]
                categories = [c for c in channels if c.get("type") == 4]
                return {
                    "ok": True,
                    "result": {
                        "all_channels": channels,
                        "text_channels": text_channels,
                        "voice_channels": voice_channels,
                        "categories": categories,
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_channel(self, channel_id: str) -> Dict[str, Any]:
        """Get a channel by ID."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/channels/{channel_id}",
                headers=self._bot_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # --- Messages -------------------------------------------------------

    def bot_send_message(
        self,
        channel_id: str,
        content: str,
        embed: Optional[Dict[str, Any]] = None,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a message to a channel as the bot."""
        payload: Dict[str, Any] = {"content": content}
        if embed:
            payload["embeds"] = [embed]
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}

        try:
            r = httpx.post(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                headers=self._bot_headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "message_id": data.get("id"),
                        "channel_id": data.get("channel_id"),
                        "content": data.get("content"),
                        "timestamp": data.get("timestamp"),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_messages(
        self,
        channel_id: str,
        limit: int = 50,
        before: Optional[str] = None,
        after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get messages from a channel (bot token)."""
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                headers=self._bot_headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                messages = r.json()
                return {
                    "ok": True,
                    "result": {
                        "messages": [
                            {
                                "id": m.get("id"),
                                "content": m.get("content"),
                                "author": {
                                    "id": m.get("author", {}).get("id"),
                                    "username": m.get("author", {}).get("username"),
                                    "bot": m.get("author", {}).get("bot", False),
                                },
                                "timestamp": m.get("timestamp"),
                                "attachments": m.get("attachments", []),
                                "embeds": m.get("embeds", []),
                            }
                            for m in messages
                        ],
                        "count": len(messages),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """Edit a message the bot sent."""
        try:
            r = httpx.patch(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
                headers=self._bot_headers(),
                json={"content": content},
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> Dict[str, Any]:
        """Delete a message."""
        try:
            r = httpx.delete(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
                headers=self._bot_headers(),
                timeout=15,
            )
            if r.status_code == 204:
                return {"ok": True, "result": {"deleted": True}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # --- Direct messages ------------------------------------------------

    def create_dm_channel(self, recipient_id: str) -> Dict[str, Any]:
        """Create (or retrieve) a DM channel with a user (bot token)."""
        try:
            r = httpx.post(
                f"{DISCORD_API_BASE}/users/@me/channels",
                headers=self._bot_headers(),
                json={"recipient_id": recipient_id},
                timeout=15,
            )
            if r.status_code in (200, 201):
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "channel_id": data.get("id"),
                        "type": data.get("type"),
                        "recipients": data.get("recipients", []),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def send_dm(
        self,
        recipient_id: str,
        content: str,
        embed: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a DM to a user via the bot."""
        dm_result = self.create_dm_channel(recipient_id)
        if "error" in dm_result:
            return dm_result
        channel_id = dm_result["result"]["channel_id"]
        return self.bot_send_message(channel_id, content, embed)

    # --- Users & members ------------------------------------------------

    def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get a user by ID (bot token)."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/users/{user_id}",
                headers=self._bot_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_guild_member(self, guild_id: str, user_id: str) -> Dict[str, Any]:
        """Get a member of a guild."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
                headers=self._bot_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": r.json()}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def list_guild_members(self, guild_id: str, limit: int = 100) -> Dict[str, Any]:
        """List members of a guild."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/members",
                headers=self._bot_headers(),
                params={"limit": min(limit, 1000)},
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": {"members": r.json()}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # --- Reactions -------------------------------------------------------

    def add_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
    ) -> Dict[str, Any]:
        """Add a reaction to a message."""
        encoded_emoji = _url_quote(emoji, safe="")
        try:
            r = httpx.put(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me",
                headers=self._bot_headers(),
                timeout=15,
            )
            if r.status_code == 204:
                return {"ok": True, "result": {"added": True, "emoji": emoji}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════════
    # USER-ACCOUNT METHODS (self-bot / personal automation)
    # ══════════════════════════════════════════════════════════════════════

    def user_get_current_user(self) -> Dict[str, Any]:
        """Get the authenticated user's own profile."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/users/@me",
                headers=self._user_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "id": data.get("id"),
                        "username": data.get("username"),
                        "discriminator": data.get("discriminator"),
                        "email": data.get("email"),
                        "avatar": data.get("avatar"),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def user_get_guilds(self, limit: int = 100) -> Dict[str, Any]:
        """Get guilds the user account is in."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/users/@me/guilds",
                headers=self._user_headers(),
                params={"limit": limit},
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, "result": {"guilds": r.json()}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def user_get_dm_channels(self) -> Dict[str, Any]:
        """Get the user's DM channel list."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/users/@me/channels",
                headers=self._user_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                channels = r.json()
                return {
                    "ok": True,
                    "result": {
                        "dm_channels": [
                            {
                                "id": c.get("id"),
                                "type": c.get("type"),
                                "recipients": [
                                    {
                                        "id": rec.get("id"),
                                        "username": rec.get("username"),
                                    }
                                    for rec in c.get("recipients", [])
                                ],
                                "last_message_id": c.get("last_message_id"),
                            }
                            for c in channels
                        ],
                        "count": len(channels),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def user_send_message(
        self,
        channel_id: str,
        content: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a message as the user account."""
        payload: Dict[str, Any] = {"content": content}
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}

        try:
            r = httpx.post(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                headers=self._user_headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "message_id": data.get("id"),
                        "channel_id": data.get("channel_id"),
                        "content": data.get("content"),
                        "timestamp": data.get("timestamp"),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def user_get_messages(
        self,
        channel_id: str,
        limit: int = 50,
        before: Optional[str] = None,
        after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get messages from a channel (user token)."""
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                headers=self._user_headers(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                messages = r.json()
                return {
                    "ok": True,
                    "result": {
                        "messages": [
                            {
                                "id": m.get("id"),
                                "content": m.get("content"),
                                "author": {
                                    "id": m.get("author", {}).get("id"),
                                    "username": m.get("author", {}).get("username"),
                                },
                                "timestamp": m.get("timestamp"),
                                "attachments": m.get("attachments", []),
                            }
                            for m in messages
                        ],
                        "count": len(messages),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def user_send_dm(
        self,
        recipient_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """Send a DM as the user account."""
        # Create / retrieve the DM channel first
        try:
            r = httpx.post(
                f"{DISCORD_API_BASE}/users/@me/channels",
                headers=self._user_headers(),
                json={"recipient_id": recipient_id},
                timeout=15,
            )
            if r.status_code not in (200, 201):
                return {"error": f"API error: {r.status_code}", "details": r.text}
            channel_id = r.json().get("id")
        except Exception as e:
            return {"error": str(e)}

        return self.user_send_message(channel_id, content)

    def user_get_relationships(self) -> Dict[str, Any]:
        """Get the user's relationships (friends, blocked, pending)."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/users/@me/relationships",
                headers=self._user_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                relationships = r.json()
                friends = [rel for rel in relationships if rel.get("type") == 1]
                blocked = [rel for rel in relationships if rel.get("type") == 2]
                incoming = [rel for rel in relationships if rel.get("type") == 3]
                outgoing = [rel for rel in relationships if rel.get("type") == 4]
                return {
                    "ok": True,
                    "result": {
                        "friends": [
                            {
                                "id": rel.get("id"),
                                "username": rel.get("user", {}).get("username"),
                            }
                            for rel in friends
                        ],
                        "blocked": blocked,
                        "incoming_requests": incoming,
                        "outgoing_requests": outgoing,
                        "total_friends": len(friends),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def user_search_guild_messages(
        self,
        guild_id: str,
        query: str,
        limit: int = 25,
    ) -> Dict[str, Any]:
        """Search messages in a guild (user token — not available to bots)."""
        try:
            r = httpx.get(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/messages/search",
                headers=self._user_headers(),
                params={"content": query, "limit": limit},
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "ok": True,
                    "result": {
                        "total_results": data.get("total_results"),
                        "messages": data.get("messages", []),
                    },
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════════
    # VOICE STUBS  (lazy-import to avoid requiring discord.py at load time)
    # ══════════════════════════════════════════════════════════════════════

    def _get_voice_manager(self):
        """Lazily import and instantiate the DiscordVoiceManager."""
        from app.external_comms.platforms.discord_voice_helpers import DiscordVoiceManager
        return DiscordVoiceManager(self._bot_token())

    async def join_voice(
        self,
        guild_id: str,
        channel_id: str,
        self_deaf: bool = False,
        self_mute: bool = False,
    ) -> Dict[str, Any]:
        """Join a voice channel.

        Requires discord.py[voice], PyNaCl, and FFmpeg.
        """
        try:
            from app.external_comms.platforms.discord_voice_helpers import DiscordVoiceManager
            manager = DiscordVoiceManager(self._bot_token())
            await manager.start()
            return await manager.join_voice(guild_id, channel_id, self_deaf=self_deaf, self_mute=self_mute)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    async def leave_voice(self, guild_id: str) -> Dict[str, Any]:
        """Leave the voice channel in a guild.

        Requires discord.py[voice], PyNaCl, and FFmpeg.
        """
        try:
            from app.external_comms.platforms.discord_voice_helpers import DiscordVoiceManager
            manager = DiscordVoiceManager(self._bot_token())
            return await manager.leave_voice(guild_id)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    async def speak_tts(
        self,
        guild_id: str,
        text: str,
        tts_provider: str = "openai",
        voice: str = "alloy",
    ) -> Dict[str, Any]:
        """Speak text in a voice channel via TTS.

        Requires discord.py[voice], PyNaCl, FFmpeg, and a TTS provider.
        """
        try:
            from app.external_comms.platforms.discord_voice_helpers import DiscordVoiceManager
            manager = DiscordVoiceManager(self._bot_token())
            return await manager.speak_text(guild_id, text, tts_provider=tts_provider, voice=voice)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}

    def get_voice_status(self, guild_id: str) -> Dict[str, Any]:
        """Get the current voice connection status for a guild.

        Requires discord.py[voice].
        """
        try:
            from app.external_comms.platforms.discord_voice_helpers import DiscordVoiceManager
            manager = DiscordVoiceManager(self._bot_token())
            return manager.get_voice_status(guild_id)
        except ImportError as e:
            return {"error": f"Voice dependencies not installed: {e}"}
        except Exception as e:
            return {"error": str(e)}
