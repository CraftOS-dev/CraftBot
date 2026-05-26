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
SLACK_SCOPES = "chat:write,channels:read,channels:history,groups:read,groups:history,users:read,files:write,im:read,im:write,im:history"

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

    async def _process_message(self, msg: Dict[str, Any], channel_id: str) -> None:
        if msg.get("bot_id") or msg.get("subtype"):
            return
        user_id = msg.get("user", "")
        text = msg.get("text", "")
        if not text or user_id == self._bot_user_id:
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
