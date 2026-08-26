"""Google Drive provider — multi-account provider for google_drive integration.

API surface comes from ``GoogleDriveClient`` (all Drive REST
methods live there and are unchanged); this class only rebinds its
credential plumbing to the injected per-account credential.
"""

from __future__ import annotations

from typing import List

from ...contracts import Operation
from .._google_common import DRIVE_SCOPES
from .client import GoogleDriveClient
from .._google import GoogleProviderBase, GoogleClientBinding
from .._shared import read_guidance
from .operations import build_operations


class BoundGoogleDriveClient(GoogleClientBinding, GoogleDriveClient):
    """GoogleDriveClient with per-account credential binding (see GoogleClientBinding)."""


class GoogleDriveProvider(GoogleProviderBase):
    id = "google_drive"
    display_name = "Google Drive"
    # ----- UI metadata -----
    description = "Files, folders, and sharing"
    auth_type = "oauth"
    icon = "google_drive"

    scopes = DRIVE_SCOPES
    client_cls = BoundGoogleDriveClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)
