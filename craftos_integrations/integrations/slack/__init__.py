# -*- coding: utf-8 -*-
"""Slack integration - handler (token + OAuth invite) + client (poll listener)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    OAuthFlow,
    PlatformMessage,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import arequest, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

SLACK_API_BASE = "https://slack.com/api"
# files:read gates downloading url_private bytes (metadata embedded in
# history messages needs only the history scopes). Workspaces connected
# before it was added must reconnect to grant it — download_file returns
# an explicit reconnect error on missing_scope.
SLACK_SCOPES = "chat:write,channels:read,channels:history,groups:read,groups:history,users:read,files:read,files:write,im:read,im:write,im:history"

POLL_INTERVAL = 3
RETRY_DELAY = 5


def _shape_slack(result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply Slack's ``{ok: bool, ...}`` envelope to an ``arequest``/``request`` result.

    On HTTP success but ``ok=False`` returns ``{error, details}``. Otherwise returns
    the raw Slack response (callers read fields like ``channels``, ``channel.id`` directly).
    """
    if "error" in result:
        return result
    body = result["result"]
    if not body.get("ok"):
        return {"error": body.get("error", "Unknown error"), "details": body}
    return body


def _slack_call(
    method: str, path: str, headers: Dict[str, str], **kw
) -> Dict[str, Any]:
    return _shape_slack(
        http_request(
            method,
            f"{SLACK_API_BASE}/{path}",
            headers=headers,
            expected=(200,),
            **kw,
        )
    )


async def _slack_acall(
    method: str, path: str, headers: Dict[str, str], **kw
) -> Dict[str, Any]:
    return _shape_slack(
        await arequest(
            method,
            f"{SLACK_API_BASE}/{path}",
            headers=headers,
            expected=(200,),
            **kw,
        )
    )


@dataclass
class SlackCredential:
    bot_token: str = ""
    workspace_id: str = ""
    team_name: str = ""


SLACK = IntegrationSpec(
    name="slack",
    cred_class=SlackCredential,
    cred_file="slack.json",
    platform_id="slack",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(SLACK.name)
class SlackHandler(IntegrationHandler):
    spec = SLACK
    display_name = "Slack"
    description = "Team messaging"
    auth_type = "both"  # OAuth invite + raw bot token
    icon = "slack"
    connect_help = [
        "Open api.slack.com/apps",
        "Click 'Create New App' â†’ 'From scratch', pick your workspace",
        "Open 'OAuth & Permissions' in the left sidebar",
        "Add bot scopes: chat:write, channels:read, users:read (more as needed)",
        "Click 'Install to Workspace' at the top, then copy the 'Bot User OAuth Token' (xoxb-...)",
    ]
    fields = [
        {
            "key": "bot_token",
            "label": "Bot Token",
            "placeholder": "xoxb-...",
            "password": True,
        },
        {
            "key": "workspace_name",
            "label": "Workspace Name (optional)",
            "placeholder": "My Workspace",
            "password": False,
            "optional": True,
        },
    ]

    oauth = OAuthFlow(
        client_id_key="SLACK_SHARED_CLIENT_ID",
        client_secret_key="SLACK_SHARED_CLIENT_SECRET",
        auth_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        userinfo_url=None,
        scopes=SLACK_SCOPES,
        use_https=True,
    )

    @property
    def subcommands(self) -> List[str]:
        return ["invite", "login", "logout", "status"]

    async def invite(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"Slack OAuth failed: {result['error']}"

        raw = result.get("raw", {})
        if not raw.get("ok"):
            return False, f"Slack OAuth token exchange failed: {raw.get('error')}"

        bot_token = raw.get("access_token", "")
        team = raw.get("team", {})
        team_id = team.get("id", "")
        team_name = team.get("name", team_id)

        save_credential(
            self.spec.cred_file,
            SlackCredential(
                bot_token=bot_token,
                workspace_id=team_id,
                team_name=team_name,
            ),
        )
        return True, f"Slack connected via CraftOS app: {team_name} ({team_id})"

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, "Usage: /slack login <bot_token> [workspace_name]"
        bot_token = args[0]
        if not bot_token.startswith(("xoxb-", "xoxp-")):
            return False, "Invalid token. Expected xoxb-... or xoxp-..."

        result = _slack_call(
            "POST", "auth.test", {"Authorization": f"Bearer {bot_token}"}
        )
        if "error" in result:
            return False, f"Slack auth failed: {result['error']}"
        team_id = result.get("team_id", "")
        workspace_name = args[1] if len(args) > 1 else result.get("team", team_id)

        save_credential(
            self.spec.cred_file,
            SlackCredential(
                bot_token=bot_token,
                workspace_id=team_id,
                team_name=workspace_name,
            ),
        )
        return True, f"Slack connected: {workspace_name} ({team_id})"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Slack credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Slack credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Slack: Not connected"
        cred = load_credential(self.spec.cred_file, SlackCredential)
        name = cred.team_name or cred.workspace_id if cred else "unknown"
        return True, f"Slack: Connected\n  - {name} ({cred.workspace_id})"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class SlackClient(BasePlatformClient):
    spec = SLACK
    PLATFORM_ID = SLACK.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[SlackCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._bot_user_id: Optional[str] = None
        self._last_timestamps: Dict[str, str] = {}
        self._catchup_done: bool = False

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> SlackCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, SlackCredential)
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

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return
        self._message_callback = callback
        cred = self._load()

        data = await _slack_acall(
            "POST", "auth.test", {"Authorization": f"Bearer {cred.bot_token}"}
        )
        if "error" in data:
            raise RuntimeError(f"Invalid Slack token: {data['error']}")
        self._bot_user_id = data.get("user_id")

        logger.info(f"[SLACK] Bot user ID: {self._bot_user_id}")
        self._listening = True
        self._catchup_done = False
        self._poll_task = asyncio.create_task(self._poll_loop())

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

    async def _poll_loop(self) -> None:
        try:
            await self._refresh_channel_timestamps()
            self._catchup_done = True
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
        channels: List[Dict[str, Any]] = []
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
                data = await _slack_acall(
                    "GET", "conversations.list", self._headers(), params=params
                )
                if "error" in data:
                    break
                for ch in data.get("channels", []):
                    if ch.get("is_member") or ch.get("is_im") or ch.get("is_mpim"):
                        channels.append(ch)
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        return channels

    async def _refresh_channel_timestamps(self) -> None:
        now_ts = f"{time.time():.6f}"
        channels = await self._get_joined_channels()
        for ch in channels:
            ch_id = ch.get("id", "")
            if ch_id:
                self._last_timestamps[ch_id] = now_ts

    async def _poll_channels(self) -> None:
        channels = await self._get_joined_channels()
        now_ts = f"{time.time():.6f}"
        for ch in channels:
            ch_id = ch.get("id", "")
            if ch_id and ch_id not in self._last_timestamps:
                self._last_timestamps[ch_id] = now_ts

        for ch_id, oldest_ts in list(self._last_timestamps.items()):
            try:
                data = await _slack_acall(
                    "GET",
                    "conversations.history",
                    self._headers(),
                    params={"channel": ch_id, "oldest": oldest_ts, "limit": 50},
                )
                if "error" in data:
                    err_code = (data.get("details") or {}).get("error", "")
                    if err_code in ("channel_not_found", "not_in_channel"):
                        self._last_timestamps.pop(ch_id, None)
                    continue

                messages = data.get("messages", [])
                if not messages:
                    continue

                messages.sort(key=lambda m: float(m.get("ts", "0")))
                for msg in messages:
                    await self._process_message(msg, ch_id)
                self._last_timestamps[ch_id] = messages[-1].get("ts", oldest_ts)
            except Exception as e:
                logger.debug(f"[SLACK] Error polling channel {ch_id}: {e}")

    @staticmethod
    def _extract_attachments(msg: Dict[str, Any]) -> list:
        """Normalize the ``files[]`` embedded in a history message into
        PlatformMessage.attachments. Metadata needs only history scopes;
        fetching bytes needs files:read (see attachment-reception plan)."""
        out: list = []
        for f in msg.get("files") or []:
            if not isinstance(f, dict):
                continue
            mime = f.get("mimetype", "") or ""
            if mime.startswith("image/"):
                kind = "photo"
            elif mime.startswith("video/"):
                kind = "video"
            elif mime.startswith("audio/"):
                kind = "audio"
            else:
                kind = "document"
            att: dict = {"kind": kind, "id": f.get("id", "")}
            if f.get("name"):
                att["name"] = f["name"]
            if mime:
                att["mime"] = mime
            if f.get("size"):
                att["size"] = f["size"]
            if f.get("permalink"):
                att["url"] = f["permalink"]
            out.append(att)
        return out

    async def _process_message(self, msg: Dict[str, Any], channel_id: str) -> None:
        # File uploads may arrive as subtype "file_share" — exempt them from
        # the bot/subtype drop or attachments die before the text guard.
        subtype = msg.get("subtype")
        if msg.get("bot_id") or (subtype and subtype not in ("file_share", "file_comment")):
            return
        user_id = msg.get("user", "")
        text = msg.get("text", "")
        attachments = self._extract_attachments(msg)
        # Attachment-only posts (no caption) must not be dropped.
        if (not text and not attachments) or user_id == self._bot_user_id:
            return

        sender_name = user_id
        try:
            info = self.get_user_info(user_id)
            if info.get("ok"):
                profile = info.get("user", {}).get("profile", {})
                sender_name = (
                    profile.get("display_name") or profile.get("real_name") or user_id
                )
        except Exception:
            pass

        ts_float = float(msg.get("ts", "0"))
        timestamp = (
            datetime.fromtimestamp(ts_float, tz=timezone.utc) if ts_float else None
        )

        if self._message_callback:
            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=user_id,
                    sender_name=sender_name,
                    text=text,
                    channel_id=channel_id,
                    message_id=msg.get("ts", ""),
                    timestamp=timestamp,
                    raw=msg,
                    attachments=attachments,
                )
            )

    # ----- API -----
    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"channel": recipient, "text": text}
        if kwargs.get("thread_ts"):
            payload["thread_ts"] = kwargs["thread_ts"]
        if kwargs.get("blocks"):
            payload["blocks"] = kwargs["blocks"]
        return _slack_call("POST", "chat.postMessage", self._headers(), json=payload)

    def list_channels(
        self,
        types: str = "public_channel,private_channel",
        limit: int = 100,
        exclude_archived: bool = True,
    ) -> Dict[str, Any]:
        return _slack_call(
            "GET",
            "conversations.list",
            self._headers(),
            params={
                "types": types,
                "limit": limit,
                "exclude_archived": exclude_archived,
            },
        )

    def get_channel_info(self, channel: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "conversations.info", self._headers(), params={"channel": channel}
        )

    def get_channel_history(
        self,
        channel: str,
        limit: int = 100,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"channel": channel, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        return _slack_call(
            "GET", "conversations.history", self._headers(), params=params
        )

    def create_channel(self, name: str, is_private: bool = False) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.create",
            self._headers(),
            json={"name": name, "is_private": is_private},
        )

    def invite_to_channel(self, channel: str, users: List[str]) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.invite",
            self._headers(),
            json={"channel": channel, "users": ",".join(users)},
        )

    def list_users(self, limit: int = 100) -> Dict[str, Any]:
        return _slack_call(
            "GET", "users.list", self._headers(), params={"limit": limit}
        )

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "users.info", self._headers(), params={"user": user_id}
        )

    def open_dm(self, users: List[str]) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.open",
            self._headers(),
            json={"users": ",".join(users)},
        )

    def search_messages(
        self,
        query: str,
        count: int = 20,
        sort: str = "timestamp",
        sort_dir: str = "desc",
    ) -> Dict[str, Any]:
        return _slack_call(
            "GET",
            "search.messages",
            self._headers(),
            params={"query": query, "count": count, "sort": sort, "sort_dir": sort_dir},
        )

    def upload_file(
        self,
        channels: List[str],
        content: Optional[str] = None,
        file_path: Optional[str] = None,
        filename: Optional[str] = None,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Legacy files.upload — kept for backwards compat. New code should use upload_file_v2,
        which uses the modern 3-step files.getUploadURLExternal flow."""
        cred = self._load()
        form_data: Dict[str, Any] = {"channels": ",".join(channels)}
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
            return _slack_call(
                "POST",
                "files.upload",
                {"Authorization": f"Bearer {cred.bot_token}"},
                data=form_data,
                files=files,
            )
        finally:
            if files:
                files["file"].close()

    # ------------------------------------------------------------------
    # Messages: edit / delete / ephemeral / schedule / permalink / threads
    # ------------------------------------------------------------------

    def update_message(
        self,
        channel: str,
        ts: str,
        text: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"channel": channel, "ts": ts}
        if text is not None:
            payload["text"] = text
        if blocks is not None:
            payload["blocks"] = blocks
        if attachments is not None:
            payload["attachments"] = attachments
        return _slack_call("POST", "chat.update", self._headers(), json=payload)

    def delete_message(self, channel: str, ts: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "chat.delete", self._headers(), json={"channel": channel, "ts": ts}
        )

    def post_ephemeral(
        self,
        channel: str,
        user: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"channel": channel, "user": user, "text": text}
        if blocks is not None:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        return _slack_call("POST", "chat.postEphemeral", self._headers(), json=payload)

    def schedule_message(
        self,
        channel: str,
        post_at: int,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """post_at is a unix timestamp."""
        payload: Dict[str, Any] = {"channel": channel, "post_at": post_at, "text": text}
        if blocks is not None:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        return _slack_call(
            "POST", "chat.scheduleMessage", self._headers(), json=payload
        )

    def delete_scheduled_message(
        self, channel: str, scheduled_message_id: str
    ) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "chat.deleteScheduledMessage",
            self._headers(),
            json={"channel": channel, "scheduled_message_id": scheduled_message_id},
        )

    def list_scheduled_messages(
        self, channel: Optional[str] = None, limit: int = 100
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"limit": limit}
        if channel:
            payload["channel"] = channel
        return _slack_call(
            "POST", "chat.scheduledMessages.list", self._headers(), json=payload
        )

    def get_permalink(self, channel: str, message_ts: str) -> Dict[str, Any]:
        return _slack_call(
            "GET",
            "chat.getPermalink",
            self._headers(),
            params={"channel": channel, "message_ts": message_ts},
        )

    def get_thread_replies(
        self, channel: str, ts: str, limit: int = 100, cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"channel": channel, "ts": ts, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return _slack_call(
            "GET", "conversations.replies", self._headers(), params=params
        )

    # ----- Reactions -----

    def add_reaction(self, channel: str, timestamp: str, name: str) -> Dict[str, Any]:
        """name is the emoji name without colons (e.g. 'thumbsup')."""
        return _slack_call(
            "POST",
            "reactions.add",
            self._headers(),
            json={"channel": channel, "timestamp": timestamp, "name": name},
        )

    def remove_reaction(
        self, channel: str, timestamp: str, name: str
    ) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "reactions.remove",
            self._headers(),
            json={"channel": channel, "timestamp": timestamp, "name": name},
        )

    def get_reactions(
        self, channel: str, timestamp: str, full: bool = True
    ) -> Dict[str, Any]:
        return _slack_call(
            "GET",
            "reactions.get",
            self._headers(),
            params={
                "channel": channel,
                "timestamp": timestamp,
                "full": str(full).lower(),
            },
        )

    def list_user_reactions(
        self, user: Optional[str] = None, count: int = 100
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"count": count, "full": "true"}
        if user:
            params["user"] = user
        return _slack_call("GET", "reactions.list", self._headers(), params=params)

    # ----- Pins -----

    def pin_message(self, channel: str, timestamp: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "pins.add",
            self._headers(),
            json={"channel": channel, "timestamp": timestamp},
        )

    def unpin_message(self, channel: str, timestamp: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "pins.remove",
            self._headers(),
            json={"channel": channel, "timestamp": timestamp},
        )

    def list_pins(self, channel: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "pins.list", self._headers(), params={"channel": channel}
        )

    # ------------------------------------------------------------------
    # Conversations: archive / rename / topic / purpose / join / leave / kick / members
    # ------------------------------------------------------------------

    def archive_channel(self, channel: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "conversations.archive", self._headers(), json={"channel": channel}
        )

    def unarchive_channel(self, channel: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.unarchive",
            self._headers(),
            json={"channel": channel},
        )

    def rename_channel(self, channel: str, name: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.rename",
            self._headers(),
            json={"channel": channel, "name": name},
        )

    def set_channel_topic(self, channel: str, topic: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.setTopic",
            self._headers(),
            json={"channel": channel, "topic": topic},
        )

    def set_channel_purpose(self, channel: str, purpose: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.setPurpose",
            self._headers(),
            json={"channel": channel, "purpose": purpose},
        )

    def join_channel(self, channel: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "conversations.join", self._headers(), json={"channel": channel}
        )

    def leave_channel(self, channel: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "conversations.leave", self._headers(), json={"channel": channel}
        )

    def kick_user(self, channel: str, user: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "conversations.kick",
            self._headers(),
            json={"channel": channel, "user": user},
        )

    def close_conversation(self, channel: str) -> Dict[str, Any]:
        """Close a DM / MPDM / private channel (per Slack's `conversations.close`)."""
        return _slack_call(
            "POST", "conversations.close", self._headers(), json={"channel": channel}
        )

    def list_channel_members(
        self, channel: str, limit: int = 100, cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"channel": channel, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return _slack_call(
            "GET", "conversations.members", self._headers(), params=params
        )

    # ------------------------------------------------------------------
    # Files (modern 3-step upload + list / info / delete)
    # ------------------------------------------------------------------

    def list_files(
        self,
        channel: Optional[str] = None,
        user: Optional[str] = None,
        types: Optional[str] = None,
        count: int = 100,
        page: int = 1,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"count": count, "page": page}
        if channel:
            params["channel"] = channel
        if user:
            params["user"] = user
        if types:
            params["types"] = types
        return _slack_call("GET", "files.list", self._headers(), params=params)

    def get_file_info(self, file_id: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "files.info", self._headers(), params={"file": file_id}
        )

    def download_file(self, file_id: str, dest_path: str) -> Dict[str, Any]:
        """Download a file's bytes to a local path.

        files.info runs first: on a token connected before files:read was
        added it fails with missing_scope → a clear reconnect error instead
        of the login-page HTML Slack serves (302, not 403) to unauthorized
        url_private fetches.
        """
        import os

        info = self.get_file_info(file_id)
        if "error" in info:
            if info.get("error") == "missing_scope":
                return {
                    "error": (
                        "Slack token lacks the files:read scope — reconnect "
                        "the Slack integration to grant it, then retry."
                    ),
                    "details": info.get("details", {}),
                }
            return info
        meta = info.get("file", {})
        url = meta.get("url_private_download") or meta.get("url_private", "")
        if not url:
            return {"error": "File has no downloadable URL", "details": meta}

        import httpx

        try:
            r = httpx.get(
                url,
                headers=self._headers(),
                follow_redirects=True,
                timeout=300.0,
            )
        except Exception as e:
            return {"error": f"Download failed: {e}"}
        content_type = r.headers.get("content-type", "")
        if r.status_code != 200 or content_type.startswith("text/html"):
            # Slack redirects unauthorized fetches to a sign-in page.
            return {
                "error": (
                    "Slack served a login page instead of the file — the "
                    "token cannot read files. Reconnect the Slack "
                    "integration to grant files:read."
                ),
                "details": {"status": r.status_code, "content_type": content_type},
            }
        if os.path.isdir(dest_path):
            dest_path = os.path.join(dest_path, meta.get("name") or file_id)
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return {
            "ok": True,
            "file_id": file_id,
            "path": dest_path,
            "name": meta.get("name", ""),
            "mimetype": meta.get("mimetype", ""),
            "size": len(r.content),
        }

    def delete_file(self, file_id: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "files.delete", self._headers(), json={"file": file_id}
        )

    def get_upload_url_external(
        self,
        filename: str,
        length: int,
        snippet_type: Optional[str] = None,
        alt_txt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Step 1 of the modern upload flow. Returns upload_url + file_id."""
        params: Dict[str, Any] = {"filename": filename, "length": length}
        if snippet_type:
            params["snippet_type"] = snippet_type
        if alt_txt:
            params["alt_txt"] = alt_txt
        return _slack_call(
            "GET", "files.getUploadURLExternal", self._headers(), params=params
        )

    def complete_upload_external(
        self,
        files: List[Dict[str, Any]],
        channel_id: Optional[str] = None,
        initial_comment: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Step 3 of the modern upload flow. files is [{id, title?, alt_txt?}, ...]."""
        payload: Dict[str, Any] = {"files": files}
        if channel_id:
            payload["channel_id"] = channel_id
        if initial_comment:
            payload["initial_comment"] = initial_comment
        if thread_ts:
            payload["thread_ts"] = thread_ts
        return _slack_call(
            "POST", "files.completeUploadExternal", self._headers(), json=payload
        )

    def upload_file_v2(
        self,
        file_path: str,
        channel_id: Optional[str] = None,
        initial_comment: Optional[str] = None,
        title: Optional[str] = None,
        thread_ts: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """High-level: full 3-step modern upload of a local file in one call."""
        import os
        import httpx

        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}"}
        if not filename:
            filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        step1 = self.get_upload_url_external(filename, file_size)
        if "error" in step1:
            return step1
        upload_url = step1.get("upload_url")
        file_id = step1.get("file_id")
        if not upload_url or not file_id:
            return {"error": "files.getUploadURLExternal returned no upload_url"}

        try:
            with open(file_path, "rb") as f:
                r = httpx.post(upload_url, content=f.read(), timeout=300.0)
            if r.status_code != 200:
                return {
                    "error": f"Upload to signed URL failed: {r.status_code}",
                    "details": r.text[:500],
                }
        except Exception as e:
            return {"error": str(e)}

        files_arr: List[Dict[str, Any]] = [{"id": file_id}]
        if title:
            files_arr[0]["title"] = title
        return self.complete_upload_external(
            files_arr,
            channel_id=channel_id,
            initial_comment=initial_comment,
            thread_ts=thread_ts,
        )

    # ------------------------------------------------------------------
    # Users: presence + usergroups
    # ------------------------------------------------------------------

    def get_user_presence(self, user: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "users.getPresence", self._headers(), params={"user": user}
        )

    def set_user_presence(self, presence: str) -> Dict[str, Any]:
        """Only works with user tokens (xoxp-), not bot tokens. presence: auto | away."""
        return _slack_call(
            "POST", "users.setPresence", self._headers(), json={"presence": presence}
        )

    def lookup_user_by_email(self, email: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "users.lookupByEmail", self._headers(), params={"email": email}
        )

    def list_usergroups(
        self,
        include_disabled: bool = False,
        include_count: bool = False,
        include_users: bool = False,
    ) -> Dict[str, Any]:
        return _slack_call(
            "GET",
            "usergroups.list",
            self._headers(),
            params={
                "include_disabled": str(include_disabled).lower(),
                "include_count": str(include_count).lower(),
                "include_users": str(include_users).lower(),
            },
        )

    def create_usergroup(
        self,
        name: str,
        handle: Optional[str] = None,
        description: Optional[str] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"name": name}
        if handle:
            payload["handle"] = handle
        if description:
            payload["description"] = description
        if channels:
            payload["channels"] = ",".join(channels)
        return _slack_call("POST", "usergroups.create", self._headers(), json=payload)

    def update_usergroup(
        self,
        usergroup: str,
        name: Optional[str] = None,
        handle: Optional[str] = None,
        description: Optional[str] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"usergroup": usergroup}
        if name is not None:
            payload["name"] = name
        if handle is not None:
            payload["handle"] = handle
        if description is not None:
            payload["description"] = description
        if channels is not None:
            payload["channels"] = ",".join(channels)
        return _slack_call("POST", "usergroups.update", self._headers(), json=payload)

    def enable_usergroup(self, usergroup: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "usergroups.enable", self._headers(), json={"usergroup": usergroup}
        )

    def disable_usergroup(self, usergroup: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "usergroups.disable", self._headers(), json={"usergroup": usergroup}
        )

    def list_usergroup_users(
        self, usergroup: str, include_disabled: bool = False
    ) -> Dict[str, Any]:
        return _slack_call(
            "GET",
            "usergroups.users.list",
            self._headers(),
            params={
                "usergroup": usergroup,
                "include_disabled": str(include_disabled).lower(),
            },
        )

    def update_usergroup_users(
        self, usergroup: str, users: List[str]
    ) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "usergroups.users.update",
            self._headers(),
            json={"usergroup": usergroup, "users": ",".join(users)},
        )

    # ------------------------------------------------------------------
    # Workspace / team / bookmarks / reminders
    # ------------------------------------------------------------------

    def auth_test(self) -> Dict[str, Any]:
        return _slack_call("POST", "auth.test", self._headers())

    def get_team_info(self, team: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if team:
            params["team"] = team
        return _slack_call("GET", "team.info", self._headers(), params=params)

    def list_bookmarks(self, channel_id: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "bookmarks.list", self._headers(), params={"channel_id": channel_id}
        )

    def add_bookmark(
        self,
        channel_id: str,
        title: str,
        type: str = "link",
        link: Optional[str] = None,
        emoji: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "channel_id": channel_id,
            "title": title,
            "type": type,
        }
        if link:
            payload["link"] = link
        if emoji:
            payload["emoji"] = emoji
        if entity_id:
            payload["entity_id"] = entity_id
        return _slack_call("POST", "bookmarks.add", self._headers(), json=payload)

    def edit_bookmark(
        self,
        channel_id: str,
        bookmark_id: str,
        title: Optional[str] = None,
        link: Optional[str] = None,
        emoji: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"channel_id": channel_id, "bookmark_id": bookmark_id}
        if title is not None:
            payload["title"] = title
        if link is not None:
            payload["link"] = link
        if emoji is not None:
            payload["emoji"] = emoji
        return _slack_call("POST", "bookmarks.edit", self._headers(), json=payload)

    def remove_bookmark(self, channel_id: str, bookmark_id: str) -> Dict[str, Any]:
        return _slack_call(
            "POST",
            "bookmarks.remove",
            self._headers(),
            json={"channel_id": channel_id, "bookmark_id": bookmark_id},
        )

    def add_reminder(
        self, text: str, time: Any, user: Optional[str] = None
    ) -> Dict[str, Any]:
        """time is a unix timestamp OR a natural-language string ("in 15 minutes").
        Requires xoxp- user token + reminders:write scope; bot tokens can't create reminders."""
        payload: Dict[str, Any] = {"text": text, "time": time}
        if user:
            payload["user"] = user
        return _slack_call("POST", "reminders.add", self._headers(), json=payload)

    def list_reminders(self) -> Dict[str, Any]:
        return _slack_call("POST", "reminders.list", self._headers())

    def complete_reminder(self, reminder: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "reminders.complete", self._headers(), json={"reminder": reminder}
        )

    def delete_reminder(self, reminder: str) -> Dict[str, Any]:
        return _slack_call(
            "POST", "reminders.delete", self._headers(), json={"reminder": reminder}
        )

    def get_reminder_info(self, reminder: str) -> Dict[str, Any]:
        return _slack_call(
            "GET", "reminders.info", self._headers(), params={"reminder": reminder}
        )
