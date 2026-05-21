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
        {
            "key": "process_incoming",
            "label": "Auto-process incoming emails",
            "type": "checkbox",
            "help": "When on, every new INBOX message is forwarded to the agent. "
            "Turn off to keep Gmail send-only - the agent ignores incoming mail.",
        },
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
            self._history_id = profile.get("historyId")
            logger.info(
                f"[GMAIL] profile: {profile.get('emailAddress')}, historyId: {self._history_id}"
            )
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
        result = await arequest(
            "GET",
            f"{GMAIL_API_BASE}/users/me/profile",
            headers=self._auth_header(),
            expected=(200,),
        )
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
            "GET",
            f"{GMAIL_API_BASE}/users/me/history",
            headers=self._auth_header(),
            params={
                "startHistoryId": self._history_id,
                "historyTypes": "messageAdded",
                "labelId": "INBOX",
            },
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
                if (
                    msg_id
                    and "INBOX" in msg.get("labelIds", [])
                    and msg_id not in self._seen_message_ids
                ):
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
            "GET",
            f"{GMAIL_API_BASE}/users/me/messages/{msg_id}",
            headers=self._auth_header(),
            params=[
                ("format", "metadata"),
                ("metadataHeaders", "From"),
                ("metadataHeaders", "Subject"),
                ("metadataHeaders", "Date"),
            ],
            expected=(200,),
        )
        if "error" in result:
            return

        msg = result["result"]
        headers = {
            h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])
        }
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
            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=sender_email,
                    sender_name=sender_name or sender_email,
                    text=text,
                    channel_id=msg.get("threadId", ""),
                    message_id=msg_id,
                    timestamp=timestamp,
                    raw=msg,
                )
            )

    # ----- REST methods -----

    @staticmethod
    def _encode_email(
        to_email: str,
        from_email: str,
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None,
    ) -> str:
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
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{os.path.basename(file_path)}"',
                    )
                    msg.attach(part)

        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> Result:
        cred = self._load()
        sender = from_email or cred.email
        raw = self._encode_email(to, sender, subject, body, attachments)
        return http_request(
            "POST",
            f"{GMAIL_API_BASE}/users/me/messages/send",
            headers=self._headers(),
            json={"raw": raw},
            expected=(200,),
        )

    def list_emails(self, n: int = 5, unread_only: bool = True) -> Result:
        params: Dict[str, Any] = {"maxResults": n, "labelIds": ["INBOX"]}
        if unread_only:
            params["q"] = "is:unread"
        return http_request(
            "GET",
            f"{GMAIL_API_BASE}/users/me/messages",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("messages", []),
        )

    def get_email(self, message_id: str, full_body: bool = False) -> Result:
        format_type = "full" if full_body else "metadata"

        def _shape(msg):
            email_info: Dict[str, Any] = {
                "id": msg.get("id"),
                "snippet": msg.get("snippet", ""),
                "headers": {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                },
            }
            if full_body and "parts" in msg.get("payload", {}):
                for part in msg["payload"]["parts"]:
                    if part.get("mimeType") == "text/plain" and "data" in part.get(
                        "body", {}
                    ):
                        email_info["body"] = base64.urlsafe_b64decode(
                            part["body"]["data"].encode("ASCII")
                        ).decode("utf-8")
                        break
            return email_info

        return http_request(
            "GET",
            f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
            headers=self._auth_header(),
            params={
                "format": format_type,
                "metadataHeaders": ["From", "To", "Subject", "Date"],
            },
            expected=(200,),
            transform=_shape,
        )

    def read_top_emails(self, n: int = 5, full_body: bool = False) -> Result:
        listing = self.list_emails(n=n, unread_only=False)
        if "error" in listing:
            return listing
        emails: List[Dict[str, Any]] = []
        for msg in listing.get("result", []):
            detail = self.get_email(msg["id"], full_body=full_body)
            emails.append(
                detail.get("result", detail) if "error" not in detail else detail
            )
        return {"ok": True, "result": emails}
