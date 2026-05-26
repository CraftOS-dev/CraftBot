# -*- coding: utf-8 -*-
"""Notion integration - handler (token + OAuth invite) + client."""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    OAuthFlow,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _notion_call(
    method: str, path: str, headers: Dict[str, str], **kw
) -> Dict[str, Any]:
    """Notion API call. Returns raw response on 200, ``{error: <notion-body>}`` otherwise.

    Layers on top of ``request`` and re-parses ``details`` (string) back into Notion's
    JSON error body so callers can read ``result["error"]["code"]`` etc.
    """
    result = http_request(
        method,
        f"{NOTION_API_BASE}{path}",
        headers=headers,
        expected=(200,),
        **kw,
    )
    if "error" not in result:
        return result["result"]
    details = result.get("details")
    if isinstance(details, str):
        try:
            return {"error": _json.loads(details)}
        except Exception:
            pass
    return {"error": {"exception": result["error"]}}


@dataclass
class NotionCredential:
    token: str = ""


NOTION = IntegrationSpec(
    name="notion",
    cred_class=NotionCredential,
    cred_file="notion.json",
    platform_id="notion",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(NOTION.name)
class NotionHandler(IntegrationHandler):
    spec = NOTION
    display_name = "Notion"
    description = "Notes and databases"
    auth_type = "both"  # OAuth invite + raw integration token
    icon = "notion"
    connect_help = [
        "Open notion.so/my-integrations",
        "Click 'New integration', give it a name and pick the workspace",
        "Copy the 'Internal Integration Token' (starts with secret_)",
        "In Notion, share each page/database you want CraftBot to access with the integration",
    ]
    fields = [
        {
            "key": "token",
            "label": "Integration Token",
            "placeholder": "secret_...",
            "password": True,
        },
    ]

    oauth = OAuthFlow(
        client_id_key="NOTION_SHARED_CLIENT_ID",
        client_secret_key="NOTION_SHARED_CLIENT_SECRET",
        auth_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        userinfo_url=None,
        scopes="",
        token_auth_basic=True,
        token_request_json=True,
        extra_auth_params={"owner": "user"},
    )

    @property
    def subcommands(self) -> List[str]:
        return ["invite", "login", "logout", "status"]

    async def invite(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"Notion OAuth failed: {result['error']}"

        token = result.get("access_token", "")
        ws_name = result.get("raw", {}).get("workspace_name", "default")
        save_credential(self.spec.cred_file, NotionCredential(token=token))
        return True, f"Notion connected via CraftOS integration: {ws_name}"

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, "Usage: /notion login <integration_token>"
        token = args[0]

        data = _notion_call(
            "GET",
            "/users/me",
            {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
        )
        if "error" in data:
            return False, f"Notion auth failed: {data['error']}"

        ws_name = data.get("bot", {}).get("workspace_name", "default")
        save_credential(self.spec.cred_file, NotionCredential(token=token))
        return True, f"Notion connected: {ws_name}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Notion credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Notion credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Notion: Not connected"
        return True, "Notion: Connected"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class NotionClient(BasePlatformClient):
    spec = NOTION
    PLATFORM_ID = NOTION.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[NotionCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> NotionCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, NotionCredential)
        if self._cred is None:
            raise RuntimeError("No Notion credentials. Use /notion login first.")
        return self._cred

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        return {
            "Authorization": f"Bearer {cred.token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "error": "Notion does not support messaging"}

    def search(
        self, query: str, filter_type: Optional[str] = None, page_size: int = 100
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"query": query, "page_size": page_size}
        if filter_type in ("page", "database"):
            payload["filter"] = {"property": "object", "value": filter_type}
        data = _notion_call("POST", "/search", self._headers(), json=payload)
        if "error" in data:
            return [{"error": data["error"]}]
        return data.get("results", [])

    def get_page(self, page_id: str) -> Dict[str, Any]:
        return _notion_call("GET", f"/pages/{page_id}", self._headers())

    def get_database(self, database_id: str) -> Dict[str, Any]:
        return _notion_call("GET", f"/databases/{database_id}", self._headers())

    def query_database(
        self,
        database_id: str,
        filter_obj: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"page_size": page_size}
        if filter_obj:
            payload["filter"] = filter_obj
        if sorts:
            payload["sorts"] = sorts
        return _notion_call(
            "POST", f"/databases/{database_id}/query", self._headers(), json=payload
        )

    def create_page(
        self,
        parent_id: str,
        parent_type: str,
        properties: Dict[str, Any],
        children: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "parent": {parent_type: parent_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children
        return _notion_call("POST", "/pages", self._headers(), json=payload)

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        return _notion_call(
            "PATCH",
            f"/pages/{page_id}",
            self._headers(),
            json={"properties": properties},
        )

    def get_block_children(self, block_id: str, page_size: int = 100) -> Dict[str, Any]:
        return _notion_call(
            "GET",
            f"/blocks/{block_id}/children",
            self._headers(),
            params={"page_size": page_size},
        )

    def append_block_children(
        self, block_id: str, children: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return _notion_call(
            "PATCH",
            f"/blocks/{block_id}/children",
            self._headers(),
            json={"children": children},
        )

    def delete_block(self, block_id: str) -> Dict[str, Any]:
        return _notion_call("DELETE", f"/blocks/{block_id}", self._headers())

    def get_user(self, user_id: str = "me") -> Dict[str, Any]:
        return _notion_call("GET", f"/users/{user_id}", self._headers())

    # ----- Pages (extended) -----

    def archive_page(self, page_id: str) -> Dict[str, Any]:
        return _notion_call(
            "PATCH", f"/pages/{page_id}",
            self._headers(), json={"archived": True},
        )

    def restore_page(self, page_id: str) -> Dict[str, Any]:
        return _notion_call(
            "PATCH", f"/pages/{page_id}",
            self._headers(), json={"archived": False},
        )

    def get_page_property(self, page_id: str, property_id: str,
                          page_size: int = 100) -> Dict[str, Any]:
        return _notion_call(
            "GET", f"/pages/{page_id}/properties/{property_id}",
            self._headers(), params={"page_size": page_size},
        )

    # ----- Databases (extended) -----

    def create_database(self, parent_page_id: str,
                        title: Optional[List[Dict[str, Any]]] = None,
                        description: Optional[List[Dict[str, Any]]] = None,
                        properties: Optional[Dict[str, Any]] = None,
                        is_inline: bool = False,
                        icon: Optional[Dict[str, Any]] = None,
                        cover: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a database under a parent page.

        Note: per the 2025 update, the database schema moved under
        ``initial_data_source.properties``. We accept ``properties`` at the
        method surface and wrap it for the agent.
        """
        payload: Dict[str, Any] = {
            "parent": {"page_id": parent_page_id},
            "is_inline": is_inline,
        }
        if title is not None: payload["title"] = title
        if description is not None: payload["description"] = description
        if properties is not None:
            payload["initial_data_source"] = {"properties": properties}
        if icon is not None: payload["icon"] = icon
        if cover is not None: payload["cover"] = cover
        return _notion_call("POST", "/databases", self._headers(), json=payload)

    def update_database(self, database_id: str,
                        title: Optional[List[Dict[str, Any]]] = None,
                        description: Optional[List[Dict[str, Any]]] = None,
                        properties: Optional[Dict[str, Any]] = None,
                        is_inline: Optional[bool] = None,
                        archived: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if title is not None: payload["title"] = title
        if description is not None: payload["description"] = description
        if properties is not None: payload["properties"] = properties
        if is_inline is not None: payload["is_inline"] = is_inline
        if archived is not None: payload["archived"] = archived
        return _notion_call("PATCH", f"/databases/{database_id}",
                            self._headers(), json=payload)

    def archive_database(self, database_id: str) -> Dict[str, Any]:
        return self.update_database(database_id, archived=True)

    def restore_database(self, database_id: str) -> Dict[str, Any]:
        return self.update_database(database_id, archived=False)

    # ----- Blocks (extended) -----

    def get_block(self, block_id: str) -> Dict[str, Any]:
        return _notion_call("GET", f"/blocks/{block_id}", self._headers())

    def update_block(self, block_id: str, block_update: Dict[str, Any]) -> Dict[str, Any]:
        """Update a block. block_update has per-block-type keys, e.g.
        for a to_do block: {"to_do": {"rich_text": [...], "checked": true}}.
        Pass {"in_trash": true} to soft-delete (or use delete_block).
        """
        return _notion_call("PATCH", f"/blocks/{block_id}",
                            self._headers(), json=block_update)

    # ----- Comments -----

    def list_comments(self, block_id: str, page_size: int = 100,
                      start_cursor: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"block_id": block_id, "page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return _notion_call("GET", "/comments", self._headers(), params=params)

    def create_comment(self, rich_text: List[Dict[str, Any]],
                       parent_page_id: Optional[str] = None,
                       parent_block_id: Optional[str] = None,
                       discussion_id: Optional[str] = None,
                       display_name: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a top-level comment on a page/block, or a reply in a discussion.

        Provide exactly one of: parent_page_id, parent_block_id, discussion_id.
        """
        payload: Dict[str, Any] = {"rich_text": rich_text}
        targets = [t for t in (parent_page_id, parent_block_id, discussion_id) if t]
        if len(targets) != 1:
            return {"error": {"validation": "Provide exactly one of parent_page_id, parent_block_id, discussion_id"}}
        if parent_page_id:
            payload["parent"] = {"page_id": parent_page_id}
        elif parent_block_id:
            payload["parent"] = {"block_id": parent_block_id}
        else:
            payload["discussion_id"] = discussion_id
        if display_name is not None:
            payload["display_name"] = display_name
        return _notion_call("POST", "/comments", self._headers(), json=payload)

    # ----- Users (extended) -----

    def list_users(self, page_size: int = 100,
                   start_cursor: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return _notion_call("GET", "/users", self._headers(), params=params)

    def get_bot_info(self) -> Dict[str, Any]:
        """Returns the bot user including workspace_name + owner info."""
        return _notion_call("GET", "/users/me", self._headers())

    # ----- File uploads -----

    def create_file_upload(self, mode: str = "single_part",
                           filename: Optional[str] = None,
                           content_type: Optional[str] = None,
                           number_of_parts: Optional[int] = None,
                           external_url: Optional[str] = None) -> Dict[str, Any]:
        """Initialise a file upload. Returns id + upload_url (for pending uploads).

        mode: single_part | multi_part | external_url
        filename: required when mode=multi_part
        number_of_parts: required when mode=multi_part
        external_url: required when mode=external_url
        """
        payload: Dict[str, Any] = {"mode": mode}
        if filename is not None: payload["filename"] = filename
        if content_type is not None: payload["content_type"] = content_type
        if number_of_parts is not None: payload["number_of_parts"] = number_of_parts
        if external_url is not None: payload["external_url"] = external_url
        return _notion_call("POST", "/file_uploads", self._headers(), json=payload)

    def send_file_upload(self, file_upload_id: str, file_path: str,
                         part_number: Optional[int] = None) -> Dict[str, Any]:
        """Send a single-part or one part of a multi-part upload.

        Uses multipart/form-data — bypasses the JSON helper.
        """
        import os
        import httpx

        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return {"error": {"validation": f"File not found: {file_path}"}}

        cred = self._load()
        headers = {
            "Authorization": f"Bearer {cred.token}",
            "Notion-Version": NOTION_VERSION,
        }
        try:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f)}
                data: Dict[str, Any] = {}
                if part_number is not None:
                    data["part_number"] = str(part_number)
                r = httpx.post(
                    f"{NOTION_API_BASE}/file_uploads/{file_upload_id}/send",
                    headers=headers, files=files, data=data, timeout=300.0,
                )
            if r.status_code != 200:
                try:
                    return {"error": r.json()}
                except Exception:
                    return {"error": {"http": r.status_code, "details": r.text[:500]}}
            return r.json()
        except Exception as e:
            return {"error": {"exception": str(e)}}

    def complete_file_upload(self, file_upload_id: str) -> Dict[str, Any]:
        """Finalize a multi-part upload."""
        return _notion_call(
            "POST", f"/file_uploads/{file_upload_id}/complete",
            self._headers(),
        )

    def get_file_upload(self, file_upload_id: str) -> Dict[str, Any]:
        return _notion_call(
            "GET", f"/file_uploads/{file_upload_id}", self._headers(),
        )

    def list_file_uploads(self, status: Optional[str] = None,
                          page_size: int = 100,
                          start_cursor: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page_size": page_size}
        if status: params["status"] = status
        if start_cursor: params["start_cursor"] = start_cursor
        return _notion_call("GET", "/file_uploads", self._headers(), params=params)

    def upload_local_file(self, file_path: str,
                          content_type: Optional[str] = None) -> Dict[str, Any]:
        """High-level helper: single-part upload of a local file in one call.

        Returns the final file_upload object (with id + status='uploaded') that
        can be attached to a block via {"type":"file_upload","file_upload":{"id":...}}.
        For files >20 MB use multi-part directly.
        """
        import os
        import mimetypes

        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return {"error": {"validation": f"File not found: {file_path}"}}
        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                content_type = "application/octet-stream"

        created = self.create_file_upload(
            mode="single_part",
            filename=os.path.basename(file_path),
            content_type=content_type,
        )
        if "error" in created:
            return created
        upload_id = created.get("id")
        if not upload_id:
            return {"error": {"validation": "create_file_upload returned no id"}}
        return self.send_file_upload(upload_id, file_path)
