# -*- coding: utf-8 -*-
"""Outlook integration - Microsoft Graph + OAuth (PKCE)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    OAuthFlow,
    PlatformMessage,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...config import ConfigStore
from ...helpers import Result, arequest, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
OUTLOOK_SCOPES = "Mail.Read Mail.Send Mail.ReadWrite User.Read offline_access"

POLL_INTERVAL = 5
RETRY_DELAY = 10


@dataclass
class OutlookCredential:
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    client_id: str = ""
    email: str = ""


OUTLOOK = IntegrationSpec(
    name="outlook",
    cred_class=OutlookCredential,
    cred_file="outlook.json",
    platform_id="outlook",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(OUTLOOK.name)
class OutlookHandler(IntegrationHandler):
    spec = OUTLOOK
    display_name = "Outlook"
    description = "Microsoft email and calendar"
    auth_type = "oauth"
    icon = "Inbox"
    fields: List = []

    oauth = OAuthFlow(
        client_id_key="OUTLOOK_CLIENT_ID",
        client_secret_key=None,
        auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url=MS_TOKEN_URL,
        userinfo_url="https://graph.microsoft.com/v1.0/me",
        scopes=OUTLOOK_SCOPES,
        use_pkce=True,
        extra_auth_params={"response_mode": "query"},
    )

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"Outlook OAuth failed: {result['error']}"

        info = result.get("userinfo", {})
        user_email = info.get("mail") or info.get("userPrincipalName", "")

        save_credential(
            self.spec.cred_file,
            OutlookCredential(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", ""),
                token_expiry=time.time() + result.get("expires_in", 3600),
                client_id=ConfigStore.get_oauth("OUTLOOK_CLIENT_ID"),
                email=user_email,
            ),
        )
        return True, f"Outlook connected as {user_email}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Outlook credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Outlook credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Outlook: Not connected"
        cred = load_credential(self.spec.cred_file, OutlookCredential)
        email = cred.email if cred else "unknown"
        return True, f"Outlook: Connected\n  - {email}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class OutlookClient(BasePlatformClient):
    spec = OUTLOOK
    PLATFORM_ID = OUTLOOK.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[OutlookCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._seen_message_ids: set = set()
        self._last_poll_time: Optional[str] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> OutlookCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, OutlookCredential)
        if self._cred is None:
            raise RuntimeError("No Outlook credentials. Use /outlook login first.")
        return self._cred

    def _ensure_token(self) -> str:
        cred = self._load()
        if cred.refresh_token and cred.token_expiry and time.time() > cred.token_expiry:
            result = self.refresh_access_token()
            if result:
                return result
        return cred.access_token

    def refresh_access_token(self) -> Optional[str]:
        cred = self._load()
        if not all([cred.client_id, cred.refresh_token]):
            return None
        result = http_request(
            "POST",
            MS_TOKEN_URL,
            data={
                "client_id": cred.client_id,
                "refresh_token": cred.refresh_token,
                "grant_type": "refresh_token",
                "scope": OUTLOOK_SCOPES,
            },
            expected=(200,),
        )
        if "error" in result:
            return None
        data = result["result"]
        cred.access_token = data["access_token"]
        cred.refresh_token = data.get("refresh_token", cred.refresh_token)
        cred.token_expiry = time.time() + data.get("expires_in", 3600) - 60
        save_credential(self.spec.cred_file, cred)
        self._cred = cred
        return cred.access_token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def _auth_header(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    async def connect(self) -> None:
        cred = self._load()
        if not cred.access_token:
            raise RuntimeError(
                "Outlook credentials need to be updated. Run /outlook logout then /outlook login."
            )
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return self.send_email(
            to=recipient, subject=kwargs.get("subject", ""), body=text
        )

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return
        self._message_callback = callback
        self._load()

        try:
            profile = await self._async_get_profile()
            email_addr = profile.get("mail") or profile.get("userPrincipalName", "")
            logger.info(f"[OUTLOOK] Connected as: {email_addr}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Outlook: {e}")

        self._last_poll_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._listening = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None

    async def _async_get_profile(self) -> Dict[str, Any]:
        result = await arequest(
            "GET", f"{GRAPH_API_BASE}/me", headers=self._auth_header(), expected=(200,)
        )
        if "error" in result:
            raise RuntimeError(f"Graph /me {result['error']}")
        return result["result"]

    async def _poll_loop(self) -> None:
        while self._listening:
            try:
                await self._check_new_messages()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OUTLOOK] Poll error: {e}")
                if "401" in str(e):
                    self.refresh_access_token()
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_new_messages(self) -> None:
        if not self._last_poll_time:
            return
        result = await arequest(
            "GET",
            f"{GRAPH_API_BASE}/me/messages",
            headers=self._auth_header(),
            params={
                "$filter": f"receivedDateTime ge {self._last_poll_time}",
                "$orderby": "receivedDateTime asc",
                "$top": "50",
                "$select": "id,from,subject,bodyPreview,receivedDateTime,conversationId",
            },
            expected=(200,),
        )
        if "error" in result:
            if "401" in result["error"]:
                self.refresh_access_token()
            else:
                logger.warning(f"[OUTLOOK] messages API {result['error']}")
            return

        messages = (result["result"] or {}).get("value", [])
        for msg in messages:
            msg_id = msg.get("id", "")
            if not msg_id or msg_id in self._seen_message_ids:
                continue
            self._seen_message_ids.add(msg_id)
            await self._dispatch_message(msg)

        if messages:
            last_received = messages[-1].get("receivedDateTime", "")
            if last_received:
                self._last_poll_time = last_received

        if len(self._seen_message_ids) > 500:
            self._seen_message_ids = set(list(self._seen_message_ids)[-200:])

    async def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        from_obj = msg.get("from", {}).get("emailAddress", {})
        sender_email = from_obj.get("address", "")
        sender_name = from_obj.get("name", sender_email)

        cred = self._load()
        if sender_email.lower() == (cred.email or "").lower():
            return

        subject = msg.get("subject", "(no subject)")
        snippet = msg.get("bodyPreview", "")
        text = f"Subject: {subject}\n{snippet}" if snippet else f"Subject: {subject}"

        timestamp = None
        try:
            timestamp = datetime.fromisoformat(
                msg.get("receivedDateTime", "").replace("Z", "+00:00")
            )
        except Exception:
            pass

        if self._message_callback:
            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=sender_email,
                    sender_name=sender_name,
                    text=text,
                    channel_id=msg.get("conversationId", ""),
                    message_id=msg.get("id", ""),
                    timestamp=timestamp,
                    raw=msg,
                )
            )

    # --- Email API ---
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        html: bool = False,
    ) -> Result:
        content_type = "HTML" if html else "Text"
        message: Dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": content_type, "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": addr.strip()}} for addr in cc.split(",")
            ]
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/sendMail",
            headers=self._headers(),
            json={"message": message, "saveToSentItems": True},
            expected=(202,),
            transform=lambda _d: {"sent": True, "to": to, "subject": subject},
        )

    def list_emails(
        self, n: int = 10, unread_only: bool = False, folder: str = "inbox"
    ) -> Result:
        params: Dict[str, Any] = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$select": "id,from,subject,receivedDateTime,isRead,bodyPreview",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"

        def _shape(d):
            emails = []
            for msg in d.get("value", []):
                from_obj = msg.get("from", {}).get("emailAddress", {})
                emails.append(
                    {
                        "id": msg.get("id"),
                        "from": f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>",
                        "subject": msg.get("subject", ""),
                        "date": msg.get("receivedDateTime", ""),
                        "is_read": msg.get("isRead", False),
                        "preview": msg.get("bodyPreview", ""),
                    }
                )
            return {"emails": emails, "count": len(emails)}

        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailFolders/{folder}/messages",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
            transform=_shape,
        )

    def get_email(self, message_id: str) -> Result:
        def _shape(msg):
            from_obj = msg.get("from", {}).get("emailAddress", {})
            to_list = [
                f"{rcpt.get('emailAddress', {}).get('name', '')} <{rcpt.get('emailAddress', {}).get('address', '')}>"
                for rcpt in msg.get("toRecipients", [])
            ]
            return {
                "id": msg.get("id"),
                "from": f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>",
                "to": ", ".join(to_list),
                "subject": msg.get("subject", ""),
                "date": msg.get("receivedDateTime", ""),
                "body": msg.get("body", {}).get("content", ""),
            }

        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._auth_header(),
            params={
                "$select": "id,from,toRecipients,subject,body,receivedDateTime,conversationId"
            },
            expected=(200,),
            transform=_shape,
        )

    def mark_as_read(self, message_id: str) -> Result:
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._headers(),
            json={"isRead": True},
            expected=(200,),
            transform=lambda _d: {},
        )

    def list_folders(self) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailFolders",
            headers=self._auth_header(),
            params={"$select": "id,displayName,totalItemCount,unreadItemCount"},
            expected=(200,),
            transform=lambda d: {
                "folders": [
                    {
                        "id": f.get("id"),
                        "name": f.get("displayName"),
                        "total": f.get("totalItemCount"),
                        "unread": f.get("unreadItemCount"),
                    }
                    for f in d.get("value", [])
                ]
            },
        )

    def read_top_emails(self, n: int = 5, full_body: bool = False) -> Result:
        listing = self.list_emails(n=n, unread_only=False)
        if "error" in listing:
            return listing
        emails_summary = listing.get("result", {}).get("emails", [])
        if not full_body:
            return {"ok": True, "result": emails_summary}
        detailed = []
        for e_info in emails_summary:
            detail = self.get_email(e_info["id"])
            detailed.append(
                detail.get("result", e_info) if "error" not in detail else e_info
            )
        return {"ok": True, "result": detailed}
