# -*- coding: utf-8 -*-
"""WhatsApp Business Cloud API integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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

logger = get_logger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


@dataclass
class WhatsAppBusinessCredential:
    access_token: str = ""
    phone_number_id: str = ""
    app_secret: str = ""
    verify_token: str = ""


WAB = IntegrationSpec(
    name="whatsapp_business",
    cred_class=WhatsAppBusinessCredential,
    cred_file="whatsapp_business.json",
    platform_id="whatsapp_business",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(WAB.name)
class WhatsAppBusinessHandler(IntegrationHandler):
    spec = WAB
    display_name = "WhatsApp Business"
    description = "WhatsApp Cloud API"
    auth_type = "token"
    icon = "whatsapp_business"
    connect_help = [
        "Open developers.facebook.com/apps and create an app (Business type)",
        "Add the 'WhatsApp' product to the app",
        "WhatsApp â†’ API Setup tab - copy the temporary access token (or generate a permanent one in System Users)",
        "Same page - copy the Phone Number ID under 'From' phone number",
        "Add a recipient phone number for testing on the same page",
    ]
    fields = [
        {
            "key": "access_token",
            "label": "Access Token",
            "placeholder": "Enter access token",
            "password": True,
        },
        {
            "key": "phone_number_id",
            "label": "Phone Number ID",
            "placeholder": "Enter phone number ID",
            "password": False,
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 2:
            return (
                False,
                "Usage: /whatsapp-business login <access_token> <phone_number_id>",
            )
        access_token, phone_number_id = args[0], args[1]

        result = http_request(
            "GET",
            f"{GRAPH_API_BASE}/{phone_number_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Invalid credentials: {result['error']}"

        save_credential(
            self.spec.cred_file,
            WhatsAppBusinessCredential(
                access_token=access_token,
                phone_number_id=phone_number_id,
            ),
        )
        return True, f"WhatsApp Business connected (phone number ID: {phone_number_id})"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No WhatsApp Business credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed WhatsApp Business credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "WhatsApp Business: Not connected"
        cred = load_credential(self.spec.cred_file, WhatsAppBusinessCredential)
        pid = cred.phone_number_id if cred else "unknown"
        return True, f"WhatsApp Business: Connected\n  - Phone Number ID: {pid}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class WhatsAppBusinessClient(BasePlatformClient):
    spec = WAB
    PLATFORM_ID = WAB.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[WhatsAppBusinessCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> WhatsAppBusinessCredential:
        if self._cred is None:
            self._cred = load_credential(
                self.spec.cred_file, WhatsAppBusinessCredential
            )
        if self._cred is None:
            raise RuntimeError(
                "No WhatsApp Business credentials. Use /whatsapp-business login first."
            )
        return self._cred

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        return {
            "Authorization": f"Bearer {cred.access_token}",
            "Content-Type": "application/json",
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return self.send_text(recipient, text)

    def _messages_url(self) -> str:
        return f"{GRAPH_API_BASE}/{self._load().phone_number_id}/messages"

    def send_text(self, to: str, text: str) -> Result:
        return http_request(
            "POST",
            self._messages_url(),
            headers=self._headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )

    def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en_US",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Result:
        template: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components
        return http_request(
            "POST",
            self._messages_url(),
            headers=self._headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": template,
            },
        )

    def send_image(
        self, to: str, image_url: str, caption: Optional[str] = None
    ) -> Result:
        image: Dict[str, Any] = {"link": image_url}
        if caption:
            image["caption"] = caption
        return http_request(
            "POST",
            self._messages_url(),
            headers=self._headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "image",
                "image": image,
            },
        )

    def send_document(
        self,
        to: str,
        document_url: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Result:
        doc: Dict[str, Any] = {"link": document_url}
        if filename:
            doc["filename"] = filename
        if caption:
            doc["caption"] = caption
        return http_request(
            "POST",
            self._messages_url(),
            headers=self._headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "document",
                "document": doc,
            },
        )

    def mark_as_read(self, message_id: str) -> Result:
        return http_request(
            "POST",
            self._messages_url(),
            headers=self._headers(),
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            },
            expected=(200,),
        )

    def get_media_url(self, media_id: str) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/{media_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "url": d.get("url"),
                "mime_type": d.get("mime_type"),
                "file_size": d.get("file_size"),
            },
        )

    def get_business_profile(self) -> Result:
        cred = self._load()
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/{cred.phone_number_id}/whatsapp_business_profile",
            headers=self._headers(),
            params={
                "fields": "about,address,description,email,profile_picture_url,websites,vertical"
            },
            expected=(200,),
            transform=lambda d: d.get("data", [{}])[0] if d.get("data") else d,
        )
