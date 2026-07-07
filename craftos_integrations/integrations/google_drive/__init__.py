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
    run_google_list_accounts,
    run_google_login,
    run_google_logout,
    run_google_set_alias,
    run_google_set_primary,
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
        return await run_google_logout(self.spec, "Google Drive", args[0] if args else None)

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Google Drive")

    def list_accounts(self):
        return run_google_list_accounts(self.spec)

    async def set_primary(self, account_id: str) -> Tuple[bool, str]:
        return await run_google_set_primary(self.spec, "Google Drive", account_id)

    def set_alias(self, account_id: str, alias: str) -> Tuple[bool, str]:
        return run_google_set_alias(self.spec, account_id, alias)


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
        """Grant a Drive permission. Roles: reader, commenter, writer, owner.

        Kept for backwards compat — new code should use create_drive_permission
        which supports more types (group, domain, anyone) and notification opts.
        """
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions",
            headers=self._headers(),
            json={"type": "user", "role": role, "emailAddress": email},
        )

    # ----- Files (extended) -----

    def update_drive_file_metadata(
        self,
        file_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        starred: Optional[bool] = None,
        trashed: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if starred is not None:
            payload["starred"] = starred
        if trashed is not None:
            payload["trashed"] = trashed
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("name"),
                "trashed": d.get("trashed"),
            },
        )

    def copy_drive_file(
        self,
        file_id: str,
        name: Optional[str] = None,
        parent_folder_id: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name:
            payload["name"] = name
        if parent_folder_id:
            payload["parents"] = [parent_folder_id]
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{file_id}/copy",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("name"),
                "webViewLink": d.get("webViewLink"),
            },
        )

    def empty_drive_trash(self) -> Result:
        # Drive returns 200 with empty JSON {} for this endpoint, not 204.
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/trash",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda _d: {"emptied": True},
        )

    def get_drive_about(self) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/about",
            headers=self._auth_header(),
            params={
                "fields": "user,storageQuota,maxUploadSize,exportFormats,importFormats,canCreateDrives"
            },
            expected=(200,),
        )

    def upload_drive_file(
        self,
        file_path: str,
        name: Optional[str] = None,
        mime_type: Optional[str] = None,
        parent_folder_id: Optional[str] = None,
    ) -> Result:
        """Upload a local file to Drive. 2-step: create metadata, then PATCH content.

        Avoids multipart/related construction; works with the standard helper
        for the metadata step and uses httpx directly for the binary upload.
        """
        import os
        import mimetypes
        import httpx

        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}"}
        if not name:
            name = os.path.basename(file_path)
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"

        metadata: Dict[str, Any] = {"name": name}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        create_result = http_request(
            "POST",
            f"{DRIVE_API_BASE}/files",
            headers=self._headers(),
            json=metadata,
            expected=(200,),
        )
        if "error" in create_result:
            return create_result
        file_id = create_result["result"]["id"]

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            r = httpx.patch(
                f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media",
                headers={
                    "Authorization": f"Bearer {self._ensure_token()}",
                    "Content-Type": mime_type,
                },
                content=content,
                timeout=300.0,
            )
            if r.status_code != 200:
                return {"error": f"Upload error: {r.status_code}", "details": r.text}
            data = r.json()
            return {
                "ok": True,
                "result": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "mimeType": data.get("mimeType"),
                    "size": data.get("size"),
                    "webViewLink": data.get("webViewLink"),
                },
            }
        except Exception as e:
            return {"error": str(e)}

    def update_drive_file_content(
        self, file_id: str, file_path: str, mime_type: Optional[str] = None
    ) -> Result:
        """Replace a file's content with a local file."""
        import os
        import mimetypes
        import httpx

        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}"}
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            r = httpx.patch(
                f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media",
                headers={
                    "Authorization": f"Bearer {self._ensure_token()}",
                    "Content-Type": mime_type,
                },
                content=content,
                timeout=300.0,
            )
            if r.status_code != 200:
                return {"error": f"Upload error: {r.status_code}", "details": r.text}
            data = r.json()
            return {
                "ok": True,
                "result": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "modifiedTime": data.get("modifiedTime"),
                },
            }
        except Exception as e:
            return {"error": str(e)}

    def download_drive_file(self, file_id: str, save_to: str) -> Result:
        """Download a regular (non-Google-native) file to a local path."""
        import os
        import httpx

        try:
            r = httpx.get(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=self._auth_header(),
                params={"alt": "media"},
                timeout=300.0,
            )
            if r.status_code != 200:
                return {
                    "error": f"Download error: {r.status_code}",
                    "details": r.text[:500],
                }
            save_to = os.path.abspath(save_to)
            parent = os.path.dirname(save_to)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(save_to, "wb") as f:
                f.write(r.content)
            return {"ok": True, "result": {"saved_to": save_to, "size": len(r.content)}}
        except Exception as e:
            return {"error": str(e)}

    def export_drive_file(self, file_id: str, save_to: str, mime_type: str) -> Result:
        """Export a Google-native file (Doc/Sheet/Slide) to a local path as the target format.

        Common mime types:
          - application/pdf
          - application/vnd.openxmlformats-officedocument.wordprocessingml.document (.docx)
          - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet (.xlsx)
          - application/vnd.openxmlformats-officedocument.presentationml.presentation (.pptx)
          - text/plain, text/csv, text/html
        """
        import os
        import httpx

        try:
            r = httpx.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=self._auth_header(),
                params={"mimeType": mime_type},
                timeout=300.0,
            )
            if r.status_code != 200:
                return {
                    "error": f"Export error: {r.status_code}",
                    "details": r.text[:500],
                }
            save_to = os.path.abspath(save_to)
            parent = os.path.dirname(save_to)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(save_to, "wb") as f:
                f.write(r.content)
            return {
                "ok": True,
                "result": {
                    "saved_to": save_to,
                    "mimeType": mime_type,
                    "size": len(r.content),
                },
            }
        except Exception as e:
            return {"error": str(e)}

    # ----- Permissions (sharing) -----

    def list_drive_permissions(self, file_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions",
            headers=self._auth_header(),
            params={
                "fields": "permissions(id,type,emailAddress,role,domain,displayName)"
            },
            expected=(200,),
            transform=lambda d: {"permissions": d.get("permissions", [])},
        )

    def get_drive_permission(self, file_id: str, permission_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions/{permission_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def create_drive_permission(
        self,
        file_id: str,
        role: str,
        perm_type: str = "user",
        email_address: Optional[str] = None,
        domain: Optional[str] = None,
        send_notification: bool = True,
        email_message: Optional[str] = None,
    ) -> Result:
        """perm_type: user|group|domain|anyone. role: reader|commenter|writer|owner."""
        payload: Dict[str, Any] = {"role": role, "type": perm_type}
        if email_address:
            payload["emailAddress"] = email_address
        if domain:
            payload["domain"] = domain
        params: Dict[str, Any] = {
            "sendNotificationEmail": str(send_notification).lower()
        }
        if email_message:
            params["emailMessage"] = email_message
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions",
            headers=self._headers(),
            json=payload,
            params=params,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "role": d.get("role"),
                "type": d.get("type"),
            },
        )

    def update_drive_permission(
        self, file_id: str, permission_id: str, role: str
    ) -> Result:
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions/{permission_id}",
            headers=self._headers(),
            json={"role": role},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "role": d.get("role")},
        )

    def delete_drive_permission(self, file_id: str, permission_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{file_id}/permissions/{permission_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "permission_id": permission_id},
        )

    # ----- Comments -----

    def list_drive_comments(
        self, file_id: str, include_deleted: bool = False
    ) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/comments",
            headers=self._auth_header(),
            params={
                "fields": "comments(id,content,createdTime,modifiedTime,author,resolved,deleted,quotedFileContent)",
                "includeDeleted": str(include_deleted).lower(),
            },
            expected=(200,),
            transform=lambda d: {"comments": d.get("comments", [])},
        )

    def get_drive_comment(self, file_id: str, comment_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}",
            headers=self._auth_header(),
            params={
                "fields": "id,content,createdTime,modifiedTime,author,resolved,replies"
            },
            expected=(200,),
        )

    def create_drive_comment(
        self, file_id: str, content: str, anchor: Optional[str] = None
    ) -> Result:
        payload: Dict[str, Any] = {"content": content}
        if anchor:
            payload["anchor"] = anchor
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{file_id}/comments",
            headers=self._headers(),
            json=payload,
            params={"fields": "id,content,createdTime"},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "content": d.get("content")},
        )

    def update_drive_comment(
        self,
        file_id: str,
        comment_id: str,
        content: Optional[str] = None,
        resolved: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if resolved is not None:
            payload["resolved"] = resolved
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}",
            headers=self._headers(),
            json=payload,
            params={"fields": "id,content,resolved"},
            expected=(200,),
        )

    def delete_drive_comment(self, file_id: str, comment_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "comment_id": comment_id},
        )

    def list_drive_comment_replies(self, file_id: str, comment_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}/replies",
            headers=self._auth_header(),
            params={
                "fields": "replies(id,content,author,createdTime,modifiedTime,action,deleted)"
            },
            expected=(200,),
            transform=lambda d: {"replies": d.get("replies", [])},
        )

    def create_drive_comment_reply(
        self, file_id: str, comment_id: str, content: str
    ) -> Result:
        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}/replies",
            headers=self._headers(),
            json={"content": content},
            params={"fields": "id,content,createdTime"},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "content": d.get("content")},
        )

    def update_drive_comment_reply(
        self, file_id: str, comment_id: str, reply_id: str, content: str
    ) -> Result:
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}/replies/{reply_id}",
            headers=self._headers(),
            json={"content": content},
            params={"fields": "id,content"},
            expected=(200,),
        )

    def delete_drive_comment_reply(
        self, file_id: str, comment_id: str, reply_id: str
    ) -> Result:
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{file_id}/comments/{comment_id}/replies/{reply_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "reply_id": reply_id},
        )

    # ----- Revisions (version history) -----

    def list_drive_revisions(self, file_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/revisions",
            headers=self._auth_header(),
            params={
                "fields": "revisions(id,modifiedTime,keepForever,published,lastModifyingUser,size)"
            },
            expected=(200,),
            transform=lambda d: {"revisions": d.get("revisions", [])},
        )

    def get_drive_revision(self, file_id: str, revision_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/files/{file_id}/revisions/{revision_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def update_drive_revision(
        self,
        file_id: str,
        revision_id: str,
        keep_forever: Optional[bool] = None,
        published: Optional[bool] = None,
        publish_auto: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if keep_forever is not None:
            payload["keepForever"] = keep_forever
        if published is not None:
            payload["published"] = published
        if publish_auto is not None:
            payload["publishAuto"] = publish_auto
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{file_id}/revisions/{revision_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def delete_drive_revision(self, file_id: str, revision_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{file_id}/revisions/{revision_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "revision_id": revision_id},
        )

    # ----- Shared drives -----

    def list_shared_drives(
        self, page_size: int = 50, q: Optional[str] = None
    ) -> Result:
        params: Dict[str, Any] = {
            "pageSize": page_size,
            "fields": "drives(id,name,createdTime,colorRgb,hidden)",
        }
        if q:
            params["q"] = q
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/drives",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
            transform=lambda d: {"drives": d.get("drives", [])},
        )

    def get_shared_drive(self, drive_id: str) -> Result:
        return http_request(
            "GET",
            f"{DRIVE_API_BASE}/drives/{drive_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def create_shared_drive(self, name: str) -> Result:
        import uuid

        return http_request(
            "POST",
            f"{DRIVE_API_BASE}/drives",
            headers=self._headers(),
            json={"name": name},
            params={"requestId": str(uuid.uuid4())},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("name")},
        )

    def update_shared_drive(
        self, drive_id: str, name: Optional[str] = None, hidden: Optional[bool] = None
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if hidden is not None:
            payload["hidden"] = hidden
        return http_request(
            "PATCH",
            f"{DRIVE_API_BASE}/drives/{drive_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def delete_shared_drive(self, drive_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{DRIVE_API_BASE}/drives/{drive_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "drive_id": drive_id},
        )
