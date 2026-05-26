# -*- coding: utf-8 -*-
"""Google Docs - granular Google integration.

Connect just Docs (without granting Gmail/Calendar/Drive/YouTube scopes)
by clicking Connect on the Google Docs card. Credential is saved to
``gdocs.json``.

Same per-service shape as ``gmail.py`` / ``google_calendar.py`` /
``google_drive.py``. Docs uses two API surfaces:
  - ``docs.googleapis.com/v1`` for document content (read/write structured)
  - ``drive.googleapis.com/v3`` for file-level ops (create/list/copy)
The Docs scope ``auth/documents`` covers the docs API; we additionally
request the full ``auth/drive`` scope so list/search can find docs the
user already owns (the narrower ``drive.file`` scope only sees files the
integration itself created, which is a frequent source of "I can see the
doc in Drive but the agent can't" complaints).
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
    DOCS_SCOPES,
    DRIVE_SCOPES,
    GoogleApiClientMixin,
    GoogleCredential,
    make_google_oauth,
    run_google_login,
    run_google_logout,
    run_google_status,
)

logger = get_logger(__name__)

DOCS_API_BASE = "https://docs.googleapis.com/v1"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

# Docs needs both the documents scope (read/write doc bodies) AND
# the full Drive scope so list/search hits docs the user already owns
# in their Drive - not just those created by this integration.
# Trade-off: this is a Google "restricted" scope; the OAuth consent
# screen shows an "unverified app" warning until the app is verified.
# Matches the scope shape used by google_drive.py.
DOCS_AND_DRIVE_SCOPES = f"{DOCS_SCOPES} {DRIVE_SCOPES}"


GDOCS = IntegrationSpec(
    name="google_docs",
    cred_class=GoogleCredential,
    cred_file="gdocs.json",
    platform_id="google_docs",
)


# -----------------------------------------------------------------
# Handler - auth flow only
# -----------------------------------------------------------------


@register_handler(GDOCS.name)
class GoogleDocsHandler(IntegrationHandler):
    spec = GDOCS
    display_name = "Google Docs"
    description = "Read, edit, and create documents"
    auth_type = "oauth"
    icon = "google_docs"
    fields: List = []

    oauth = make_google_oauth(DOCS_AND_DRIVE_SCOPES)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_login(self.spec, self.oauth, "Google Docs")

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_logout(self.spec, "Google Docs")

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Google Docs")


# -----------------------------------------------------------------
# Client - Docs REST methods (no listener)
# -----------------------------------------------------------------


@register_client
class GoogleDocsClient(GoogleApiClientMixin, BasePlatformClient):
    spec = GDOCS
    PLATFORM_ID = GDOCS.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[GoogleCredential] = None

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {"error": "Google Docs does not support send_message"}

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def create_document(self, title: str) -> Result:
        """Create a new blank Google Doc and return its metadata."""
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents",
            headers=self._headers(),
            json={"title": title},
            transform=lambda d: {
                "document_id": d.get("documentId"),
                "title": d.get("title"),
                "url": f"https://docs.google.com/document/d/{d.get('documentId')}/edit",
            },
        )

    def get_document(self, document_id: str) -> Result:
        """Read a document's full structured content (body + headers/footers)."""
        return http_request(
            "GET",
            f"{DOCS_API_BASE}/documents/{document_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def get_document_text(self, document_id: str) -> Result:
        """Plain-text view of a document - flattens the body into a single string."""
        result = self.get_document(document_id)
        if "error" in result:
            return result
        doc = result["result"]
        text_parts: List[str] = []
        for elem in doc.get("body", {}).get("content", []) or []:
            para = elem.get("paragraph")
            if not para:
                continue
            for run in para.get("elements") or []:
                tr = run.get("textRun")
                if tr and tr.get("content"):
                    text_parts.append(tr["content"])
        return {
            "ok": True,
            "result": {
                "document_id": document_id,
                "title": doc.get("title", ""),
                "text": "".join(text_parts),
            },
        }

    def append_text(self, document_id: str, text: str) -> Result:
        """Append text to the end of a document via batchUpdate."""
        # Get the doc to find its current end-index for insertion.
        result = self.get_document(document_id)
        if "error" in result:
            return result
        body = result["result"].get("body", {})
        end_index = (
            body.get("content", [{}])[-1].get("endIndex", 1)
            if body.get("content")
            else 1
        )
        # Insert just before the trailing newline (endIndex - 1).
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers(),
            json={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": max(1, end_index - 1)},
                            "text": text,
                        }
                    },
                ],
            },
            expected=(200,),
            transform=lambda _d: {"appended": True, "document_id": document_id},
        )

    def replace_text(
        self, document_id: str, find: str, replace: str, match_case: bool = False
    ) -> Result:
        """Find-and-replace across the entire document body."""
        return http_request(
            "POST",
            f"{DOCS_API_BASE}/documents/{document_id}:batchUpdate",
            headers=self._headers(),
            json={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {"text": find, "matchCase": match_case},
                            "replaceText": replace,
                        }
                    },
                ],
            },
            expected=(200,),
            transform=lambda d: {
                "document_id": document_id,
                "occurrences_changed": (
                    (d.get("replies") or [{}])[0]
                    .get("replaceAllText", {})
                    .get("occurrencesChanged", 0)
                ),
            },
        )

    def list_documents(self, max_results: int = 50) -> Result:
        """List Google Docs files the user owns or has access to."""
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={
                "q": "mimeType='application/vnd.google-apps.document' and trashed=false",
                "pageSize": max_results,
                "fields": "files(id,name,modifiedTime,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
            expected=(200,),
            transform=lambda d: d.get("files", []),
        )

    def search_documents(self, query: str, max_results: int = 50) -> Result:
        """Search for Google Docs by name. ``query`` is a fragment matched
        against the document title."""
        # Drive's q-query syntax: combine name contains with mimeType filter.
        q = (
            f"name contains '{query}' "
            "and mimeType='application/vnd.google-apps.document' "
            "and trashed=false"
        )
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={
                "q": q,
                "pageSize": max_results,
                "fields": "files(id,name,modifiedTime,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
            expected=(200,),
            transform=lambda d: d.get("files", []),
        )

    def delete_document(self, document_id: str) -> Result:
        """Delete a Google Doc (moves to Drive trash)."""
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{document_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "document_id": document_id},
        )
