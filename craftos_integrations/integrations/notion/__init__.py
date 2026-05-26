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
