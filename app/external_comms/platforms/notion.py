# -*- coding: utf-8 -*-
"""Notion API client — direct HTTP via httpx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.external_comms.base import BasePlatformClient
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
CREDENTIAL_FILE = "notion.json"


@dataclass
class NotionCredential:
    token: str = ""


@register_client
class NotionClient(BasePlatformClient):
    PLATFORM_ID = "notion"

    def __init__(self):
        super().__init__()
        self._cred: Optional[NotionCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> NotionCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, NotionCredential)
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
        # Notion doesn't have a messaging concept; no-op
        return {"ok": False, "error": "Notion does not support messaging"}

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    def search(self, query: str, filter_type: Optional[str] = None, page_size: int = 100) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"query": query, "page_size": page_size}
        if filter_type in ("page", "database"):
            payload["filter"] = {"property": "object", "value": filter_type}
        r = httpx.post(f"{NOTION_API_BASE}/search", headers=self._headers(), json=payload)
        data = r.json()
        if r.status_code != 200:
            return [{"error": data}]
        return data.get("results", [])

    def get_page(self, page_id: str) -> Dict[str, Any]:
        r = httpx.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=self._headers())
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def get_database(self, database_id: str) -> Dict[str, Any]:
        r = httpx.get(f"{NOTION_API_BASE}/databases/{database_id}", headers=self._headers())
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

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
        r = httpx.post(f"{NOTION_API_BASE}/databases/{database_id}/query", headers=self._headers(), json=payload)
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def create_page(
        self,
        parent_id: str,
        parent_type: str,
        properties: Dict[str, Any],
        children: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"parent": {parent_type: parent_id}, "properties": properties}
        if children:
            payload["children"] = children
        r = httpx.post(f"{NOTION_API_BASE}/pages", headers=self._headers(), json=payload)
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        r = httpx.patch(f"{NOTION_API_BASE}/pages/{page_id}", headers=self._headers(), json={"properties": properties})
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def get_block_children(self, block_id: str, page_size: int = 100) -> Dict[str, Any]:
        r = httpx.get(f"{NOTION_API_BASE}/blocks/{block_id}/children", headers=self._headers(), params={"page_size": page_size})
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def append_block_children(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        r = httpx.patch(f"{NOTION_API_BASE}/blocks/{block_id}/children", headers=self._headers(), json={"children": children})
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def delete_block(self, block_id: str) -> Dict[str, Any]:
        r = httpx.delete(f"{NOTION_API_BASE}/blocks/{block_id}", headers=self._headers())
        data = r.json()
        return {"error": data} if r.status_code != 200 else data

    def get_user(self, user_id: str = "me") -> Dict[str, Any]:
        r = httpx.get(f"{NOTION_API_BASE}/users/{user_id}", headers=self._headers())
        data = r.json()
        return {"error": data} if r.status_code != 200 else data
