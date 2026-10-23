"""Google Docs provider — multi-account port of the granular Docs integration.

API surface comes from ``GoogleDocsClient`` (all Docs/Drive
REST methods live there and are unchanged); this class only rebinds its
credential plumbing to the injected per-account credential.

Drive authorization covers document content and file management. The
broad scope lets list/search find existing documents across Drive.
"""

from __future__ import annotations

from typing import List

from ...contracts import Operation
from .._google_common import DOCS_SCOPES
from .client import GoogleDocsClient
from .._google import GoogleProviderBase, GoogleClientBinding
from .._shared import read_guidance
from .operations import build_operations


class BoundGoogleDocsClient(GoogleClientBinding, GoogleDocsClient):
    """GoogleDocsClient with per-account credential binding (see GoogleClientBinding)."""


class GoogleDocsProvider(GoogleProviderBase):
    id = "google_docs"
    display_name = "Google Docs"
    # ----- UI metadata -----
    description = "Read, edit, and create documents"
    auth_type = "oauth"
    icon = "google_docs"

    scopes = DOCS_SCOPES
    client_cls = BoundGoogleDocsClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)
