# -*- coding: utf-8 -*-
"""Gmail - granular Google integration.

A user can connect just Gmail (without granting Calendar/Drive/YouTube
scopes) by clicking Connect on the Gmail card. The credential is saved
to ``gmail.json``. The "Google Workspace" meta-integration also writes
to this file when it cascades, so they stay interchangeable.

Structure mirrors any single-purpose integration in this package — see
``github/`` for the canonical shape. The Google-specific pieces
(``GoogleCredential``, ``OAuthFlow`` factory, token refresh) live in
``../_google_common.py`` and are shared with the other per-service
integrations (calendar / drive / docs / youtube).
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from dataclasses import dataclass
from datetime import timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    PlatformMessage,
    load_config,
    register_client,
    register_handler,
)
from ...helpers import Result, arequest, request as http_request
from ...logger import get_logger
from .._google_common import (
    GMAIL_SCOPES,
    GoogleApiClientMixin,
    GoogleCredential,
    make_google_oauth,
    run_google_login,
    run_google_logout,
    run_google_status,
)

logger = get_logger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
POLL_INTERVAL = 5
RETRY_DELAY = 10


GMAIL = IntegrationSpec(
    name="gmail",
    cred_class=GoogleCredential,
    cred_file="gmail.json",
    platform_id="gmail",
)


@dataclass
class GmailConfig:
    """Runtime knobs persisted to ``gmail_config.json``."""
    # When True (default), every new INBOX message is forwarded to the
    # agent as a PlatformMessage. When False, the listener still polls
    # Gmail history (so send/read REST methods stay live) but does not
    # dispatch incoming emails to the agent - Gmail becomes effectively
    # send-only.
    process_incoming: bool = True


def _gmail_config_file() -> str:
    """``gmail.json`` â†’ ``gmail_config.json``."""
    stem = GMAIL.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# -----------------------------------------------------------------
# Handler - auth flow only
# -----------------------------------------------------------------

@register_handler(GMAIL.name)
class GmailHandler(IntegrationHandler):
    spec = GMAIL
    display_name = "Gmail"
    description = "Email - read, search, and send"
    auth_type = "oauth"
    icon = "gmail"
    fields: List = []

    config_class = GmailConfig
    config_fields = [
        {"key": "process_incoming", "label": "Auto-process incoming emails", "type": "checkbox",
         "help": "When on, every new INBOX message is forwarded to the agent. "
                 "Turn off to keep Gmail send-only - the agent ignores incoming mail."},
    ]

    oauth = make_google_oauth(GMAIL_SCOPES)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_login(self.spec, self.oauth, "Gmail")

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_logout(self.spec, "Gmail")

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Gmail")


# -----------------------------------------------------------------
# Client - Gmail listener + REST methods
# -----------------------------------------------------------------

@register_client
class GmailClient(GoogleApiClientMixin, BasePlatformClient):
    # Mixin first so its concrete ``has_credentials`` / ``_load`` / token
    # methods satisfy ``BasePlatformClient``'s abstract slots. See
    # ``_google_common.py`` for the rationale.
    spec = GMAIL
    PLATFORM_ID = GMAIL.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[GoogleCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._history_id: Optional[str] = None
        self._seen_message_ids: set = set()

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return self.send_email(to=recipient, subject=kwargs.get("subject", ""), body=text)

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
            self._history_id = profile.get("historyId")
            logger.info(f"[GMAIL] profile: {profile.get('emailAddress')}, historyId: {self._history_id}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Gmail: {e}")

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

    # ----- Listener internals -----

    async def _async_get_profile(self) -> Dict[str, Any]:
        result = await arequest("GET", f"{GMAIL_API_BASE}/users/me/profile",
                                headers=self._auth_header(), expected=(200,))
        if "error" in result:
            raise RuntimeError(f"Gmail profile {result['error']}")
        return result["result"]

    async def _poll_loop(self) -> None:
        while self._listening:
            try:
                await self._check_history()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[GMAIL] Poll error: {e}")
                if "404" in str(e) or "historyId" in str(e).lower():
                    try:
                        profile = await self._async_get_profile()
                        self._history_id = profile.get("historyId")
                    except Exception:
                        pass
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_history(self) -> None:
        if not self._history_id:
            return
        result = await arequest(
            "GET", f"{GMAIL_API_BASE}/users/me/history",
            headers=self._auth_header(),
            params={"startHistoryId": self._history_id, "historyTypes": "messageAdded", "labelId": "INBOX"},
            expected=(200,),
        )
        if "error" in result:
            if "404" in result["error"]:
                raise RuntimeError("historyId expired (404)")
            logger.warning(f"[GMAIL] history.list {result['error']}")
            return

        data = result["result"] or {}
        new_history_id = data.get("historyId")
        if new_history_id:
            self._history_id = new_history_id

        new_msg_ids = []
        for record in data.get("history", []):
            for added in record.get("messagesAdded", []):
                msg = added.get("message", {})
                msg_id = msg.get("id", "")
                if msg_id and "INBOX" in msg.get("labelIds", []) and msg_id not in self._seen_message_ids:
                    new_msg_ids.append(msg_id)
                    self._seen_message_ids.add(msg_id)

        if len(self._seen_message_ids) > 500:
            self._seen_message_ids = set(list(self._seen_message_ids)[-200:])

        for msg_id in new_msg_ids:
            try:
                await self._fetch_and_dispatch(msg_id)
            except Exception as e:
                logger.debug(f"[GMAIL] Error processing message {msg_id}: {e}")

    async def _fetch_and_dispatch(self, msg_id: str) -> None:
        cfg = load_config(_gmail_config_file(), GmailConfig) or GmailConfig()
        if not cfg.process_incoming:
            return

        result = await arequest(
            "GET", f"{GMAIL_API_BASE}/users/me/messages/{msg_id}",
            headers=self._auth_header(),
            params=[("format", "metadata"), ("metadataHeaders", "From"),
                    ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")],
            expected=(200,),
        )
        if "error" in result:
            return

        msg = result["result"]
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        from_header = headers.get("From", "")
        subject = headers.get("Subject", "(no subject)")
        snippet = msg.get("snippet", "")

        sender_name = from_header
        sender_email = from_header
        if "<" in from_header and ">" in from_header:
            parts = from_header.rsplit("<", 1)
            sender_name = parts[0].strip().strip('"')
            sender_email = parts[1].rstrip(">").strip()

        cred = self._load()
        if sender_email.lower() == (cred.email or "").lower():
            return

        timestamp = None
        try:
            from email.utils import parsedate_to_datetime
            timestamp = parsedate_to_datetime(headers.get("Date", ""))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        text = f"Subject: {subject}\n{snippet}" if snippet else f"Subject: {subject}"

        if self._message_callback:
            await self._message_callback(PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=sender_email,
                sender_name=sender_name or sender_email,
                text=text,
                channel_id=msg.get("threadId", ""),
                message_id=msg_id,
                timestamp=timestamp,
                raw=msg,
            ))

    # ----- REST methods -----

    @staticmethod
    def _encode_email(to_email: str, from_email: str, subject: str, body: str,
                      attachments: Optional[List[str]] = None) -> str:
        msg = MIMEMultipart()
        msg["to"] = to_email
        msg["from"] = from_email
        msg["subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_path in attachments:
                if not os.path.isfile(file_path):
                    continue
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, subtype = mime_type.split("/", 1)
                with open(file_path, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(file_path)}"')
                    msg.attach(part)

        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def send_email(self, to: str, subject: str, body: str,
                   from_email: Optional[str] = None,
                   attachments: Optional[List[str]] = None) -> Result:
        cred = self._load()
        sender = from_email or cred.email
        raw = self._encode_email(to, sender, subject, body, attachments)
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/send",
            headers=self._headers(), json={"raw": raw}, expected=(200,),
        )

    def list_emails(self, n: int = 5, unread_only: bool = True) -> Result:
        params: Dict[str, Any] = {"maxResults": n, "labelIds": ["INBOX"]}
        if unread_only:
            params["q"] = "is:unread"
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/messages",
            headers=self._auth_header(), params=params, expected=(200,),
            transform=lambda d: d.get("messages", []),
        )

    def get_email(self, message_id: str, full_body: bool = False) -> Result:
        format_type = "full" if full_body else "metadata"

        def _shape(msg):
            email_info: Dict[str, Any] = {
                "id": msg.get("id"), "snippet": msg.get("snippet", ""),
                "headers": {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])},
            }
            if full_body and "parts" in msg.get("payload", {}):
                for part in msg["payload"]["parts"]:
                    if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
                        email_info["body"] = base64.urlsafe_b64decode(
                            part["body"]["data"].encode("ASCII")
                        ).decode("utf-8")
                        break
            return email_info

        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
            headers=self._auth_header(),
            params={"format": format_type, "metadataHeaders": ["From", "To", "Subject", "Date"]},
            expected=(200,), transform=_shape,
        )

    def read_top_emails(self, n: int = 5, full_body: bool = False) -> Result:
        listing = self.list_emails(n=n, unread_only=False)
        if "error" in listing:
            return listing
        emails: List[Dict[str, Any]] = []
        for msg in listing.get("result", []):
            detail = self.get_email(msg["id"], full_body=full_body)
            emails.append(detail.get("result", detail) if "error" not in detail else detail)
        return {"ok": True, "result": emails}

    # ----- Messages: search / modify / trash / untrash / delete / batch -----

    def search_messages(self, query: str, max_results: int = 25,
                        label_ids: Optional[List[str]] = None,
                        include_spam_trash: bool = False) -> Result:
        """Search messages by Gmail's q syntax (e.g. 'from:alice subject:invoice newer_than:7d')."""
        params: Dict[str, Any] = {
            "q": query,
            "maxResults": max_results,
            "includeSpamTrash": str(include_spam_trash).lower(),
        }
        if label_ids:
            params["labelIds"] = label_ids
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/messages",
            headers=self._auth_header(), params=params, expected=(200,),
            transform=lambda d: {"messages": d.get("messages", []),
                                 "resultSizeEstimate": d.get("resultSizeEstimate", 0)},
        )

    def modify_message_labels(self, message_id: str,
                              add_label_ids: Optional[List[str]] = None,
                              remove_label_ids: Optional[List[str]] = None) -> Result:
        payload: Dict[str, Any] = {}
        if add_label_ids: payload["addLabelIds"] = add_label_ids
        if remove_label_ids: payload["removeLabelIds"] = remove_label_ids
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/{message_id}/modify",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "labelIds": d.get("labelIds", [])},
        )

    def trash_message(self, message_id: str) -> Result:
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/{message_id}/trash",
            headers=self._auth_header(), expected=(200,),
            transform=lambda d: {"id": d.get("id"), "trashed": True},
        )

    def untrash_message(self, message_id: str) -> Result:
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/{message_id}/untrash",
            headers=self._auth_header(), expected=(200,),
            transform=lambda d: {"id": d.get("id"), "trashed": False},
        )

    def delete_message(self, message_id: str) -> Result:
        """Permanently delete. Use trash_message for soft delete."""
        return http_request(
            "DELETE", f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
            headers=self._auth_header(), expected=(204,),
            transform=lambda _d: {"deleted": True, "message_id": message_id},
        )

    def batch_modify_messages(self, message_ids: List[str],
                              add_label_ids: Optional[List[str]] = None,
                              remove_label_ids: Optional[List[str]] = None) -> Result:
        payload: Dict[str, Any] = {"ids": message_ids}
        if add_label_ids: payload["addLabelIds"] = add_label_ids
        if remove_label_ids: payload["removeLabelIds"] = remove_label_ids
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/batchModify",
            headers=self._headers(), json=payload, expected=(204,),
            transform=lambda _d: {"modified": len(message_ids)},
        )

    def batch_delete_messages(self, message_ids: List[str]) -> Result:
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/batchDelete",
            headers=self._headers(), json={"ids": message_ids}, expected=(204,),
            transform=lambda _d: {"deleted": len(message_ids)},
        )

    # ----- Reply / forward (build proper RFC 2822 message and send via threadId) -----

    def _fetch_reply_headers(self, message_id: str) -> Dict[str, str]:
        """Fetch original message metadata + Message-ID/Subject/From headers."""
        result = http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
            headers=self._auth_header(),
            params=[("format", "metadata"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "To"),
                    ("metadataHeaders", "Cc"),
                    ("metadataHeaders", "Subject"),
                    ("metadataHeaders", "Message-ID"),
                    ("metadataHeaders", "References")],
            expected=(200,),
        )
        if "error" in result:
            return {"_error": result["error"], "_thread_id": ""}
        data = result["result"]
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        headers["_thread_id"] = data.get("threadId", "")
        return headers

    def reply_to_message(self, message_id: str, body: str,
                         reply_all: bool = False,
                         attachments: Optional[List[str]] = None) -> Result:
        info = self._fetch_reply_headers(message_id)
        if info.get("_error"):
            return {"error": info["_error"]}
        cred = self._load()

        orig_subject = info.get("Subject", "")
        reply_subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        msg_id_hdr = info.get("Message-ID") or info.get("Message-Id", "")
        references = info.get("References", "")
        thread_id = info["_thread_id"]

        # Default: reply to sender. If reply_all, also CC the original To/Cc minus self.
        from_addr = info.get("From", "")
        cc_addrs: List[str] = []
        if reply_all:
            for hdr in ("To", "Cc"):
                if info.get(hdr):
                    cc_addrs.extend([a.strip() for a in info[hdr].split(",")])
            self_email = (cred.email or "").lower()
            cc_addrs = [a for a in cc_addrs if a and self_email not in a.lower()]

        msg = MIMEMultipart()
        msg["to"] = from_addr
        msg["from"] = cred.email
        msg["subject"] = reply_subject
        if cc_addrs:
            msg["cc"] = ", ".join(cc_addrs)
        if msg_id_hdr:
            msg["In-Reply-To"] = msg_id_hdr
            msg["References"] = (references + " " + msg_id_hdr).strip() if references else msg_id_hdr
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_path in attachments:
                if not os.path.isfile(file_path):
                    continue
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, subtype = mime_type.split("/", 1)
                with open(file_path, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition",
                                    f'attachment; filename="{os.path.basename(file_path)}"')
                    msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload: Dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/send",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "threadId": d.get("threadId"),
                                 "replied_to": message_id},
        )

    def forward_message(self, message_id: str, to: str, body: str = "",
                        attachments: Optional[List[str]] = None) -> Result:
        info = self._fetch_reply_headers(message_id)
        if info.get("_error"):
            return {"error": info["_error"]}
        cred = self._load()

        orig_subject = info.get("Subject", "")
        fwd_subject = orig_subject if orig_subject.lower().startswith("fwd:") else f"Fwd: {orig_subject}"
        thread_id = info["_thread_id"]

        msg = MIMEMultipart()
        msg["to"] = to
        msg["from"] = cred.email
        msg["subject"] = fwd_subject
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_path in attachments:
                if not os.path.isfile(file_path):
                    continue
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, subtype = mime_type.split("/", 1)
                with open(file_path, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition",
                                    f'attachment; filename="{os.path.basename(file_path)}"')
                    msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload: Dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/messages/send",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "threadId": d.get("threadId"),
                                 "forwarded": message_id, "to": to},
        )

    # ----- Threads -----

    def list_threads(self, query: Optional[str] = None,
                     label_ids: Optional[List[str]] = None,
                     max_results: int = 25) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if query: params["q"] = query
        if label_ids: params["labelIds"] = label_ids
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/threads",
            headers=self._auth_header(), params=params, expected=(200,),
            transform=lambda d: {"threads": d.get("threads", []),
                                 "resultSizeEstimate": d.get("resultSizeEstimate", 0)},
        )

    def get_thread(self, thread_id: str, fmt: str = "metadata") -> Result:
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/threads/{thread_id}",
            headers=self._auth_header(),
            params={"format": fmt}, expected=(200,),
        )

    def modify_thread_labels(self, thread_id: str,
                             add_label_ids: Optional[List[str]] = None,
                             remove_label_ids: Optional[List[str]] = None) -> Result:
        payload: Dict[str, Any] = {}
        if add_label_ids: payload["addLabelIds"] = add_label_ids
        if remove_label_ids: payload["removeLabelIds"] = remove_label_ids
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/threads/{thread_id}/modify",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "messages": len(d.get("messages", []))},
        )

    def trash_thread(self, thread_id: str) -> Result:
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/threads/{thread_id}/trash",
            headers=self._auth_header(), expected=(200,),
            transform=lambda d: {"id": d.get("id"), "trashed": True},
        )

    def untrash_thread(self, thread_id: str) -> Result:
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/threads/{thread_id}/untrash",
            headers=self._auth_header(), expected=(200,),
            transform=lambda d: {"id": d.get("id"), "trashed": False},
        )

    def delete_thread(self, thread_id: str) -> Result:
        return http_request(
            "DELETE", f"{GMAIL_API_BASE}/users/me/threads/{thread_id}",
            headers=self._auth_header(), expected=(204,),
            transform=lambda _d: {"deleted": True, "thread_id": thread_id},
        )

    # ----- Drafts -----

    def list_drafts(self, max_results: int = 25, query: Optional[str] = None) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if query: params["q"] = query
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/drafts",
            headers=self._auth_header(), params=params, expected=(200,),
            transform=lambda d: {"drafts": d.get("drafts", [])},
        )

    def get_draft(self, draft_id: str, fmt: str = "metadata") -> Result:
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/drafts/{draft_id}",
            headers=self._auth_header(), params={"format": fmt}, expected=(200,),
        )

    def create_draft(self, to: str, subject: str, body: str,
                     cc: Optional[str] = None, bcc: Optional[str] = None,
                     attachments: Optional[List[str]] = None) -> Result:
        cred = self._load()
        msg = MIMEMultipart()
        msg["to"] = to
        msg["from"] = cred.email
        msg["subject"] = subject
        if cc: msg["cc"] = cc
        if bcc: msg["bcc"] = bcc
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_path in attachments:
                if not os.path.isfile(file_path):
                    continue
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, subtype = mime_type.split("/", 1)
                with open(file_path, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition",
                                    f'attachment; filename="{os.path.basename(file_path)}"')
                    msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/drafts",
            headers=self._headers(),
            json={"message": {"raw": raw}}, expected=(200,),
            transform=lambda d: {"id": d.get("id"),
                                 "message_id": d.get("message", {}).get("id")},
        )

    def update_draft(self, draft_id: str, to: str, subject: str, body: str,
                     cc: Optional[str] = None, bcc: Optional[str] = None,
                     attachments: Optional[List[str]] = None) -> Result:
        """Replaces the draft content (PUT)."""
        cred = self._load()
        msg = MIMEMultipart()
        msg["to"] = to
        msg["from"] = cred.email
        msg["subject"] = subject
        if cc: msg["cc"] = cc
        if bcc: msg["bcc"] = bcc
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_path in attachments:
                if not os.path.isfile(file_path):
                    continue
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, subtype = mime_type.split("/", 1)
                with open(file_path, "rb") as f:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition",
                                    f'attachment; filename="{os.path.basename(file_path)}"')
                    msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return http_request(
            "PUT", f"{GMAIL_API_BASE}/users/me/drafts/{draft_id}",
            headers=self._headers(),
            json={"message": {"raw": raw}}, expected=(200,),
            transform=lambda d: {"id": d.get("id")},
        )

    def send_draft(self, draft_id: str) -> Result:
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/drafts/send",
            headers=self._headers(), json={"id": draft_id}, expected=(200,),
            transform=lambda d: {"sent": True, "message_id": d.get("id"), "draft_id": draft_id},
        )

    def delete_draft(self, draft_id: str) -> Result:
        return http_request(
            "DELETE", f"{GMAIL_API_BASE}/users/me/drafts/{draft_id}",
            headers=self._auth_header(), expected=(204,),
            transform=lambda _d: {"deleted": True, "draft_id": draft_id},
        )

    # ----- Labels -----

    def list_labels(self) -> Result:
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/labels",
            headers=self._auth_header(), expected=(200,),
            transform=lambda d: {"labels": [
                {"id": l.get("id"), "name": l.get("name"), "type": l.get("type"),
                 "messageListVisibility": l.get("messageListVisibility"),
                 "labelListVisibility": l.get("labelListVisibility")}
                for l in d.get("labels", [])
            ]},
        )

    def get_label(self, label_id: str) -> Result:
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/labels/{label_id}",
            headers=self._auth_header(), expected=(200,),
        )

    def create_label(self, name: str,
                     label_list_visibility: str = "labelShow",
                     message_list_visibility: str = "show",
                     background_color: Optional[str] = None,
                     text_color: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {
            "name": name,
            "labelListVisibility": label_list_visibility,
            "messageListVisibility": message_list_visibility,
        }
        if background_color and text_color:
            payload["color"] = {"backgroundColor": background_color, "textColor": text_color}
        return http_request(
            "POST", f"{GMAIL_API_BASE}/users/me/labels",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("name")},
        )

    def update_label(self, label_id: str, name: Optional[str] = None,
                     label_list_visibility: Optional[str] = None,
                     message_list_visibility: Optional[str] = None,
                     background_color: Optional[str] = None,
                     text_color: Optional[str] = None) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None: payload["name"] = name
        if label_list_visibility is not None: payload["labelListVisibility"] = label_list_visibility
        if message_list_visibility is not None: payload["messageListVisibility"] = message_list_visibility
        if background_color and text_color:
            payload["color"] = {"backgroundColor": background_color, "textColor": text_color}
        return http_request(
            "PATCH", f"{GMAIL_API_BASE}/users/me/labels/{label_id}",
            headers=self._headers(), json=payload, expected=(200,),
            transform=lambda d: {"id": d.get("id"), "name": d.get("name")},
        )

    def delete_label(self, label_id: str) -> Result:
        return http_request(
            "DELETE", f"{GMAIL_API_BASE}/users/me/labels/{label_id}",
            headers=self._auth_header(), expected=(204,),
            transform=lambda _d: {"deleted": True, "label_id": label_id},
        )

    # ----- Attachments -----

    def download_attachment(self, message_id: str, attachment_id: str,
                            save_to: str) -> Result:
        """Download an attachment to a local path. Decodes Gmail's urlsafe base64 data."""
        import os as _os

        result = http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/messages/{message_id}/attachments/{attachment_id}",
            headers=self._auth_header(), expected=(200,),
        )
        if "error" in result:
            return result
        data_b64 = result["result"].get("data", "")
        if not data_b64:
            return {"error": "Attachment had no data field"}
        try:
            save_to = _os.path.abspath(save_to)
            parent = _os.path.dirname(save_to)
            if parent:
                _os.makedirs(parent, exist_ok=True)
            with open(save_to, "wb") as f:
                f.write(base64.urlsafe_b64decode(data_b64.encode("ascii")))
            return {"ok": True, "result": {"saved_to": save_to, "size": _os.path.getsize(save_to)}}
        except Exception as e:
            return {"error": str(e)}

    # ----- Profile -----

    def get_profile(self) -> Result:
        return http_request(
            "GET", f"{GMAIL_API_BASE}/users/me/profile",
            headers=self._auth_header(), expected=(200,),
            transform=lambda d: {
                "emailAddress": d.get("emailAddress"),
                "messagesTotal": d.get("messagesTotal"),
                "threadsTotal": d.get("threadsTotal"),
                "historyId": d.get("historyId"),
            },
        )
