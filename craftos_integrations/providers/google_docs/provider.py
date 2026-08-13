"""Google Docs provider — multi-account port of the granular Docs integration.

API surface comes from the legacy ``GoogleDocsClient`` (all Docs/Drive
REST methods live there and are unchanged); this class only rebinds its
credential plumbing to the injected per-account credential.

Scopes mirror the legacy handler's ``make_google_oauth`` string
(``DOCS_AND_DRIVE_SCOPES`` = documents + full drive): the Docs scope
covers document bodies, and the broad Drive scope lets list/search find
docs the user already owns — not just files created by the integration.
"""

from __future__ import annotations

from typing import List

from ...contracts import Operation
from ...integrations.google_docs import DOCS_AND_DRIVE_SCOPES, GoogleDocsClient
from .._google import GoogleProviderBase, GoogleClientBinding, read_guidance
from .operations import build_operations


class BoundGoogleDocsClient(GoogleClientBinding, GoogleDocsClient):
    """GoogleDocsClient with per-account credential binding (see GoogleClientBinding)."""


class GoogleDocsProvider(GoogleProviderBase):
    id = "google_docs"
    display_name = "Google Docs"
    scopes = DOCS_AND_DRIVE_SCOPES
    client_cls = BoundGoogleDocsClient

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)
