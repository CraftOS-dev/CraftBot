"""YouTube provider — multi-account port of the legacy google_youtube integration.

API surface comes from the legacy ``YouTubeClient`` (all YouTube Data API
v3 methods live there and are unchanged); this class only rebinds its
credential plumbing to the injected per-account credential.
"""

from __future__ import annotations

from typing import List

from ...contracts import Operation
from ...integrations._google_common import YOUTUBE_SCOPES
from ...integrations.google_youtube import YouTubeClient
from .._google import GoogleProviderBase, GoogleClientBinding, read_guidance
from .operations import build_operations


class BoundGoogleYoutubeClient(GoogleClientBinding, YouTubeClient):
    """YouTubeClient with per-account credential binding (see GoogleClientBinding)."""


class GoogleYoutubeProvider(GoogleProviderBase):
    id = "google_youtube"  # matches legacy platform_id / run_client name
    display_name = "YouTube"
    scopes = YOUTUBE_SCOPES
    client_cls = BoundGoogleYoutubeClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)
