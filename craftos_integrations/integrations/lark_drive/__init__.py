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

from typing import Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._lark_common import (
    LARK_API_BASE,
    LarkCredential,
    ensure_token,
    make_headers,
    validate_and_mint_token,
)

logger = get_logger(__name__)


LARK_DRIVE = IntegrationSpec(
    name="lark_drive",
    cred_class=LarkCredential,
    cred_file="lark_drive.json",
    platform_id="lark_drive",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(LARK_DRIVE.name)
class LarkDriveHandler(IntegrationHandler):
    spec = LARK_DRIVE
    display_name = "Lark Drive"
    description = "Files and folders in Lark Drive"
    auth_type = "token"
    icon = "lark"
    connect_help = [
        "Use the same Custom App you created for /lark (or create one at open.larksuite.com/app)",
        "Permissions & Scopes â†’ enable: drive:drive (read-write) and drive:file:upload",
        "Version Management â†’ Create Version â†’ submit for tenant admin approval - required for the new scopes to take effect",
        "Credentials & Basic Info â†’ copy App ID + App Secret and paste them below (same values as /lark)",
    ]
    fields = [
        {
            "key": "app_id",
            "label": "App ID",
            "placeholder": "cli_xxxxxxxxxx",
            "password": False,
        },
        {
            "key": "app_secret",
            "label": "App Secret",
            "placeholder": "From Credentials & Basic Info tab",
            "password": True,
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, (
                "Usage: /lark_drive login <app_id> <app_secret>\n"
                "Use the same App ID + Secret as /lark; just make sure drive:* "
                "scopes are enabled on the same Custom App."
            )
        app_id, app_secret = args[0], args[1]
        token, token_expires_at, err = validate_and_mint_token(app_id, app_secret)
        if err:
            return False, err

        save_credential(
            self.spec.cred_file,
            LarkCredential(
                app_id=app_id,
                app_secret=app_secret,
                tenant_access_token=token,
                token_expires_at=token_expires_at,
            ),
        )
        return True, f"Lark Drive connected: {app_id}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Lark Drive credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Lark Drive credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Lark Drive: Not connected"
        cred = load_credential(self.spec.cred_file, LarkCredential)
        if not cred:
            return True, "Lark Drive: Connected\n  - app configured"
        return True, f"Lark Drive: Connected\n  - {cred.app_id}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


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
