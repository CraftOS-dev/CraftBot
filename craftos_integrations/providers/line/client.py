# -*- coding: utf-8 -*-
"""LINE Messaging API integration.

LINE delivers inbound messages via webhooks only - there is no long-poll
endpoint. The bot needs a public HTTPS URL registered in the LINE
Developers console to receive messages, which a desktop agent cannot
provide directly. This integration is therefore **send-only** out of the
box: ``send_message`` (push) and ``reply_message`` work; ``start_listening``
is not supported.

Credentials come from the LINE Developers console
(https://developers.line.biz/console/) under your provider → Messaging
API channel:
    - Channel access token (long-lived) - for the Authorization header.
    - Channel secret - used to verify webhook signatures (stored for
      future webhook-server use; not required for send-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ... import (
    BasePlatformClient,
    IntegrationSpec,
    has_credential,
    load_config,
    load_credential,
    register_client,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_DATA_API_BASE = "https://api-data.line.me/v2/bot"
LINE_OAUTH_API_BASE = "https://api.line.me/oauth2/v3"


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
    """``line.json`` → ``line_config.json``."""
    stem = LINE.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


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

    # ==================================================================
    # Generic message sending (any LINE message object — up to 5 per call)
    # ==================================================================

    def push_messages(
        self,
        to: str,
        messages: List[Dict[str, Any]],
        notification_disabled: Optional[bool] = None,
    ) -> Result:
        """Send up to 5 LINE message objects to a user/group/room.

        messages is a list of LINE-formatted message dicts, e.g.
        [{"type":"text","text":"Hi"}, {"type":"image","originalContentUrl":"...","previewImageUrl":"..."}].
        """
        cfg = self._config()
        nd = (
            cfg.notification_disabled
            if notification_disabled is None
            else notification_disabled
        )
        payload: Dict[str, Any] = {"to": to, "messages": messages}
        if nd:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/push",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def reply_messages(
        self,
        reply_token: str,
        messages: List[Dict[str, Any]],
        notification_disabled: Optional[bool] = None,
    ) -> Result:
        """Reply with up to 5 LINE message objects."""
        cfg = self._config()
        nd = (
            cfg.notification_disabled
            if notification_disabled is None
            else notification_disabled
        )
        payload: Dict[str, Any] = {"replyToken": reply_token, "messages": messages}
        if nd:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/reply",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def multicast_messages(
        self,
        to: List[str],
        messages: List[Dict[str, Any]],
        notification_disabled: Optional[bool] = None,
    ) -> Result:
        cfg = self._config()
        nd = (
            cfg.notification_disabled
            if notification_disabled is None
            else notification_disabled
        )
        payload: Dict[str, Any] = {"to": to, "messages": messages}
        if nd:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/multicast",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def broadcast_messages(
        self,
        messages: List[Dict[str, Any]],
        notification_disabled: Optional[bool] = None,
    ) -> Result:
        cfg = self._config()
        nd = (
            cfg.notification_disabled
            if notification_disabled is None
            else notification_disabled
        )
        payload: Dict[str, Any] = {"messages": messages}
        if nd:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/broadcast",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    # ----- Convenience builders for common message types -----

    def push_image(
        self,
        to: str,
        original_content_url: str,
        preview_image_url: Optional[str] = None,
    ) -> Result:
        msg: Dict[str, Any] = {
            "type": "image",
            "originalContentUrl": original_content_url,
            "previewImageUrl": preview_image_url or original_content_url,
        }
        return self.push_messages(to, [msg])

    def push_video(
        self, to: str, original_content_url: str, preview_image_url: str
    ) -> Result:
        msg: Dict[str, Any] = {
            "type": "video",
            "originalContentUrl": original_content_url,
            "previewImageUrl": preview_image_url,
        }
        return self.push_messages(to, [msg])

    def push_audio(
        self, to: str, original_content_url: str, duration_ms: int
    ) -> Result:
        msg: Dict[str, Any] = {
            "type": "audio",
            "originalContentUrl": original_content_url,
            "duration": duration_ms,
        }
        return self.push_messages(to, [msg])

    def push_location(
        self, to: str, title: str, address: str, latitude: float, longitude: float
    ) -> Result:
        msg: Dict[str, Any] = {
            "type": "location",
            "title": title,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
        }
        return self.push_messages(to, [msg])

    def push_sticker(self, to: str, package_id: str, sticker_id: str) -> Result:
        msg: Dict[str, Any] = {
            "type": "sticker",
            "packageId": package_id,
            "stickerId": sticker_id,
        }
        return self.push_messages(to, [msg])

    def push_flex(self, to: str, alt_text: str, contents: Dict[str, Any]) -> Result:
        """Send a Flex Message. contents is the Flex JSON structure."""
        msg: Dict[str, Any] = {
            "type": "flex",
            "altText": alt_text,
            "contents": contents,
        }
        return self.push_messages(to, [msg])

    def push_template(self, to: str, alt_text: str, template: Dict[str, Any]) -> Result:
        """Send a template message (buttons/confirm/carousel/image_carousel)."""
        msg: Dict[str, Any] = {
            "type": "template",
            "altText": alt_text,
            "template": template,
        }
        return self.push_messages(to, [msg])

    def push_imagemap(
        self,
        to: str,
        base_url: str,
        alt_text: str,
        base_width: int,
        base_height: int,
        actions: List[Dict[str, Any]],
    ) -> Result:
        msg: Dict[str, Any] = {
            "type": "imagemap",
            "baseUrl": base_url,
            "altText": alt_text,
            "baseSize": {"width": base_width, "height": base_height},
            "actions": actions,
        }
        return self.push_messages(to, [msg])

    # ==================================================================
    # Content retrieval (data plane)
    # ==================================================================

    def get_message_content(self, message_id: str, dest_path: str) -> Result:
        """Download the binary content of a user-sent image/video/audio/file message."""
        import httpx

        try:
            with httpx.stream(
                "GET",
                f"{LINE_DATA_API_BASE}/message/{message_id}/content",
                headers={
                    "Authorization": f"Bearer {self._load().channel_access_token}"
                },
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    return {
                        "error": f"Download failed: HTTP {resp.status_code}",
                        "details": resp.read().decode("utf-8", errors="replace")[:500],
                    }
                bytes_written = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
                        bytes_written += len(chunk)
                return {
                    "ok": True,
                    "result": {
                        "path": dest_path,
                        "bytes_written": bytes_written,
                        "mimetype": resp.headers.get("content-type", ""),
                    },
                }
        except (httpx.HTTPError, OSError) as e:
            return {"error": f"Download failed: {e}"}

    # ==================================================================
    # Group / room operations
    # ==================================================================

    def get_group_summary(self, group_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/group/{group_id}/summary",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def get_group_member_count(self, group_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/group/{group_id}/members/count",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def list_group_member_user_ids(
        self, group_id: str, start: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {}
        if start:
            params["start"] = start
        return http_request(
            "GET",
            f"{LINE_API_BASE}/group/{group_id}/members/ids",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params=params,
            expected=(200,),
        )

    def get_group_member_profile(self, group_id: str, user_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/group/{group_id}/member/{user_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def leave_group(self, group_id: str) -> Result:
        return http_request(
            "POST",
            f"{LINE_API_BASE}/group/{group_id}/leave",
            headers=self._headers(),
            expected=(200,),
            transform=lambda _d: {"left": True, "group_id": group_id},
        )

    def get_room_member_count(self, room_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/room/{room_id}/members/count",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def list_room_member_user_ids(
        self, room_id: str, start: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {}
        if start:
            params["start"] = start
        return http_request(
            "GET",
            f"{LINE_API_BASE}/room/{room_id}/members/ids",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params=params,
            expected=(200,),
        )

    def get_room_member_profile(self, room_id: str, user_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/room/{room_id}/member/{user_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def leave_room(self, room_id: str) -> Result:
        return http_request(
            "POST",
            f"{LINE_API_BASE}/room/{room_id}/leave",
            headers=self._headers(),
            expected=(200,),
            transform=lambda _d: {"left": True, "room_id": room_id},
        )

    # ==================================================================
    # Rich menus
    # ==================================================================

    def create_rich_menu(self, rich_menu: Dict[str, Any]) -> Result:
        """rich_menu is a RichMenu object: {size, selected, name, chatBarText, areas: [...]}."""
        return http_request(
            "POST",
            f"{LINE_API_BASE}/richmenu",
            headers=self._headers(),
            json=rich_menu,
            expected=(200,),
        )

    def get_rich_menu(self, rich_menu_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/richmenu/{rich_menu_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def list_rich_menus(self) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/richmenu/list",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def delete_rich_menu(self, rich_menu_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{LINE_API_BASE}/richmenu/{rich_menu_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
            transform=lambda _d: {"deleted": True, "rich_menu_id": rich_menu_id},
        )

    def upload_rich_menu_image(self, rich_menu_id: str, file_path: str) -> Result:
        """Upload PNG/JPEG image for a rich menu (data plane). Image must match the rich menu's size."""
        import os
        import mimetypes
        import httpx

        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}"}
        mime, _ = mimetypes.guess_type(file_path)
        if mime not in ("image/png", "image/jpeg"):
            return {
                "error": f"Unsupported image type {mime}; rich menu images must be PNG or JPEG"
            }
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            r = httpx.post(
                f"{LINE_DATA_API_BASE}/richmenu/{rich_menu_id}/content",
                headers={
                    "Authorization": f"Bearer {self._load().channel_access_token}",
                    "Content-Type": mime,
                },
                content=data,
                timeout=120.0,
            )
            if r.status_code != 200:
                return {
                    "error": f"Upload failed: HTTP {r.status_code}",
                    "details": r.text[:500],
                }
            return {
                "ok": True,
                "result": {"rich_menu_id": rich_menu_id, "size": len(data)},
            }
        except (httpx.HTTPError, OSError) as e:
            return {"error": str(e)}

    def set_default_rich_menu(self, rich_menu_id: str) -> Result:
        return http_request(
            "POST",
            f"{LINE_API_BASE}/user/all/richmenu/{rich_menu_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
            transform=lambda _d: {"set_default": True, "rich_menu_id": rich_menu_id},
        )

    def get_default_rich_menu(self) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/user/all/richmenu",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def cancel_default_rich_menu(self) -> Result:
        return http_request(
            "DELETE",
            f"{LINE_API_BASE}/user/all/richmenu",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
            transform=lambda _d: {"cancelled": True},
        )

    def link_rich_menu_to_user(self, user_id: str, rich_menu_id: str) -> Result:
        return http_request(
            "POST",
            f"{LINE_API_BASE}/user/{user_id}/richmenu/{rich_menu_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
            transform=lambda _d: {
                "linked": True,
                "user_id": user_id,
                "rich_menu_id": rich_menu_id,
            },
        )

    def unlink_rich_menu_from_user(self, user_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{LINE_API_BASE}/user/{user_id}/richmenu",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
            transform=lambda _d: {"unlinked": True, "user_id": user_id},
        )

    def get_user_rich_menu(self, user_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/user/{user_id}/richmenu",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def bulk_link_rich_menu(self, rich_menu_id: str, user_ids: List[str]) -> Result:
        """Link 1+ users (max 500) to a rich menu in one call."""
        return http_request(
            "POST",
            f"{LINE_API_BASE}/richmenu/bulk/link",
            headers=self._headers(),
            json={"richMenuId": rich_menu_id, "userIds": user_ids},
            expected=(202,),
            transform=lambda _d: {"queued": True, "count": len(user_ids)},
        )

    def bulk_unlink_rich_menu(self, user_ids: List[str]) -> Result:
        return http_request(
            "POST",
            f"{LINE_API_BASE}/richmenu/bulk/unlink",
            headers=self._headers(),
            json={"userIds": user_ids},
            expected=(202,),
            transform=lambda _d: {"queued": True, "count": len(user_ids)},
        )

    # ==================================================================
    # Narrowcast + Audiences
    # ==================================================================

    def send_narrowcast(
        self,
        messages: List[Dict[str, Any]],
        recipient: Optional[Dict[str, Any]] = None,
        demographic: Optional[Dict[str, Any]] = None,
        limit: Optional[Dict[str, Any]] = None,
        notification_disabled: Optional[bool] = None,
    ) -> Result:
        """Send a message to a filtered subset of friends. Returns a request ID; poll with get_narrowcast_progress."""
        cfg = self._config()
        nd = (
            cfg.notification_disabled
            if notification_disabled is None
            else notification_disabled
        )
        payload: Dict[str, Any] = {"messages": messages}
        if recipient is not None:
            payload["recipient"] = recipient
        if demographic is not None:
            payload["filter"] = {"demographic": demographic}
        if limit is not None:
            payload["limit"] = limit
        if nd:
            payload["notificationDisabled"] = True
        return http_request(
            "POST",
            f"{LINE_API_BASE}/message/narrowcast",
            headers=self._headers(),
            json=payload,
            expected=(202,),
            transform=lambda d: {
                "request_id": d.get("requestId") if d else None,
                "queued": True,
            },
        )

    def get_narrowcast_progress(self, request_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/message/progress/narrowcast",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params={"requestId": request_id},
            expected=(200,),
        )

    def create_user_id_audience(
        self,
        description: str,
        audiences: Optional[List[Dict[str, str]]] = None,
        is_ifa_audience: bool = False,
    ) -> Result:
        """Create an audience group from explicit user IDs. audiences: [{id: '<user_id>'}, ...]."""
        payload: Dict[str, Any] = {
            "description": description,
            "isIfaAudience": is_ifa_audience,
        }
        if audiences:
            payload["audiences"] = audiences
        return http_request(
            "POST",
            "https://api.line.me/v2/bot/audienceGroup/upload",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def update_audience_description(
        self, audience_group_id: int, description: str
    ) -> Result:
        return http_request(
            "PUT",
            f"{LINE_API_BASE}/audienceGroup/{audience_group_id}/updateDescription",
            headers=self._headers(),
            json={"description": description},
            expected=(200,),
            transform=lambda _d: {
                "updated": True,
                "audience_group_id": audience_group_id,
            },
        )

    def delete_audience(self, audience_group_id: int) -> Result:
        return http_request(
            "DELETE",
            f"{LINE_API_BASE}/audienceGroup/{audience_group_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
            transform=lambda _d: {
                "deleted": True,
                "audience_group_id": audience_group_id,
            },
        )

    def get_audience(self, audience_group_id: int) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/audienceGroup/{audience_group_id}",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def list_audiences(
        self,
        page: int = 1,
        size: int = 20,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Result:
        params: Dict[str, Any] = {"page": page, "size": min(size, 40)}
        if description:
            params["description"] = description
        if status:
            params["status"] = status
        return http_request(
            "GET",
            f"{LINE_API_BASE}/audienceGroup/list",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params=params,
            expected=(200,),
        )

    # ==================================================================
    # Insights
    # ==================================================================

    def get_number_of_followers(self, date: str) -> Result:
        """date: YYYYMMDD."""
        return http_request(
            "GET",
            f"{LINE_API_BASE}/insight/followers",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params={"date": date},
            expected=(200,),
        )

    def get_friend_demographics(self) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/insight/demographic",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def get_message_delivery_stats(self, date: str) -> Result:
        """Number of pushes/multicasts/broadcasts sent on a date (YYYYMMDD)."""
        return http_request(
            "GET",
            f"{LINE_API_BASE}/insight/message/delivery",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params={"date": date},
            expected=(200,),
        )

    def get_message_event_stats(self, request_id: str) -> Result:
        """Per-narrowcast/broadcast/multicast click/impression/open stats."""
        return http_request(
            "GET",
            f"{LINE_API_BASE}/insight/message/event",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params={"requestId": request_id},
            expected=(200,),
        )

    def get_user_interaction_stats(self, request_id: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/insight/message/event/aggregation",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            params={"customAggregationUnit": request_id},
            expected=(200,),
        )

    # ==================================================================
    # Webhook + channel-token admin
    # ==================================================================

    def set_webhook_endpoint(self, endpoint: str) -> Result:
        return http_request(
            "PUT",
            f"{LINE_API_BASE}/channel/webhook/endpoint",
            headers=self._headers(),
            json={"endpoint": endpoint},
            expected=(200,),
            transform=lambda _d: {"endpoint": endpoint, "updated": True},
        )

    def get_webhook_endpoint(self) -> Result:
        return http_request(
            "GET",
            f"{LINE_API_BASE}/channel/webhook/endpoint",
            headers={"Authorization": f"Bearer {self._load().channel_access_token}"},
            expected=(200,),
        )

    def test_webhook_endpoint(self, endpoint: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {}
        if endpoint:
            payload["endpoint"] = endpoint
        return http_request(
            "POST",
            f"{LINE_API_BASE}/channel/webhook/test",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def issue_channel_access_token(
        self, channel_id: str, channel_secret: str
    ) -> Result:
        """Issue a short-lived access token (v2.1) — useful for rotating credentials."""
        return http_request(
            "POST",
            f"{LINE_OAUTH_API_BASE}/token",
            data={
                "grant_type": "client_credentials",
                "client_id": channel_id,
                "client_secret": channel_secret,
            },
            expected=(200,),
        )

    def revoke_channel_access_token(self, access_token: str) -> Result:
        return http_request(
            "POST",
            f"{LINE_OAUTH_API_BASE}/revoke",
            data={"access_token": access_token},
            expected=(200,),
            transform=lambda _d: {"revoked": True},
        )

    def verify_access_token(self, access_token: str) -> Result:
        return http_request(
            "GET",
            f"{LINE_OAUTH_API_BASE}/verify",
            params={"access_token": access_token},
            expected=(200,),
        )
