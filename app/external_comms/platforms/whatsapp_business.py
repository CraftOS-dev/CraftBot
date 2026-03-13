# -*- coding: utf-8 -*-
"""WhatsApp Business Cloud API client — direct HTTP via httpx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.external_comms.base import BasePlatformClient
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
CREDENTIAL_FILE = "whatsapp_business.json"


@dataclass
class WhatsAppBusinessCredential:
    access_token: str = ""
    phone_number_id: str = ""
    app_secret: str = ""
    verify_token: str = ""


@register_client
class WhatsAppBusinessClient(BasePlatformClient):
    PLATFORM_ID = "whatsapp_business"

    def __init__(self):
        super().__init__()
        self._cred: Optional[WhatsAppBusinessCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> WhatsAppBusinessCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, WhatsAppBusinessCredential)
        if self._cred is None:
            raise RuntimeError("No WhatsApp Business credentials. Use /whatsapp-business login first.")
        return self._cred

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        return {"Authorization": f"Bearer {cred.access_token}", "Content-Type": "application/json"}

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a text message via WhatsApp Business Cloud API."""
        return self.send_text(recipient, text)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def send_text(self, to: str, text: str) -> Dict[str, Any]:
        cred = self._load()
        url = f"{GRAPH_API_BASE}/{cred.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        try:
            r = httpx.post(url, headers=self._headers(), json=payload, timeout=15)
            data = r.json()
            if r.status_code in (200, 201):
                return {"ok": True, "result": data}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}

    def send_template(self, to: str, template_name: str, language_code: str = "en_US",
                      components: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        cred = self._load()
        url = f"{GRAPH_API_BASE}/{cred.phone_number_id}/messages"
        template: Dict[str, Any] = {"name": template_name, "language": {"code": language_code}}
        if components:
            template["components"] = components
        payload = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": template}
        try:
            r = httpx.post(url, headers=self._headers(), json=payload, timeout=15)
            data = r.json()
            if r.status_code in (200, 201):
                return {"ok": True, "result": data}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}

    def send_image(self, to: str, image_url: str, caption: Optional[str] = None) -> Dict[str, Any]:
        cred = self._load()
        url = f"{GRAPH_API_BASE}/{cred.phone_number_id}/messages"
        image: Dict[str, Any] = {"link": image_url}
        if caption:
            image["caption"] = caption
        payload = {"messaging_product": "whatsapp", "to": to, "type": "image", "image": image}
        try:
            r = httpx.post(url, headers=self._headers(), json=payload, timeout=15)
            data = r.json()
            if r.status_code in (200, 201):
                return {"ok": True, "result": data}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}

    def send_document(self, to: str, document_url: str, filename: Optional[str] = None,
                      caption: Optional[str] = None) -> Dict[str, Any]:
        cred = self._load()
        url = f"{GRAPH_API_BASE}/{cred.phone_number_id}/messages"
        doc: Dict[str, Any] = {"link": document_url}
        if filename:
            doc["filename"] = filename
        if caption:
            doc["caption"] = caption
        payload = {"messaging_product": "whatsapp", "to": to, "type": "document", "document": doc}
        try:
            r = httpx.post(url, headers=self._headers(), json=payload, timeout=15)
            data = r.json()
            if r.status_code in (200, 201):
                return {"ok": True, "result": data}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}

    def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        cred = self._load()
        url = f"{GRAPH_API_BASE}/{cred.phone_number_id}/messages"
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        try:
            r = httpx.post(url, headers=self._headers(), json=payload, timeout=15)
            data = r.json()
            if r.status_code == 200:
                return {"ok": True, "result": data}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def get_media_url(self, media_id: str) -> Dict[str, Any]:
        try:
            r = httpx.get(f"{GRAPH_API_BASE}/{media_id}", headers=self._headers(), timeout=15)
            data = r.json()
            if r.status_code == 200:
                return {"ok": True, "result": {"url": data.get("url"), "mime_type": data.get("mime_type"), "file_size": data.get("file_size")}}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Business Profile
    # ------------------------------------------------------------------

    def get_business_profile(self) -> Dict[str, Any]:
        cred = self._load()
        try:
            r = httpx.get(f"{GRAPH_API_BASE}/{cred.phone_number_id}/whatsapp_business_profile",
                          headers=self._headers(), params={"fields": "about,address,description,email,profile_picture_url,websites,vertical"}, timeout=15)
            data = r.json()
            if r.status_code == 200:
                return {"ok": True, "result": data.get("data", [{}])[0] if data.get("data") else data}
            return {"error": f"API error: {r.status_code}", "details": data}
        except Exception as e:
            return {"error": str(e)}
