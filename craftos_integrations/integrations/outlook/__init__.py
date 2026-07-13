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
    load_credential,
    register_client,
    register_handler,
    save_credential,
)
from ... import accounts as acc
from ...config import ConfigStore
from ...helpers import Result, arequest, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
OUTLOOK_SCOPES = "Mail.Read Mail.Send Mail.ReadWrite User.Read offline_access"

POLL_INTERVAL = 5
RETRY_DELAY = 10

# Multi-account: the bare "outlook.json" is always the primary account (no
# migration needed for existing single-account installs); additional
# accounts get "outlook__<email>.json" — see craftos_integrations/accounts.py.
_STEM = "outlook"


def _identity(cred: "OutlookCredential") -> str:
    return cred.email


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
        # ponytail: no select_account prompt — adding a 2nd Outlook account
        # will silently re-auth whatever MS account is signed into the
        # browser and overwrite the primary. Add "prompt": "select_account"
        # back to extra_auth_params if that regresses.
        extra_auth_params={"response_mode": "query"},
    )

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"Outlook OAuth failed: {result['error']}"

        info = result.get("userinfo", {})
        user_email = info.get("mail") or info.get("userPrincipalName", "")

        target_file = acc.resolve_save_target(_STEM, OutlookCredential, _identity, user_email)
        save_credential(
            target_file,
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
        account = args[0] if args else None
        accounts = acc.list_accounts(self.spec.platform_id, _STEM, OutlookCredential, _identity)
        if not accounts:
            return False, "No Outlook credentials found."
        if not account:
            acc.remove_all_accounts(_STEM)
            return True, "Removed Outlook credential."
        fname, err = acc.resolve_account(
            self.spec.platform_id, _STEM, OutlookCredential, _identity, account, "Outlook"
        )
        if err:
            return False, err
        acc.remove_account(_STEM, fname)
        return True, "Removed Outlook account."

    async def status(self) -> Tuple[bool, str]:
        accounts = acc.list_accounts(self.spec.platform_id, _STEM, OutlookCredential, _identity)
        if not accounts:
            return True, "Outlook: Not connected"
        lines = ["Outlook: Connected"]
        lines.extend(f"  - {a.identity} ({a.identity})" for a in accounts)
        return True, "\n".join(lines)

    def list_accounts(self):
        accounts = acc.list_accounts(self.spec.platform_id, _STEM, OutlookCredential, _identity)
        return acc.accounts_to_dicts(accounts)

    async def set_primary(self, account_id: str) -> Tuple[bool, str]:
        fname, err = acc.resolve_account(
            self.spec.platform_id, _STEM, OutlookCredential, _identity, account_id, "Outlook"
        )
        if err:
            return False, err
        if not acc.promote_to_primary(_STEM, fname):
            return False, f"{account_id} is already the primary Outlook account."
        return True, f"{account_id} is now the primary Outlook account."

    def set_alias(self, account_id: str, alias: str) -> Tuple[bool, str]:
        fname, err = acc.resolve_account(
            self.spec.platform_id, _STEM, OutlookCredential, _identity, account_id, "Outlook"
        )
        if err:
            return False, err
        cred = load_credential(fname, OutlookCredential)
        if not cred:
            return False, f"Could not load credential for {account_id}."
        acc.set_alias(self.spec.platform_id, cred.email, alias)
        return True, f"Alias {'set' if alias.strip() else 'cleared'} for {cred.email}."


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
        self._cred_file: Optional[str] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._seen_message_ids: set = set()
        self._last_poll_time: Optional[str] = None

    def has_credentials(self) -> bool:
        """True if *any* account is connected. Deliberately does not resolve
        self._account here — see GoogleApiClientMixin.has_credentials for why."""
        return bool(acc.list_accounts(self.spec.platform_id, _STEM, OutlookCredential, _identity))

    def _load(self) -> OutlookCredential:
        if self._cred is None:
            fname, err = acc.resolve_account(
                self.spec.platform_id,
                _STEM,
                OutlookCredential,
                _identity,
                getattr(self, "_account", None),
                "Outlook",
            )
            if err:
                raise RuntimeError(err)
            self._cred_file = fname
            self._cred = load_credential(fname, OutlookCredential)
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
        save_credential(self._cred_file or self.spec.cred_file, cred)
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

    # ----- Helper: build a Recipient list payload -----

    @staticmethod
    def _recipients(addresses: Optional[List[str]]) -> List[Dict[str, Any]]:
        if not addresses:
            return []
        return [
            {"emailAddress": {"address": a.strip()}}
            for a in addresses
            if a and a.strip()
        ]

    # ----- Message lifecycle: reply / forward / move / copy / delete / flag -----

    def reply_to_message(
        self, message_id: str, comment: str, to_recipients: Optional[List[str]] = None
    ) -> Result:
        """Send a reply to the sender immediately. Returns 202."""
        payload: Dict[str, Any] = {"comment": comment}
        if to_recipients:
            payload["message"] = {"toRecipients": self._recipients(to_recipients)}
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/reply",
            headers=self._headers(),
            json=payload,
            expected=(202,),
            transform=lambda _d: {"replied": True, "message_id": message_id},
        )

    def reply_all_to_message(self, message_id: str, comment: str) -> Result:
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/replyAll",
            headers=self._headers(),
            json={"comment": comment},
            expected=(202,),
            transform=lambda _d: {"replied_all": True, "message_id": message_id},
        )

    def forward_message(
        self, message_id: str, to_recipients: List[str], comment: str = ""
    ) -> Result:
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/forward",
            headers=self._headers(),
            json={"comment": comment, "toRecipients": self._recipients(to_recipients)},
            expected=(202,),
            transform=lambda _d: {
                "forwarded": True,
                "message_id": message_id,
                "to": to_recipients,
            },
        )

    def create_reply_draft(self, message_id: str, comment: str = "") -> Result:
        """Create a draft pre-populated as a reply; returns the draft so it can be edited then sent."""
        payload: Dict[str, Any] = {}
        if comment:
            payload["comment"] = comment
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/createReply",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "draft_id": d.get("id"),
                "conversationId": d.get("conversationId"),
            },
        )

    def create_forward_draft(
        self, message_id: str, to_recipients: List[str], comment: str = ""
    ) -> Result:
        payload: Dict[str, Any] = {
            "comment": comment,
            "toRecipients": self._recipients(to_recipients),
        }
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/createForward",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "draft_id": d.get("id"),
                "conversationId": d.get("conversationId"),
            },
        )

    def create_draft(
        self,
        subject: str,
        body: str,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html: bool = False,
    ) -> Result:
        """Create a draft message. POST /me/messages returns 201 + draft resource."""
        message: Dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "HTML" if html else "Text", "content": body},
        }
        if to:
            message["toRecipients"] = self._recipients(to)
        if cc:
            message["ccRecipients"] = self._recipients(cc)
        if bcc:
            message["bccRecipients"] = self._recipients(bcc)
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages",
            headers=self._headers(),
            json=message,
            expected=(201,),
            transform=lambda d: {
                "draft_id": d.get("id"),
                "subject": d.get("subject"),
                "conversationId": d.get("conversationId"),
            },
        )

    def update_draft(
        self,
        message_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html: bool = False,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if subject is not None:
            payload["subject"] = subject
        if body is not None:
            payload["body"] = {
                "contentType": "HTML" if html else "Text",
                "content": body,
            }
        if to is not None:
            payload["toRecipients"] = self._recipients(to)
        if cc is not None:
            payload["ccRecipients"] = self._recipients(cc)
        if bcc is not None:
            payload["bccRecipients"] = self._recipients(bcc)
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "subject": d.get("subject")},
        )

    def send_draft(self, message_id: str) -> Result:
        """Send an existing draft. Returns 202."""
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/send",
            headers=self._headers(),
            expected=(202,),
            transform=lambda _d: {"sent": True, "message_id": message_id},
        )

    def delete_message(self, message_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "message_id": message_id},
        )

    def move_message(self, message_id: str, destination_folder_id: str) -> Result:
        """Move a message to a folder. destination_folder_id can be a well-known name (inbox, drafts, sentitems, deleteditems, archive, junkemail) or a custom folder ID. Returns 201."""
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/move",
            headers=self._headers(),
            json={"destinationId": destination_folder_id},
            expected=(201,),
            transform=lambda d: {
                "moved": True,
                "new_id": d.get("id"),
                "parent_folder_id": d.get("parentFolderId"),
            },
        )

    def copy_message(self, message_id: str, destination_folder_id: str) -> Result:
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/copy",
            headers=self._headers(),
            json={"destinationId": destination_folder_id},
            expected=(201,),
            transform=lambda d: {"copied": True, "new_id": d.get("id")},
        )

    def mark_as_unread(self, message_id: str) -> Result:
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._headers(),
            json={"isRead": False},
            expected=(200,),
            transform=lambda _d: {"marked_unread": True, "message_id": message_id},
        )

    def flag_message(self, message_id: str, flag_status: str = "flagged") -> Result:
        """flag_status: notFlagged | complete | flagged."""
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._headers(),
            json={"flag": {"flagStatus": flag_status}},
            expected=(200,),
            transform=lambda _d: {"flag_status": flag_status, "message_id": message_id},
        )

    def set_message_categories(self, message_id: str, categories: List[str]) -> Result:
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/messages/{message_id}",
            headers=self._headers(),
            json={"categories": categories},
            expected=(200,),
            transform=lambda _d: {"categories": categories, "message_id": message_id},
        )

    def search_messages(
        self, query: str, top: int = 25, folder: Optional[str] = None
    ) -> Result:
        """OData $search across messages (subject, body, attachments). Sorted by relevance."""
        url = (
            f"{GRAPH_API_BASE}/me/mailFolders/{folder}/messages"
            if folder
            else f"{GRAPH_API_BASE}/me/messages"
        )
        return http_request(
            "GET",
            url,
            headers=self._auth_header(),
            params={
                "$search": f'"{query}"',
                "$top": top,
                "$select": "id,from,subject,bodyPreview,receivedDateTime,isRead",
            },
            expected=(200,),
            transform=lambda d: {
                "results": [
                    {
                        "id": m.get("id"),
                        "from": (m.get("from") or {})
                        .get("emailAddress", {})
                        .get("address", ""),
                        "subject": m.get("subject", ""),
                        "received": m.get("receivedDateTime", ""),
                        "preview": m.get("bodyPreview", ""),
                        "is_read": m.get("isRead", False),
                    }
                    for m in d.get("value", [])
                ]
            },
        )

    # ----- Attachments -----

    def list_attachments(self, message_id: str) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/attachments",
            headers=self._auth_header(),
            params={"$select": "id,name,contentType,size,isInline"},
            expected=(200,),
            transform=lambda d: {
                "attachments": [
                    {
                        "id": a.get("id"),
                        "name": a.get("name"),
                        "contentType": a.get("contentType"),
                        "size": a.get("size"),
                        "is_inline": a.get("isInline", False),
                    }
                    for a in d.get("value", [])
                ]
            },
        )

    def get_attachment(self, message_id: str, attachment_id: str) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/attachments/{attachment_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def download_attachment(
        self, message_id: str, attachment_id: str, save_to: str
    ) -> Result:
        """Download an attachment to a local path. Decodes contentBytes (base64)."""
        import os
        import base64

        meta = self.get_attachment(message_id, attachment_id)
        if "error" in meta:
            return meta
        data = meta["result"]
        content_b64 = data.get("contentBytes")
        if not content_b64:
            return {
                "error": "Attachment has no contentBytes (may be itemAttachment or referenceAttachment, not fileAttachment)"
            }
        try:
            save_to = os.path.abspath(save_to)
            parent = os.path.dirname(save_to)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(save_to, "wb") as f:
                f.write(base64.b64decode(content_b64))
            return {
                "ok": True,
                "result": {"saved_to": save_to, "size": os.path.getsize(save_to)},
            }
        except Exception as e:
            return {"error": str(e)}

    def add_attachment(
        self, message_id: str, file_path: str, content_type: Optional[str] = None
    ) -> Result:
        """Attach a local file to a DRAFT message (under 3 MB; large files need session upload)."""
        import os
        import base64
        import mimetypes

        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}"}
        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                content_type = "application/octet-stream"

        with open(file_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")

        payload = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": os.path.basename(file_path),
            "contentType": content_type,
            "contentBytes": content,
        }
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/attachments",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("name"),
                "size": d.get("size"),
            },
        )

    def delete_attachment(self, message_id: str, attachment_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{GRAPH_API_BASE}/me/messages/{message_id}/attachments/{attachment_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "attachment_id": attachment_id},
        )

    # ----- Folders (MailFolder CRUD + traversal) -----

    def get_folder(self, folder_id: str) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailFolders/{folder_id}",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("displayName"),
                "parentFolderId": d.get("parentFolderId"),
                "total": d.get("totalItemCount"),
                "unread": d.get("unreadItemCount"),
            },
        )

    def create_folder(
        self, display_name: str, parent_folder_id: str = "msgfolderroot"
    ) -> Result:
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/mailFolders/{parent_folder_id}/childFolders",
            headers=self._headers(),
            json={"displayName": display_name},
            expected=(201,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("displayName")},
        )

    def update_folder(self, folder_id: str, display_name: str) -> Result:
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/mailFolders/{folder_id}",
            headers=self._headers(),
            json={"displayName": display_name},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("displayName")},
        )

    def delete_folder(self, folder_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{GRAPH_API_BASE}/me/mailFolders/{folder_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "folder_id": folder_id},
        )

    def list_child_folders(self, folder_id: str = "msgfolderroot") -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailFolders/{folder_id}/childFolders",
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

    def list_folder_messages(
        self, folder_id: str, n: int = 25, unread_only: bool = False
    ) -> Result:
        params: Dict[str, Any] = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$select": "id,from,subject,receivedDateTime,isRead,bodyPreview",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailFolders/{folder_id}/messages",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "messages": [
                    {
                        "id": m.get("id"),
                        "from": (m.get("from") or {})
                        .get("emailAddress", {})
                        .get("address", ""),
                        "subject": m.get("subject", ""),
                        "received": m.get("receivedDateTime", ""),
                        "is_read": m.get("isRead", False),
                        "preview": m.get("bodyPreview", ""),
                    }
                    for m in d.get("value", [])
                ]
            },
        )

    # ----- Mailbox settings (out-of-office, timezone, locale) -----

    def get_mailbox_settings(self) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailboxSettings",
            headers=self._auth_header(),
            expected=(200,),
        )

    def update_mailbox_settings(self, settings: Dict[str, Any]) -> Result:
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/mailboxSettings",
            headers=self._headers(),
            json=settings,
            expected=(200,),
        )

    def get_automatic_replies(self) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailboxSettings/automaticRepliesSetting",
            headers=self._auth_header(),
            expected=(200,),
        )

    def update_automatic_replies(
        self,
        status: str,
        internal_reply: Optional[str] = None,
        external_reply: Optional[str] = None,
        external_audience: str = "all",
        scheduled_start: Optional[str] = None,
        scheduled_end: Optional[str] = None,
    ) -> Result:
        """status: disabled | alwaysEnabled | scheduled. external_audience: none|contactsOnly|all."""
        payload: Dict[str, Any] = {
            "automaticRepliesSetting": {
                "status": status,
                "externalAudience": external_audience,
            }
        }
        ars = payload["automaticRepliesSetting"]
        if internal_reply is not None:
            ars["internalReplyMessage"] = internal_reply
        if external_reply is not None:
            ars["externalReplyMessage"] = external_reply
        if scheduled_start and scheduled_end:
            ars["scheduledStartDateTime"] = {
                "dateTime": scheduled_start,
                "timeZone": "UTC",
            }
            ars["scheduledEndDateTime"] = {"dateTime": scheduled_end, "timeZone": "UTC"}
        return http_request(
            "PATCH",
            f"{GRAPH_API_BASE}/me/mailboxSettings",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "status": d.get("automaticRepliesSetting", {}).get("status")
            },
        )

    # ----- Inbox rules -----

    def list_inbox_rules(self) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {
                "rules": [
                    {
                        "id": r.get("id"),
                        "name": r.get("displayName"),
                        "sequence": r.get("sequence"),
                        "enabled": r.get("isEnabled"),
                    }
                    for r in d.get("value", [])
                ]
            },
        )

    def create_inbox_rule(
        self,
        display_name: str,
        conditions: Dict[str, Any],
        actions: Dict[str, Any],
        sequence: int = 1,
        is_enabled: bool = True,
    ) -> Result:
        payload = {
            "displayName": display_name,
            "sequence": sequence,
            "isEnabled": is_enabled,
            "conditions": conditions,
            "actions": actions,
        }
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("displayName")},
        )

    def delete_inbox_rule(self, rule_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules/{rule_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "rule_id": rule_id},
        )

    # ----- Categories (Outlook master categories) -----

    def list_categories(self) -> Result:
        return http_request(
            "GET",
            f"{GRAPH_API_BASE}/me/outlook/masterCategories",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {
                "categories": [
                    {
                        "id": c.get("id"),
                        "displayName": c.get("displayName"),
                        "color": c.get("color"),
                    }
                    for c in d.get("value", [])
                ]
            },
        )

    def create_category(self, display_name: str, color: str = "preset0") -> Result:
        """color: preset0..preset24 (see Microsoft Graph categoryColor enum)."""
        return http_request(
            "POST",
            f"{GRAPH_API_BASE}/me/outlook/masterCategories",
            headers=self._headers(),
            json={"displayName": display_name, "color": color},
            expected=(201,),
            transform=lambda d: {
                "id": d.get("id"),
                "displayName": d.get("displayName"),
                "color": d.get("color"),
            },
        )

    def delete_category(self, category_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{GRAPH_API_BASE}/me/outlook/masterCategories/{category_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "category_id": category_id},
        )
