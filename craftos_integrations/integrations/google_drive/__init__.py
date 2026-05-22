# -*- coding: utf-8 -*-
"""Google Drive - granular Google integration.

Connect just Drive (without granting Gmail/Calendar/YouTube scopes) by
clicking Connect on the Google Drive card. Credential is saved to
``gdrive.json``.

Same per-service shape as ``gmail.py`` and ``google_calendar.py`` - the
only file-level differences are the scope, the API base URL, and the
REST surface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
    DRIVE_SCOPES,
    GoogleApiClientMixin,
    GoogleCredential,
    make_google_oauth,
    run_google_login,
    run_google_logout,
    run_google_status,
)

logger = get_logger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


GDRIVE = IntegrationSpec(
    name="google_drive",
    cred_class=GoogleCredential,
    cred_file="gdrive.json",
    platform_id="google_drive",
)


# -----------------------------------------------------------------
# Handler - auth flow only
# -----------------------------------------------------------------


@register_handler(GDRIVE.name)
class GoogleDriveHandler(IntegrationHandler):
    spec = GDRIVE
    display_name = "Google Drive"
    description = "Files, folders, and sharing"
    auth_type = "oauth"
    icon = "google_drive"
    fields: List = []

    oauth = make_google_oauth(DRIVE_SCOPES)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_login(self.spec, self.oauth, "Google Drive")

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_logout(self.spec, "Google Drive")

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Google Drive")


# -----------------------------------------------------------------
# Client - Drive REST methods (no listener; Drive isn't push-based)
# -----------------------------------------------------------------


@register_client
class GoogleDriveClient(GoogleApiClientMixin, BasePlatformClient):
    spec = GDRIVE
    PLATFORM_ID = GDRIVE.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[GoogleCredential] = None

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {"error": "Google Drive does not support send_message"}

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def list_drive_files(self, folder_id: str, fields: Optional[str] = None) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": fields or "files(id,name,mimeType,parents)",
            },
            expected=(200,),
            transform=lambda d: d.get("files", []),
        )

    def search_drive(
        self, query: str, max_results: int = 50, fields: Optional[str] = None
    ) -> Result:
        """Free-form search across all of Drive - uses Drive's q-query syntax."""
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={
                "q": query,
                "pageSize": max_results,
                "fields": fields or "files(id,name,mimeType,parents,modifiedTime)",
            },
            expected=(200,),
            transform=lambda d: d.get("files", []),
        )

    def create_drive_folder(
        self, name: str, parent_folder_id: Optional[str] = None
    ) -> Result:
        payload: Dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_folder_id:
            payload["parents"] = [parent_folder_id]
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files",
            headers=self._headers(),
            json=payload,
        )

    def get_drive_file(self, file_id: str, fields: Optional[str] = None) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers=self._auth_header(),
            params={
                "fields": fields or "id,name,mimeType,parents,modifiedTime,webViewLink"
            },
            expected=(200,),
        )

    def move_drive_file(
        self, file_id: str, add_parents: str, remove_parents: str
    ) -> Result:
        params: Dict[str, str] = {"addParents": add_parents, "fields": "id,parents"}
        if remove_parents:
            params["removeParents"] = remove_parents
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
        )

    def find_drive_folder_by_name(
        self, name: str, parent_folder_id: Optional[str] = None
    ) -> Result:
        q_parts = [
            f"name = '{name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false",
        ]
        if parent_folder_id:
            q_parts.append(f"'{parent_folder_id}' in parents")
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files",
            headers=self._auth_header(),
            params={"q": " and ".join(q_parts), "fields": "files(id,name)"},
            expected=(200,),
            transform=lambda d: (d.get("files") or [None])[0],
        )

    def delete_drive_file(self, file_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "file_id": file_id},
        )

    def share_drive_file(
        self, file_id: str, email: str, role: str = "reader"
    ) -> Result:
        """Grant a Drive permission. Roles: reader, commenter, writer, owner."""
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions",
            headers=self._headers(),
            json={"type": "user", "role": role, "emailAddress": email},
        )
