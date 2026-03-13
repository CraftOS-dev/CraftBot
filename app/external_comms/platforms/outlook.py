# -*- coding: utf-8 -*-
"""Outlook email client — Microsoft Graph API via httpx."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.external_comms.base import BasePlatformClient, PlatformMessage, MessageCallback
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
CREDENTIAL_FILE = "outlook.json"

POLL_INTERVAL = 5       # seconds between inbox polls
RETRY_DELAY = 10        # seconds to wait after a poll error


@dataclass
class OutlookCredential:
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    client_id: str = ""
    email: str = ""


@register_client
class OutlookClient(BasePlatformClient):
    PLATFORM_ID = "outlook"

    def __init__(self):
        super().__init__()
        self._cred: Optional[OutlookCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._seen_message_ids: set = set()
        self._last_poll_time: Optional[str] = None  # ISO 8601 timestamp

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> OutlookCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, OutlookCredential)
        if self._cred is None:
            raise RuntimeError("No Outlook credentials. Use /outlook login first.")
        return self._cred

    def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
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
        try:
            r = httpx.post(
                MS_TOKEN_URL,
                data={
                    "client_id": cred.client_id,
                    "refresh_token": cred.refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "Mail.Read Mail.Send Mail.ReadWrite User.Read offline_access",
                },
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                cred.access_token = data["access_token"]
                # Microsoft may rotate refresh tokens
                cred.refresh_token = data.get("refresh_token", cred.refresh_token)
                cred.token_expiry = time.time() + data.get("expires_in", 3600) - 60
                save_credential(CREDENTIAL_FILE, cred)
                self._cred = cred
                return cred.access_token
        except Exception:
            pass
        return None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def _auth_header(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    # ------------------------------------------------------------------
    # BasePlatformClient interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        cred = self._load()
        if not cred.access_token:
            raise RuntimeError(
                "Outlook credentials need to be updated. "
                "Run /outlook logout then /outlook login to re-authenticate."
            )
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        subject = kwargs.get("subject", "")
        return self.send_email(to=recipient, subject=subject, body=text)

    # ------------------------------------------------------------------
    # Listening support (email polling via Graph API)
    # ------------------------------------------------------------------

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback: MessageCallback) -> None:
        if self._listening:
            return

        self._message_callback = callback
        self._load()

        # Verify token works and get user profile
        try:
            profile = await self._async_get_profile()
            email_addr = profile.get("mail") or profile.get("userPrincipalName", "")
            logger.info(f"[OUTLOOK] Connected as: {email_addr}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Outlook: {e}")

        # Catchup: set last poll time to now so we don't dispatch old messages
        self._last_poll_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._listening = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[OUTLOOK] Email poller started")

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
        logger.info("[OUTLOOK] Email poller stopped")

    async def _async_get_profile(self) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_API_BASE}/me",
                headers=self._auth_header(),
                timeout=15,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Graph /me error: {resp.status_code}")
            return resp.json()

    async def _poll_loop(self) -> None:
        logger.info("[OUTLOOK] Catchup complete — watching for new emails")

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

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_API_BASE}/me/messages",
                headers=self._auth_header(),
                params={
                    "$filter": f"receivedDateTime ge {self._last_poll_time}",
                    "$orderby": "receivedDateTime asc",
                    "$top": "50",
                    "$select": "id,from,subject,bodyPreview,receivedDateTime,conversationId",
                },
                timeout=15,
            )
            if resp.status_code == 401:
                self.refresh_access_token()
                return
            if resp.status_code != 200:
                logger.warning(f"[OUTLOOK] messages API error: {resp.status_code}")
                return

            data = resp.json()
            messages = data.get("value", [])

            for msg in messages:
                msg_id = msg.get("id", "")
                if not msg_id or msg_id in self._seen_message_ids:
                    continue

                self._seen_message_ids.add(msg_id)
                await self._dispatch_message(msg)

            # Update last poll time to the most recent message's time
            if messages:
                last_received = messages[-1].get("receivedDateTime", "")
                if last_received:
                    self._last_poll_time = last_received

            # Cap seen set
            if len(self._seen_message_ids) > 500:
                self._seen_message_ids = set(list(self._seen_message_ids)[-200:])

    async def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        from_obj = msg.get("from", {}).get("emailAddress", {})
        sender_email = from_obj.get("address", "")
        sender_name = from_obj.get("name", sender_email)

        # Skip own messages
        cred = self._load()
        if sender_email.lower() == (cred.email or "").lower():
            return

        subject = msg.get("subject", "(no subject)")
        snippet = msg.get("bodyPreview", "")
        text = f"Subject: {subject}\n{snippet}" if snippet else f"Subject: {subject}"

        # Parse timestamp
        timestamp = None
        dt_str = msg.get("receivedDateTime", "")
        if dt_str:
            try:
                timestamp = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except Exception:
                pass

        platform_msg = PlatformMessage(
            platform="outlook",
            sender_id=sender_email,
            sender_name=sender_name,
            text=text,
            channel_id=msg.get("conversationId", ""),
            message_id=msg.get("id", ""),
            timestamp=timestamp,
            raw=msg,
        )

        if self._message_callback:
            await self._message_callback(platform_msg)

    # ==================================================================
    # Send Email
    # ==================================================================

    def send_email(self, to: str, subject: str, body: str, cc: Optional[str] = None,
                   html: bool = False) -> Dict[str, Any]:
        """Send email via Microsoft Graph API."""
        content_type = "HTML" if html else "Text"
        message: Dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": content_type, "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": addr.strip()}}
                for addr in cc.split(",")
            ]

        try:
            r = httpx.post(
                f"{GRAPH_API_BASE}/me/sendMail",
                headers=self._headers(),
                json={"message": message, "saveToSentItems": True},
                timeout=15,
            )
            if r.status_code == 202:
                return {"ok": True, "result": {"sent": True, "to": to, "subject": subject}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    # ==================================================================
    # Read Emails
    # ==================================================================

    def list_emails(self, n: int = 10, unread_only: bool = False, folder: str = "inbox") -> Dict[str, Any]:
        """List recent emails from a folder."""
        params: Dict[str, Any] = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$select": "id,from,subject,receivedDateTime,isRead,bodyPreview",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"

        try:
            r = httpx.get(
                f"{GRAPH_API_BASE}/me/mailFolders/{folder}/messages",
                headers=self._auth_header(),
                params=params,
                timeout=15,
            )
            if r.status_code == 200:
                messages = r.json().get("value", [])
                emails = []
                for msg in messages:
                    from_obj = msg.get("from", {}).get("emailAddress", {})
                    emails.append({
                        "id": msg.get("id"),
                        "from": f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>",
                        "subject": msg.get("subject", ""),
                        "date": msg.get("receivedDateTime", ""),
                        "is_read": msg.get("isRead", False),
                        "preview": msg.get("bodyPreview", ""),
                    })
                return {"ok": True, "result": {"emails": emails, "count": len(emails)}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def get_email(self, message_id: str) -> Dict[str, Any]:
        """Get full email by ID."""
        try:
            r = httpx.get(
                f"{GRAPH_API_BASE}/me/messages/{message_id}",
                headers=self._auth_header(),
                params={"$select": "id,from,toRecipients,subject,body,receivedDateTime,conversationId"},
                timeout=15,
            )
            if r.status_code != 200:
                return {"error": f"API error: {r.status_code}", "details": r.text}

            msg = r.json()
            from_obj = msg.get("from", {}).get("emailAddress", {})
            to_list = [
                f"{rcpt.get('emailAddress', {}).get('name', '')} <{rcpt.get('emailAddress', {}).get('address', '')}>"
                for rcpt in msg.get("toRecipients", [])
            ]
            return {"ok": True, "result": {
                "id": msg.get("id"),
                "from": f"{from_obj.get('name', '')} <{from_obj.get('address', '')}>",
                "to": ", ".join(to_list),
                "subject": msg.get("subject", ""),
                "date": msg.get("receivedDateTime", ""),
                "body": msg.get("body", {}).get("content", ""),
            }}
        except Exception as e:
            return {"error": str(e)}

    def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Mark email as read."""
        try:
            r = httpx.patch(
                f"{GRAPH_API_BASE}/me/messages/{message_id}",
                headers=self._headers(),
                json={"isRead": True},
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def list_folders(self) -> Dict[str, Any]:
        """List mail folders."""
        try:
            r = httpx.get(
                f"{GRAPH_API_BASE}/me/mailFolders",
                headers=self._auth_header(),
                params={"$select": "id,displayName,totalItemCount,unreadItemCount"},
                timeout=15,
            )
            if r.status_code == 200:
                folders = r.json().get("value", [])
                return {"ok": True, "result": {"folders": [
                    {
                        "id": f.get("id"),
                        "name": f.get("displayName"),
                        "total": f.get("totalItemCount"),
                        "unread": f.get("unreadItemCount"),
                    }
                    for f in folders
                ]}}
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}

    def read_top_emails(self, n: int = 5, full_body: bool = False) -> Dict[str, Any]:
        """Read top N emails with details."""
        listing = self.list_emails(n=n, unread_only=False)
        if "error" in listing:
            return listing
        emails_summary = listing.get("result", {}).get("emails", [])
        if not full_body:
            return {"ok": True, "result": emails_summary}
        detailed = []
        for e_info in emails_summary:
            detail = self.get_email(e_info["id"])
            if "error" not in detail:
                detailed.append(detail.get("result", detail))
            else:
                detailed.append(e_info)
        return {"ok": True, "result": detailed}
