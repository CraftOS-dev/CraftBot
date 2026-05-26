# -*- coding: utf-8 -*-
"""YouTube - granular Google integration.

Connect just YouTube (without granting Gmail/Calendar/Drive/Docs scopes)
by clicking Connect on the YouTube card. Credential is saved to
``youtube.json``.

Scopes used:
  - ``youtube.readonly`` - list channels, fetch video metadata, search
  - ``youtube.force-ssl`` - required for any write op (subscribe, comment,
    rate, manage playlists). Same scope shape as the Workspace meta.

The YouTube Data API v3 is the only surface used; everything goes through
``https://www.googleapis.com/youtube/v3``.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    register_client,
    register_handler,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._google_common import (
    YOUTUBE_SCOPES,
    GoogleApiClientMixin,
    GoogleCredential,
    make_google_oauth,
    run_google_login,
    run_google_logout,
    run_google_status,
)

logger = get_logger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


YOUTUBE = IntegrationSpec(
    name="google_youtube",
    cred_class=GoogleCredential,
    cred_file="youtube.json",
    platform_id="google_youtube",
)


# -----------------------------------------------------------------
# Handler - auth flow only
# -----------------------------------------------------------------


@register_handler(YOUTUBE.name)
class YouTubeHandler(IntegrationHandler):
    spec = YOUTUBE
    display_name = "YouTube"
    description = "Channels, videos, playlists, and subscriptions"
    auth_type = "oauth"
    icon = "google_youtube"
    fields: List = []

    oauth = make_google_oauth(YOUTUBE_SCOPES)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_login(self.spec, self.oauth, "YouTube")

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_logout(self.spec, "YouTube")

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "YouTube")


# -----------------------------------------------------------------
# Client - YouTube REST methods (no listener)
# -----------------------------------------------------------------


@register_client
class YouTubeClient(GoogleApiClientMixin, BasePlatformClient):
    spec = YOUTUBE
    PLATFORM_ID = YOUTUBE.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[GoogleCredential] = None

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {"error": "YouTube does not support send_message"}

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def get_my_channel(self) -> Result:
        """Return the authenticated user's channel (id, title, stats)."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/channels",
            headers=self._auth_header(),
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            expected=(200,),
            transform=lambda d: (d.get("items") or [None])[0],
        )

    def search(
        self, query: str, max_results: int = 25, type_filter: str = "video"
    ) -> Result:
        """Search YouTube. ``type_filter`` is one of ``video|channel|playlist``."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/search",
            headers=self._auth_header(),
            params={
                "part": "snippet",
                "q": query,
                "maxResults": max_results,
                "type": type_filter,
            },
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )

    def get_video(self, video_id: str) -> Result:
        """Full metadata for a single video (snippet + stats + content details)."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/videos",
            headers=self._auth_header(),
            params={"part": "snippet,statistics,contentDetails", "id": video_id},
            expected=(200,),
            transform=lambda d: (d.get("items") or [None])[0],
        )

    def list_my_subscriptions(self, max_results: int = 50) -> Result:
        """Channels the authenticated user is subscribed to."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/subscriptions",
            headers=self._auth_header(),
            params={
                "part": "snippet",
                "mine": "true",
                "maxResults": max_results,
                "order": "alphabetical",
            },
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )

    def list_my_playlists(self, max_results: int = 50) -> Result:
        """Playlists owned by the authenticated user."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/playlists",
            headers=self._auth_header(),
            params={
                "part": "snippet,contentDetails",
                "mine": "true",
                "maxResults": max_results,
            },
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )

    def list_playlist_items(self, playlist_id: str, max_results: int = 50) -> Result:
        """Videos in a playlist."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/playlistItems",
            headers=self._auth_header(),
            params={
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": max_results,
            },
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )

    def subscribe(self, channel_id: str) -> Result:
        """Subscribe the authenticated user to a channel."""
        return http_request(
            "POST",
            f"{YOUTUBE_API_BASE}/subscriptions",
            headers=self._headers(),
            params={"part": "snippet"},
            json={
                "snippet": {
                    "resourceId": {"kind": "youtube#channel", "channelId": channel_id}
                }
            },
        )

    def unsubscribe(self, subscription_id: str) -> Result:
        """Remove a subscription. ``subscription_id`` is the id returned by
        ``list_my_subscriptions`` (NOT the channel id - it's the subscription
        relationship's own id)."""
        return http_request(
            "DELETE",
            f"{YOUTUBE_API_BASE}/subscriptions",
            headers=self._auth_header(),
            params={"id": subscription_id},
            expected=(204,),
            transform=lambda _d: {
                "unsubscribed": True,
                "subscription_id": subscription_id,
            },
        )

    def rate_video(self, video_id: str, rating: str) -> Result:
        """Like / dislike / clear rating. ``rating`` is one of
        ``like|dislike|none``."""
        return http_request(
            "POST",
            f"{YOUTUBE_API_BASE}/videos/rate",
            headers=self._auth_header(),
            params={"id": video_id, "rating": rating},
            expected=(204,),
            transform=lambda _d: {"video_id": video_id, "rating": rating},
        )

    def post_comment(self, video_id: str, text: str) -> Result:
        """Post a top-level comment on a video."""
        return http_request(
            "POST",
            f"{YOUTUBE_API_BASE}/commentThreads",
            headers=self._headers(),
            params={"part": "snippet"},
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}},
                },
            },
        )

    def get_video_comments(self, video_id: str, max_results: int = 50) -> Result:
        """Top-level comments on a video, most-recent first."""
        return http_request(
            "GET",
            f"{YOUTUBE_API_BASE}/commentThreads",
            headers=self._auth_header(),
            params={
                "part": "snippet",
                "videoId": video_id,
                "maxResults": max_results,
                "order": "time",
                "textFormat": "plainText",
            },
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )
