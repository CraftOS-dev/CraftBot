# -*- coding: utf-8 -*-
"""Lark Drive integration - list/upload/download/move files in Lark Drive.

Lark Drive is the file-storage layer of the Lark workspace; it backs Lark
Docs, Sheets, Bitable, etc. (those services reference Drive ``file_token``
identifiers internally) but for this integration "Drive" means the user-
visible files-and-folders surface only.

Auth is the same Custom App that messaging uses - App ID + Secret minting a
``tenant_access_token`` - but each Lark service is registered as its own
sibling integration (matches the ``google_*.py`` pattern). The user pastes
the same App ID + Secret here as in ``/lark login``; the only effective
difference is the cred file (``lark_drive.json`` vs ``lark.json``) and the
permissions enabled on the app.

Required Lark permissions (Permissions & Scopes tab on the Custom App):
  - ``drive:drive`` (full read-write) OR ``drive:drive:readonly`` (read-only)
  - ``drive:file:upload`` (only if you want to upload via this integration)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ... import (
    BasePlatformClient,
    IntegrationSpec,
    has_credential,
    load_credential,
    register_client,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._lark_common import (
    LARK_API_BASE,
    LarkCredential,
    ensure_token,
    make_headers,
)

logger = get_logger(__name__)


LARK_DRIVE = IntegrationSpec(
    name="lark_drive",
    cred_class=LarkCredential,
    cred_file="lark_drive.json",
    platform_id="lark_drive",
)


@register_client
class LarkDriveClient(BasePlatformClient):
    spec = LARK_DRIVE
    PLATFORM_ID = LARK_DRIVE.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[LarkCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> LarkCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, LarkCredential)
        if self._cred is None:
            raise RuntimeError(
                "No Lark Drive credentials. Use /lark_drive login first."
            )
        return self._cred

    def _headers(self) -> Dict[str, str]:
        return make_headers(self._load(), self.spec.cred_file)

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {"error": "Lark Drive does not support send_message"}

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def list_files(
        self, folder_token: str = "", page_size: int = 50, page_token: str = ""
    ) -> Result:
        """List files in a folder. Empty ``folder_token`` lists the root.

        Pagination: pass the returned ``next_page_token`` back as ``page_token``
        until ``has_more`` is False.
        """
        params: Dict[str, str] = {"page_size": str(min(page_size, 200))}
        if folder_token:
            params["folder_token"] = folder_token
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/files",
            params=params,
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_file_metadata(
        self, file_tokens: List[str], doc_type: str = "file"
    ) -> Result:
        """Batch-fetch metadata for one or more file tokens.

        ``doc_type`` is one of: ``doc`` (legacy Doc), ``docx`` (new Doc),
        ``sheet``, ``bitable``, ``mindnote``, ``file`` (regular file),
        ``slides``. Mixed-type batches are allowed by passing a list of
        ``{doc_token, doc_type}`` pairs via ``request_docs`` directly to
        the API instead of going through this convenience method.
        """
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/metas/batch_query",
            headers=self._headers(),
            json={
                "request_docs": [
                    {"doc_token": t, "doc_type": doc_type} for t in file_tokens
                ]
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_folder(self, name: str, parent_folder_token: str = "") -> Result:
        """Create a new folder. Empty ``parent_folder_token`` creates at the root."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/files/create_folder",
            headers=self._headers(),
            json={"name": name, "folder_token": parent_folder_token},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def upload_file(
        self, file_path: str, parent_folder_token: str, file_name: str = ""
    ) -> Result:
        """Upload a file (max 20MB) to a folder.

        Lark's upload_all endpoint is multipart/form-data with the file size
        as a form field - the SDK quirk is the size has to be a string. For
        files >20MB the API requires the chunked upload_prepare/upload_part/
        upload_finish flow, which this method does NOT handle.
        """
        import os

        if not file_name:
            file_name = os.path.basename(file_path)
        size = os.path.getsize(file_path)
        if size > 20 * 1024 * 1024:
            return {
                "error": f"File too large ({size} bytes). Use chunked "
                "upload for files >20MB (not yet implemented)."
            }
        with open(file_path, "rb") as f:
            file_data = f.read()
        # Multipart form: file_name, parent_type=explorer, parent_node, size, file
        # The token bearer is added via Authorization header; Content-Type is
        # set by the multipart encoder, NOT our default JSON.
        token = ensure_token(self._load(), self.spec.cred_file)
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/files/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": file_name,
                "parent_type": "explorer",
                "parent_node": parent_folder_token,
                "size": str(size),
            },
            files={"file": (file_name, file_data)},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def download_file(self, file_token: str, dest_path: str) -> Result:
        """Download a file by its token to ``dest_path`` on disk.

        Returns ``{ok, result: {path, bytes_written}}`` on success.
        """
        token = ensure_token(self._load(), self.spec.cred_file)
        # http_request returns parsed JSON - for a binary download we use
        # transform=None and read the raw bytes off the response. Easier
        # path: do a raw httpx call here to avoid teaching the helper
        # about binary responses.
        import httpx

        try:
            with httpx.stream(
                "GET",
                f"{LARK_API_BASE}/drive/v1/files/{file_token}/download",
                headers={"Authorization": f"Bearer {token}"},
                timeout=60.0,
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
                    "result": {"path": dest_path, "bytes_written": bytes_written},
                }
        except (httpx.HTTPError, OSError) as e:
            return {"error": f"Download failed: {e}"}

    def delete_file(self, file_token: str, file_type: str = "file") -> Result:
        """Delete a file or folder by token.

        ``file_type`` is one of: ``file``, ``folder``, ``doc``, ``docx``,
        ``sheet``, ``bitable``, ``mindnote``, ``shortcut``, ``slides``.
        """
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}",
            params={"type": file_type},
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def search_files(self, search_key: str, count: int = 20) -> Result:
        """Full-text search across files the bot has access to."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v2/files/search_app",
            headers=self._headers(),
            json={"search_key": search_key, "count": min(count, 50)},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ------------------------------------------------------------------
    # Drive: copy / move / versions / shortcuts / stats
    # ------------------------------------------------------------------

    def copy_file(
        self, file_token: str, name: str, folder_token: str, copy_type: str = "file"
    ) -> Result:
        """Copy a file to a folder. copy_type: file | folder | doc | docx | sheet | bitable | mindnote | slides."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/copy",
            headers=self._headers(),
            json={"name": name, "type": copy_type, "folder_token": folder_token},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def move_file(
        self, file_token: str, target_folder_token: str, file_type: str = "file"
    ) -> Result:
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/move",
            headers=self._headers(),
            json={"type": file_type, "folder_token": target_folder_token},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_file_versions(
        self,
        file_token: str,
        file_type: str = "docx",
        page_size: int = 50,
        page_token: str = "",
    ) -> Result:
        """List version history. file_type: docx | doc | sheet."""
        params: Dict[str, str] = {
            "obj_type": file_type,
            "page_size": str(min(page_size, 50)),
        }
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/versions",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def file_statistics(self, file_token: str, file_type: str = "docx") -> Result:
        """View/like/comment stats. file_type: docx | doc | sheet | bitable | file."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/statistics",
            headers=self._headers(),
            params={"file_type": file_type},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ------------------------------------------------------------------
    # Drive Permissions (sharing)
    # ------------------------------------------------------------------

    def list_permission_members(
        self, file_token: str, file_type: str = "docx"
    ) -> Result:
        """List who has access. file_type: doc | docx | sheet | bitable | file | folder | mindnote | slides."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/permissions/{file_token}/members",
            headers=self._headers(),
            params={"type": file_type},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def add_permission_member(
        self,
        file_token: str,
        member_type: str,
        member_id: str,
        perm: str,
        file_type: str = "docx",
        perm_type: str = "container",
        notify_lark: bool = False,
    ) -> Result:
        """Grant access. member_type: email|openid|userid|unionid|chatid|departmentid|openchat|opendepartment|userid|groupid. perm: view|edit|full_access. perm_type: container|single_page."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/permissions/{file_token}/members",
            headers=self._headers(),
            params={"type": file_type, "need_notification": str(notify_lark).lower()},
            json={
                "member_type": member_type,
                "member_id": member_id,
                "perm": perm,
                "perm_type": perm_type,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_permission_member(
        self,
        file_token: str,
        member_id: str,
        member_type: str,
        perm: str,
        file_type: str = "docx",
        perm_type: str = "container",
        notify_lark: bool = False,
    ) -> Result:
        return http_request(
            "PUT",
            f"{LARK_API_BASE}/drive/v1/permissions/{file_token}/members/{member_id}",
            headers=self._headers(),
            params={"type": file_type, "need_notification": str(notify_lark).lower()},
            json={"member_type": member_type, "perm": perm, "perm_type": perm_type},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_permission_member(
        self, file_token: str, member_id: str, member_type: str, file_type: str = "docx"
    ) -> Result:
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/drive/v1/permissions/{file_token}/members/{member_id}",
            headers=self._headers(),
            params={"type": file_type, "member_type": member_type},
            expected=(200,),
            transform=lambda d: d.get(
                "data", {"removed": True, "member_id": member_id}
            ),
        )

    def get_public_permission(self, file_token: str, file_type: str = "docx") -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v2/permissions/{file_token}/public",
            headers=self._headers(),
            params={"type": file_type},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_public_permission(
        self,
        file_token: str,
        file_type: str = "docx",
        external_access_entity: Optional[str] = None,
        security_entity: Optional[str] = None,
        comment_entity: Optional[str] = None,
        share_entity: Optional[str] = None,
        link_share_entity: Optional[str] = None,
        invite_external: Optional[bool] = None,
    ) -> Result:
        """Update public-link settings. Values like 'tenant_readable', 'anyone_readable', 'anyone_editable', 'closed', etc. — see Lark docs for the exact enum per field."""
        payload: Dict[str, Any] = {}
        if external_access_entity is not None:
            payload["external_access_entity"] = external_access_entity
        if security_entity is not None:
            payload["security_entity"] = security_entity
        if comment_entity is not None:
            payload["comment_entity"] = comment_entity
        if share_entity is not None:
            payload["share_entity"] = share_entity
        if link_share_entity is not None:
            payload["link_share_entity"] = link_share_entity
        if invite_external is not None:
            payload["invite_external"] = invite_external
        return http_request(
            "PATCH",
            f"{LARK_API_BASE}/drive/v2/permissions/{file_token}/public",
            headers=self._headers(),
            params={"type": file_type},
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def transfer_owner(
        self,
        file_token: str,
        member_type: str,
        member_id: str,
        file_type: str = "docx",
        remove_old_owner: bool = False,
    ) -> Result:
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/permissions/{file_token}/members/transfer_owner",
            headers=self._headers(),
            params={
                "type": file_type,
                "need_notification": "true",
                "remove_old_owner": str(remove_old_owner).lower(),
            },
            json={"member_type": member_type, "member_id": member_id},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ------------------------------------------------------------------
    # Drive Comments (and replies)
    # ------------------------------------------------------------------

    def list_comments(
        self,
        file_token: str,
        file_type: str = "docx",
        is_whole: bool = True,
        page_size: int = 100,
        page_token: str = "",
    ) -> Result:
        """is_whole=True returns whole-document comments; False returns anchored ones."""
        params: Dict[str, str] = {
            "file_type": file_type,
            "is_whole": str(is_whole).lower(),
            "page_size": str(min(page_size, 100)),
        }
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_comment(
        self,
        file_token: str,
        content_elements: List[Dict[str, Any]],
        file_type: str = "docx",
    ) -> Result:
        """content_elements is a list of rich-text element dicts (text_run, mention, link, etc.)."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments",
            headers=self._headers(),
            params={"file_type": file_type},
            json={
                "reply_list": {"replies": [{"content": {"elements": content_elements}}]}
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_comment(
        self, file_token: str, comment_id: str, file_type: str = "docx"
    ) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments/{comment_id}",
            headers=self._headers(),
            params={"file_type": file_type},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def resolve_comment(
        self,
        file_token: str,
        comment_id: str,
        file_type: str = "docx",
        is_solved: bool = True,
    ) -> Result:
        return http_request(
            "PATCH",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments/{comment_id}",
            headers=self._headers(),
            params={"file_type": file_type},
            json={"is_solved": is_solved},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_comment_replies(
        self,
        file_token: str,
        comment_id: str,
        file_type: str = "docx",
        page_size: int = 100,
    ) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments/{comment_id}/replies",
            headers=self._headers(),
            params={"file_type": file_type, "page_size": str(min(page_size, 100))},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_comment_reply(
        self,
        file_token: str,
        comment_id: str,
        reply_id: str,
        content_elements: List[Dict[str, Any]],
        file_type: str = "docx",
    ) -> Result:
        return http_request(
            "PUT",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments/{comment_id}/replies/{reply_id}",
            headers=self._headers(),
            params={"file_type": file_type},
            json={"content": {"elements": content_elements}},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_comment_reply(
        self, file_token: str, comment_id: str, reply_id: str, file_type: str = "docx"
    ) -> Result:
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/drive/v1/files/{file_token}/comments/{comment_id}/replies/{reply_id}",
            headers=self._headers(),
            params={"file_type": file_type},
            expected=(200,),
            transform=lambda d: d.get("data", {"deleted": True, "reply_id": reply_id}),
        )

    # ------------------------------------------------------------------
    # Drive Import / Export tasks
    # ------------------------------------------------------------------

    def create_import_task(
        self,
        file_extension: str,
        file_name: str,
        file_token: str,
        file_type: str,
        point_type: str = "ccm_import_open_platform",
        folder_token: str = "",
    ) -> Result:
        """Convert a regular file token into a Doc/Sheet/Bitable.

        file_extension: docx | pdf | csv | xlsx ... ; file_type: docx | sheet | bitable
        """
        payload: Dict[str, Any] = {
            "file_extension": file_extension,
            "file_name": file_name,
            "file_token": file_token,
            "type": file_type,
            "point": {"mount_type": 1, "mount_key": folder_token},
        }
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/import_tasks",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_import_task(self, ticket: str) -> Result:
        """Poll a previously-created import task. Returns job_status + result_token when done."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/import_tasks/{ticket}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_export_task(
        self, file_extension: str, file_token: str, file_type: str, sub_id: str = ""
    ) -> Result:
        """Convert a Doc/Sheet/Bitable into a regular file. Returns a ticket.

        file_extension: docx | pdf | csv | xlsx
        file_type: docx | sheet | bitable
        """
        payload: Dict[str, Any] = {
            "file_extension": file_extension,
            "token": file_token,
            "type": file_type,
        }
        if sub_id:
            payload["sub_id"] = sub_id
        return http_request(
            "POST",
            f"{LARK_API_BASE}/drive/v1/export_tasks",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_export_task(self, ticket: str, file_token: str) -> Result:
        """Poll export task. When done, response contains file_token of the result blob."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/drive/v1/export_tasks/{ticket}",
            headers=self._headers(),
            params={"token": file_token},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def download_export(self, result_file_token: str, dest_path: str) -> Result:
        """Download the file blob produced by a finished export task."""
        token = ensure_token(self._load(), self.spec.cred_file)
        import httpx

        try:
            with httpx.stream(
                "GET",
                f"{LARK_API_BASE}/drive/v1/export_tasks/file/{result_file_token}/download",
                headers={"Authorization": f"Bearer {token}"},
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
                    "result": {"path": dest_path, "bytes_written": bytes_written},
                }
        except (httpx.HTTPError, OSError) as e:
            return {"error": f"Download failed: {e}"}

    # ==================================================================
    # Docx (new Docs) — documents + blocks
    # ==================================================================

    def create_document(self, title: str = "", folder_token: str = "") -> Result:
        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        if folder_token:
            payload["folder_token"] = folder_token
        return http_request(
            "POST",
            f"{LARK_API_BASE}/docx/v1/documents",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_document(self, document_id: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_document_raw_content(self, document_id: str, lang: int = 0) -> Result:
        """Returns the doc's plain-text representation. lang: 0=default, 1=en, 2=zh, 3=ja."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/raw_content",
            headers=self._headers(),
            params={"lang": lang},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_document_blocks(
        self,
        document_id: str,
        page_size: int = 500,
        page_token: str = "",
        document_revision_id: int = -1,
    ) -> Result:
        params: Dict[str, str] = {
            "page_size": str(min(page_size, 500)),
            "document_revision_id": str(document_revision_id),
        }
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/blocks",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_document_block(
        self, document_id: str, block_id: str, document_revision_id: int = -1
    ) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/blocks/{block_id}",
            headers=self._headers(),
            params={"document_revision_id": str(document_revision_id)},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_document_block_children(
        self,
        document_id: str,
        block_id: str,
        children: List[Dict[str, Any]],
        index: int = -1,
        document_revision_id: int = -1,
    ) -> Result:
        """Insert children blocks under a parent. block_id is the parent; use the document_id for top-level inserts."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/blocks/{block_id}/children",
            headers=self._headers(),
            params={"document_revision_id": str(document_revision_id)},
            json={"children": children, "index": index},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_document_block(
        self,
        document_id: str,
        block_id: str,
        update_payload: Dict[str, Any],
        document_revision_id: int = -1,
    ) -> Result:
        """update_payload uses Docx's update structures: {update_text_elements: {...}} / {update_table_property: {...}} / etc."""
        return http_request(
            "PATCH",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/blocks/{block_id}",
            headers=self._headers(),
            params={"document_revision_id": str(document_revision_id)},
            json=update_payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_update_document_blocks(
        self,
        document_id: str,
        requests: List[Dict[str, Any]],
        document_revision_id: int = -1,
    ) -> Result:
        """One round-trip multi-block update. requests is a list of {block_id, ...update_fields}."""
        return http_request(
            "PATCH",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/blocks/batch_update",
            headers=self._headers(),
            params={"document_revision_id": str(document_revision_id)},
            json={"requests": requests},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_document_blocks(
        self,
        document_id: str,
        block_id: str,
        start_index: int,
        end_index: int,
        document_revision_id: int = -1,
    ) -> Result:
        """Delete a contiguous range of children of block_id (half-open [start_index, end_index))."""
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/docx/v1/documents/{document_id}/blocks/{block_id}/children/batch_delete",
            headers=self._headers(),
            params={"document_revision_id": str(document_revision_id)},
            json={"start_index": start_index, "end_index": end_index},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ==================================================================
    # Sheets (Spreadsheets + values)
    # ==================================================================

    def create_spreadsheet(self, title: str = "", folder_token: str = "") -> Result:
        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        if folder_token:
            payload["folder_token"] = folder_token
        return http_request(
            "POST",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_spreadsheet(self, spreadsheet_token: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_spreadsheet_title(self, spreadsheet_token: str, title: str) -> Result:
        return http_request(
            "PATCH",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}",
            headers=self._headers(),
            json={"title": title},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_spreadsheet_sheets(self, spreadsheet_token: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_spreadsheet_sheet(self, spreadsheet_token: str, sheet_id: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/{sheet_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_sheet_values(
        self,
        spreadsheet_token: str,
        range_: str,
        value_render_option: str = "ToString",
        date_time_render_option: str = "FormattedString",
    ) -> Result:
        """range_ format: '<sheetId>!A1:D10'."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_}",
            headers=self._headers(),
            params={
                "valueRenderOption": value_render_option,
                "dateTimeRenderOption": date_time_render_option,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_get_sheet_values(
        self,
        spreadsheet_token: str,
        ranges: List[str],
        value_render_option: str = "ToString",
    ) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values_batch_get",
            headers=self._headers(),
            params={
                "ranges": ",".join(ranges),
                "valueRenderOption": value_render_option,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_sheet_values(
        self, spreadsheet_token: str, range_: str, values: List[List[Any]]
    ) -> Result:
        """Write a 2D values array into range_ (overwriting). values e.g. [['A1','B1'],['A2','B2']]."""
        return http_request(
            "PUT",
            f"{LARK_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values",
            headers=self._headers(),
            json={"valueRange": {"range": range_, "values": values}},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def append_sheet_values(
        self,
        spreadsheet_token: str,
        range_: str,
        values: List[List[Any]],
        insert_data_option: str = "OVERWRITE",
    ) -> Result:
        """Append rows after the last filled row in range_. insert_data_option: OVERWRITE | INSERT_ROWS."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values_append",
            headers=self._headers(),
            params={"insertDataOption": insert_data_option},
            json={"valueRange": {"range": range_, "values": values}},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_update_sheet_values(
        self, spreadsheet_token: str, value_ranges: List[Dict[str, Any]]
    ) -> Result:
        """Multiple writes in one call. value_ranges: [{range, values}, ...]."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values_batch_update",
            headers=self._headers(),
            json={"valueRanges": value_ranges},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def find_in_sheet(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        find_text: str,
        range_: str,
        match_case: bool = False,
        match_entire_cell: bool = False,
        search_by_regex: bool = False,
        include_formulas: bool = False,
    ) -> Result:
        return http_request(
            "POST",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/{sheet_id}/find",
            headers=self._headers(),
            json={
                "find_condition": {
                    "range": range_,
                    "match_case": match_case,
                    "match_entire_cell": match_entire_cell,
                    "search_by_regex": search_by_regex,
                    "include_formulas": include_formulas,
                },
                "find": find_text,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def replace_in_sheet(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        find_text: str,
        replacement: str,
        range_: str,
        match_case: bool = False,
        match_entire_cell: bool = False,
        search_by_regex: bool = False,
        include_formulas: bool = False,
    ) -> Result:
        return http_request(
            "POST",
            f"{LARK_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/{sheet_id}/replace",
            headers=self._headers(),
            json={
                "find_condition": {
                    "range": range_,
                    "match_case": match_case,
                    "match_entire_cell": match_entire_cell,
                    "search_by_regex": search_by_regex,
                    "include_formulas": include_formulas,
                },
                "find": find_text,
                "replacement": replacement,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def insert_sheet_dimension_range(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        major_dimension: str,
        start_index: int,
        end_index: int,
        inherit_style: str = "BEFORE",
    ) -> Result:
        """Insert rows/columns. major_dimension: ROWS | COLUMNS. inherit_style: BEFORE | AFTER."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/insert_dimension_range",
            headers=self._headers(),
            json={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": major_dimension,
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "inheritStyle": inherit_style,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ==================================================================
    # Bitable (Base) — apps + tables + records + fields
    # ==================================================================

    def create_bitable_app(
        self, name: str = "", folder_token: str = "", time_zone: str = "Asia/Shanghai"
    ) -> Result:
        payload: Dict[str, Any] = {"time_zone": time_zone}
        if name:
            payload["name"] = name
        if folder_token:
            payload["folder_token"] = folder_token
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_bitable_app(self, app_token: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_bitable_app(
        self,
        app_token: str,
        name: Optional[str] = None,
        is_advanced: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if is_advanced is not None:
            payload["is_advanced"] = is_advanced
        return http_request(
            "PUT",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_bitable_tables(
        self, app_token: str, page_size: int = 100, page_token: str = ""
    ) -> Result:
        params: Dict[str, str] = {"page_size": str(min(page_size, 100))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_bitable_table(
        self,
        app_token: str,
        name: str,
        default_view_name: Optional[str] = None,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> Result:
        payload_table: Dict[str, Any] = {"name": name}
        if default_view_name:
            payload_table["default_view_name"] = default_view_name
        if fields:
            payload_table["fields"] = fields
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables",
            headers=self._headers(),
            json={"table": payload_table},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_bitable_table(self, app_token: str, table_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", {"deleted": True, "table_id": table_id}),
        )

    def list_bitable_records(
        self,
        app_token: str,
        table_id: str,
        view_id: str = "",
        page_size: int = 100,
        page_token: str = "",
        field_names: Optional[List[str]] = None,
    ) -> Result:
        params: Dict[str, str] = {"page_size": str(min(page_size, 500))}
        if view_id:
            params["view_id"] = view_id
        if page_token:
            params["page_token"] = page_token
        if field_names:
            params["field_names"] = ",".join(f'"{n}"' for n in field_names)
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_bitable_record(
        self, app_token: str, table_id: str, record_id: str
    ) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_bitable_record(
        self, app_token: str, table_id: str, fields: Dict[str, Any]
    ) -> Result:
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            headers=self._headers(),
            json={"fields": fields},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_bitable_record(
        self, app_token: str, table_id: str, record_id: str, fields: Dict[str, Any]
    ) -> Result:
        return http_request(
            "PUT",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            headers=self._headers(),
            json={"fields": fields},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_bitable_record(
        self, app_token: str, table_id: str, record_id: str
    ) -> Result:
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get(
                "data", {"deleted": True, "record_id": record_id}
            ),
        )

    def batch_create_bitable_records(
        self, app_token: str, table_id: str, records: List[Dict[str, Any]]
    ) -> Result:
        """records: [{fields: {...}}, ...]."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
            headers=self._headers(),
            json={"records": records},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_update_bitable_records(
        self, app_token: str, table_id: str, records: List[Dict[str, Any]]
    ) -> Result:
        """records: [{record_id, fields}, ...]."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
            headers=self._headers(),
            json={"records": records},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_delete_bitable_records(
        self, app_token: str, table_id: str, record_ids: List[str]
    ) -> Result:
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete",
            headers=self._headers(),
            json={"records": record_ids},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def search_bitable_records(
        self,
        app_token: str,
        table_id: str,
        filter_obj: Optional[Dict[str, Any]] = None,
        sort: Optional[List[Dict[str, Any]]] = None,
        field_names: Optional[List[str]] = None,
        view_id: str = "",
        page_size: int = 100,
        page_token: str = "",
    ) -> Result:
        """Filtered/sorted record search. filter_obj uses Bitable's conjunction/conditions syntax."""
        payload: Dict[str, Any] = {}
        if filter_obj is not None:
            payload["filter"] = filter_obj
        if sort is not None:
            payload["sort"] = sort
        if field_names is not None:
            payload["field_names"] = field_names
        if view_id:
            payload["view_id"] = view_id
        params: Dict[str, str] = {"page_size": str(min(page_size, 500))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
            headers=self._headers(),
            params=params,
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_bitable_fields(
        self,
        app_token: str,
        table_id: str,
        view_id: str = "",
        page_size: int = 100,
        page_token: str = "",
    ) -> Result:
        params: Dict[str, str] = {"page_size": str(min(page_size, 100))}
        if view_id:
            params["view_id"] = view_id
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_bitable_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        field_type: int,
        property: Optional[Dict[str, Any]] = None,
        description: Optional[Dict[str, Any]] = None,
    ) -> Result:
        """field_type: 1=Text, 2=Number, 3=SingleSelect, 4=MultiSelect, 5=DateTime, 7=Checkbox, 11=User, 13=Phone, 15=URL, 17=Attachment, 18=Link, 19=Lookup, 20=Formula, 21=DuplicateLookup, 22=Location, 23=Group, 1001=CreatedTime, 1002=ModifiedTime, 1003=CreatedUser, 1004=ModifiedUser, 1005=AutoNumber."""
        payload: Dict[str, Any] = {
            "field_name": field_name,
            "type": field_type,
        }
        if property is not None:
            payload["property"] = property
        if description is not None:
            payload["description"] = description
        return http_request(
            "POST",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_bitable_views(
        self, app_token: str, table_id: str, page_size: int = 100
    ) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/views",
            headers=self._headers(),
            params={"page_size": str(min(page_size, 100))},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ==================================================================
    # Wiki spaces + nodes
    # ==================================================================

    def list_wiki_spaces(self, page_size: int = 50, page_token: str = "") -> Result:
        params: Dict[str, str] = {"page_size": str(min(page_size, 50))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/wiki/v2/spaces",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_wiki_space(self, space_id: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/wiki/v2/spaces/{space_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def list_wiki_nodes(
        self,
        space_id: str,
        parent_node_token: str = "",
        page_size: int = 50,
        page_token: str = "",
    ) -> Result:
        params: Dict[str, str] = {"page_size": str(min(page_size, 50))}
        if parent_node_token:
            params["parent_node_token"] = parent_node_token
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/wiki/v2/spaces/{space_id}/nodes",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_wiki_node(self, token: str, obj_type: str = "wiki") -> Result:
        """Resolve a wiki URL token to its underlying obj_token + obj_type (docx/sheet/bitable/...)."""
        return http_request(
            "GET",
            f"{LARK_API_BASE}/wiki/v2/spaces/get_node",
            headers=self._headers(),
            params={"token": token, "obj_type": obj_type},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_wiki_node(
        self,
        space_id: str,
        obj_type: str,
        node_type: str = "origin",
        parent_node_token: str = "",
        origin_node_token: str = "",
        title: str = "",
    ) -> Result:
        """obj_type: doc | docx | sheet | bitable | mindnote | file | slides. node_type: origin (create new) | shortcut (reference)."""
        payload: Dict[str, Any] = {"obj_type": obj_type, "node_type": node_type}
        if parent_node_token:
            payload["parent_node_token"] = parent_node_token
        if origin_node_token:
            payload["origin_node_token"] = origin_node_token
        if title:
            payload["title"] = title
        return http_request(
            "POST",
            f"{LARK_API_BASE}/wiki/v2/spaces/{space_id}/nodes",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def move_wiki_node(
        self,
        space_id: str,
        node_token: str,
        target_parent_token: str = "",
        target_space_id: str = "",
    ) -> Result:
        payload: Dict[str, Any] = {}
        if target_parent_token:
            payload["target_parent_token"] = target_parent_token
        if target_space_id:
            payload["target_space_id"] = target_space_id
        return http_request(
            "POST",
            f"{LARK_API_BASE}/wiki/v2/spaces/{space_id}/nodes/{node_token}/move",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )
