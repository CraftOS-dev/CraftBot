"""YouTube provider — multi-account provider for google_youtube integration.

API surface comes from ``YouTubeClient`` (all YouTube Data API
v3 methods live there and are unchanged); this class only rebinds its
credential plumbing to the injected per-account credential.
"""

from __future__ import annotations

from typing import List

from ...contracts import Operation
from .._google_common import YOUTUBE_SCOPES
from .client import YouTubeClient
from .._google import GoogleProviderBase, GoogleClientBinding
from .._shared import read_guidance
from .operations import build_operations


class BoundGoogleYoutubeClient(GoogleClientBinding, YouTubeClient):
    """YouTubeClient with per-account credential binding (see GoogleClientBinding)."""


class GoogleYoutubeProvider(GoogleProviderBase):
    id = "google_youtube"  # matches the platform_id / run_client name
    display_name = "YouTube"
    # ----- UI metadata -----
    description = "Channels, videos, playlists, and subscriptions"
    auth_type = "oauth"
    icon = "google_youtube"

    scopes = YOUTUBE_SCOPES
    client_cls = BoundGoogleYoutubeClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)
