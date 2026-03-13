# -*- coding: utf-8 -*-
"""Slack API client — direct HTTP via httpx."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.external_comms.base import BasePlatformClient, PlatformMessage, MessageCallback
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

SLACK_API_BASE = "https://slack.com/api"
CREDENTIAL_FILE = "slack.json"

POLL_INTERVAL = 3       # seconds between polls
RETRY_DELAY = 5         # seconds to wait after a poll error


@dataclass
class SlackCredential:
    bot_token: str = ""
    workspace_id: str = ""
    team_name: str = ""


@register_client
class SlackClient(BasePlatformClient):
    PLATFORM_ID = "slack"

    def __init__(self):
        super().__init__()
        self._cred: Optional[SlackCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._bot_user_id: Optional[str] = None
        self._last_timestamps: Dict[str, str] = {}  # channel_id -> latest ts seen
        self._catchup_done: bool = False

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> SlackCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, SlackCredential)
        if self._cred is None:
            raise RuntimeError("No Slack credentials. Use /slack login first.")
        return self._cred

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        return {
            "Authorization": f"Bearer {cred.bot_token}",
            "Content-Type": "application/json",
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    # ------------------------------------------------------------------
    # Listening support (polling via conversations.history)
    # ------------------------------------------------------------------

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback: MessageCallback) -> None:
        if self._listening:
            return

        self._message_callback = callback
        cred = self._load()

        # Verify token by calling auth.test
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SLACK_API_BASE}/auth.test",
                headers={"Authorization": f"Bearer {cred.bot_token}"},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Invalid Slack token: {data.get('error', 'unknown')}")
            self._bot_user_id = data.get("user_id")

        logger.info(f"[SLACK] Bot user ID: {self._bot_user_id}")

        self._listening = True
        self._catchup_done = False
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[SLACK] Poller started")

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        logger.info("[SLACK] Poller stopped")

    async def _poll_loop(self) -> None:
        """Poll all joined channels for new messages."""
        # Catchup: record current timestamps for all channels without dispatching
        logger.info("[SLACK] Running initial catchup...")
        try:
            await self._refresh_channel_timestamps()
            self._catchup_done = True
            logger.info(f"[SLACK] Catchup complete — tracking {len(self._last_timestamps)} channel(s)")
        except Exception as e:
            logger.error(f"[SLACK] Catchup error: {e}")
            self._catchup_done = True

        while self._listening:
            try:
                await self._poll_channels()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SLACK] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(POLL_INTERVAL)

    async def _get_joined_channels(self) -> List[Dict[str, Any]]:
        """Get all channels/DMs the bot is a member of."""
        channels: List[Dict[str, Any]] = []
        async with httpx.AsyncClient() as client:
            for ch_type in ("public_channel,private_channel", "mpim,im"):
                cursor = None
                while True:
                    params: Dict[str, Any] = {
                        "types": ch_type,
                        "exclude_archived": True,
                        "limit": 200,
                    }
                    if cursor:
                        params["cursor"] = cursor
                    resp = await client.get(
                        f"{SLACK_API_BASE}/conversations.list",
                        headers=self._headers(),
                        params=params,
                    )
                    data = resp.json()
                    if not data.get("ok"):
                        logger.warning(f"[SLACK] conversations.list failed: {data.get('error')}")
                        break
                    for ch in data.get("channels", []):
                        if ch.get("is_member") or ch.get("is_im") or ch.get("is_mpim"):
                            channels.append(ch)
                    cursor = data.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
        return channels

    async def _refresh_channel_timestamps(self) -> None:
        """Set the 'oldest' timestamp for each channel to now (catchup)."""
        now_ts = f"{time.time():.6f}"
        channels = await self._get_joined_channels()
        for ch in channels:
            ch_id = ch.get("id", "")
            if ch_id:
                self._last_timestamps[ch_id] = now_ts

    async def _poll_channels(self) -> None:
        """Check all tracked channels for new messages since last poll."""
        channels = await self._get_joined_channels()
        # Add any new channels we haven't seen
        now_ts = f"{time.time():.6f}"
        for ch in channels:
            ch_id = ch.get("id", "")
            if ch_id and ch_id not in self._last_timestamps:
                self._last_timestamps[ch_id] = now_ts

        async with httpx.AsyncClient() as client:
            for ch_id, oldest_ts in list(self._last_timestamps.items()):
                try:
                    resp = await client.get(
                        f"{SLACK_API_BASE}/conversations.history",
                        headers=self._headers(),
                        params={
                            "channel": ch_id,
                            "oldest": oldest_ts,
                            "limit": 50,
                        },
                    )
                    data = resp.json()
                    if not data.get("ok"):
                        if data.get("error") in ("channel_not_found", "not_in_channel"):
                            self._last_timestamps.pop(ch_id, None)
                        continue

                    messages = data.get("messages", [])
                    if not messages:
                        continue

                    # Messages are newest-first; process oldest-first
                    messages.sort(key=lambda m: float(m.get("ts", "0")))

                    for msg in messages:
                        await self._process_message(msg, ch_id)

                    # Advance timestamp past the newest message
                    newest_ts = messages[-1].get("ts", oldest_ts)
                    self._last_timestamps[ch_id] = newest_ts

                except Exception as e:
                    logger.debug(f"[SLACK] Error polling channel {ch_id}: {e}")

    async def _process_message(self, msg: Dict[str, Any], channel_id: str) -> None:
        """Process a single Slack message and dispatch to callback."""
        # Skip bot messages (including our own)
        if msg.get("bot_id"):
            return
        # Skip subtypes (joins, leaves, topic changes, etc.)
        if msg.get("subtype"):
            return

        user_id = msg.get("user", "")
        text = msg.get("text", "")
        if not text:
            return

        # Skip messages from our own bot user
        if user_id == self._bot_user_id:
            return

        # Resolve user name
        sender_name = user_id
        try:
            info = self.get_user_info(user_id)
            if info.get("ok"):
                profile = info.get("user", {}).get("profile", {})
                sender_name = profile.get("display_name") or profile.get("real_name") or user_id
        except Exception:
            pass

        ts_float = float(msg.get("ts", "0"))
        timestamp = datetime.fromtimestamp(ts_float, tz=timezone.utc) if ts_float else None

        platform_msg = PlatformMessage(
            platform="slack",
            sender_id=user_id,
            sender_name=sender_name,
            text=text,
            channel_id=channel_id,
            message_id=msg.get("ts", ""),
            timestamp=timestamp,
            raw=msg,
        )

        if self._message_callback:
            await self._message_callback(platform_msg)

    # ------------------------------------------------------------------
    # Send message
    # ------------------------------------------------------------------

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a message to a Slack channel or DM.

        Args:
            recipient: Channel ID or user ID for DM.
            text: Message text.
            **kwargs: Optional ``thread_ts`` (str) and ``blocks`` (list).

        Returns:
            API response with message details or error.
        """
        thread_ts: Optional[str] = kwargs.get("thread_ts")
        blocks: Optional[List[Dict[str, Any]]] = kwargs.get("blocks")

        payload: Dict[str, Any] = {
            "channel": recipient,
            "text": text,
        }

        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks

        r = httpx.post(f"{SLACK_API_BASE}/chat.postMessage", headers=self._headers(), json=payload)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    # ------------------------------------------------------------------
    # Channel methods
    # ------------------------------------------------------------------

    def list_channels(
        self,
        types: str = "public_channel,private_channel",
        limit: int = 100,
        exclude_archived: bool = True,
    ) -> Dict[str, Any]:
        """List channels in the workspace.

        Args:
            types: Comma-separated channel types (public_channel, private_channel, mpim, im).
            limit: Maximum number of channels to return.
            exclude_archived: Whether to exclude archived channels.

        Returns:
            API response with channels list or error.
        """
        params: Dict[str, Any] = {
            "types": types,
            "limit": limit,
            "exclude_archived": exclude_archived,
        }

        r = httpx.get(f"{SLACK_API_BASE}/conversations.list", headers=self._headers(), params=params)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    def get_channel_info(self, channel: str) -> Dict[str, Any]:
        """Get information about a channel.

        Args:
            channel: Channel ID.

        Returns:
            API response with channel info or error.
        """
        r = httpx.get(f"{SLACK_API_BASE}/conversations.info", headers=self._headers(), params={"channel": channel})
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    def get_channel_history(
        self,
        channel: str,
        limit: int = 100,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get message history from a channel.

        Args:
            channel: Channel ID.
            limit: Maximum number of messages to return.
            oldest: Start of time range (Unix timestamp).
            latest: End of time range (Unix timestamp).

        Returns:
            API response with messages or error.
        """
        params: Dict[str, Any] = {
            "channel": channel,
            "limit": limit,
        }

        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest

        r = httpx.get(f"{SLACK_API_BASE}/conversations.history", headers=self._headers(), params=params)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    def create_channel(self, name: str, is_private: bool = False) -> Dict[str, Any]:
        """Create a new channel.

        Args:
            name: Channel name (will be lowercased and hyphenated).
            is_private: Whether the channel should be private.

        Returns:
            API response with channel info or error.
        """
        payload: Dict[str, Any] = {
            "name": name,
            "is_private": is_private,
        }

        r = httpx.post(f"{SLACK_API_BASE}/conversations.create", headers=self._headers(), json=payload)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    def invite_to_channel(self, channel: str, users: List[str]) -> Dict[str, Any]:
        """Invite users to a channel.

        Args:
            channel: Channel ID.
            users: List of user IDs to invite.

        Returns:
            API response or error.
        """
        payload: Dict[str, Any] = {
            "channel": channel,
            "users": ",".join(users),
        }

        r = httpx.post(f"{SLACK_API_BASE}/conversations.invite", headers=self._headers(), json=payload)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    # ------------------------------------------------------------------
    # User methods
    # ------------------------------------------------------------------

    def list_users(self, limit: int = 100) -> Dict[str, Any]:
        """List users in the workspace.

        Args:
            limit: Maximum number of users to return.

        Returns:
            API response with users list or error.
        """
        r = httpx.get(f"{SLACK_API_BASE}/users.list", headers=self._headers(), params={"limit": limit})
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get information about a user.

        Args:
            user_id: The user ID.

        Returns:
            API response with user info or error.
        """
        r = httpx.get(f"{SLACK_API_BASE}/users.info", headers=self._headers(), params={"user": user_id})
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    # ------------------------------------------------------------------
    # Messaging / DM methods
    # ------------------------------------------------------------------

    def open_dm(self, users: List[str]) -> Dict[str, Any]:
        """Open a DM or group DM with users.

        Args:
            users: List of user IDs (1 for DM, 2+ for group DM).

        Returns:
            API response with channel info or error.
        """
        payload: Dict[str, Any] = {"users": ",".join(users)}

        r = httpx.post(f"{SLACK_API_BASE}/conversations.open", headers=self._headers(), json=payload)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    def search_messages(
        self,
        query: str,
        count: int = 20,
        sort: str = "timestamp",
        sort_dir: str = "desc",
    ) -> Dict[str, Any]:
        """Search for messages in the workspace.

        Args:
            query: Search query.
            count: Number of results to return.
            sort: Sort by ``"score"`` or ``"timestamp"``.
            sort_dir: Sort direction ``"asc"`` or ``"desc"``.

        Returns:
            API response with search results or error.
        """
        params: Dict[str, Any] = {
            "query": query,
            "count": count,
            "sort": sort,
            "sort_dir": sort_dir,
        }

        r = httpx.get(f"{SLACK_API_BASE}/search.messages", headers=self._headers(), params=params)
        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data

    # ------------------------------------------------------------------
    # File methods
    # ------------------------------------------------------------------

    def upload_file(
        self,
        channels: List[str],
        content: Optional[str] = None,
        file_path: Optional[str] = None,
        filename: Optional[str] = None,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a file to Slack.

        Args:
            channels: List of channel IDs to share the file to.
            content: File content as string (for text files).
            file_path: Path to local file to upload.
            filename: Filename to use.
            title: Title for the file.
            initial_comment: Message to include with the file.

        Returns:
            API response with file info or error.
        """
        # File uploads use multipart form data, so we only send the auth header
        # (no Content-Type — httpx sets it automatically for multipart).
        cred = self._load()
        headers = {"Authorization": f"Bearer {cred.bot_token}"}

        form_data: Dict[str, Any] = {
            "channels": ",".join(channels),
        }

        if filename:
            form_data["filename"] = filename
        if title:
            form_data["title"] = title
        if initial_comment:
            form_data["initial_comment"] = initial_comment

        files = None
        if file_path:
            files = {"file": open(file_path, "rb")}
        elif content:
            form_data["content"] = content

        try:
            r = httpx.post(f"{SLACK_API_BASE}/files.upload", headers=headers, data=form_data, files=files)
        finally:
            if files:
                files["file"].close()

        data = r.json()

        if not data.get("ok"):
            return {"error": data.get("error", "Unknown error"), "details": data}

        return data
