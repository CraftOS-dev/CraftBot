"""Outlook operations — schemas for outlook_actions.py.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced).

Complete port of app/data/action/integrations/outlook/outlook_actions.py
(all 40 actions). Names, descriptions, schemas, arg maps, envelope
options, and the lean/include_metadata result shaping are reproduced
verbatim; ``irreversible`` sends plus permanent deletes map to
``destructive=True``. The intentionally-unexposed Graph
surfaces (webhooks, >3 MB upload sessions, extensions, calendar,
delta sync, delegation) stay unexposed here for the same reasons.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from ...contracts import Operation
from .._shared import client_op

_UNSET = object()


def _csv_list(text: Optional[str], default: Any = _UNSET) -> Any:
    """Local copy of app.utils.text.csv_list (providers are host-blind)."""
    if not text:
        return [] if default is _UNSET else default
    return [v.strip() for v in text.split(",") if v.strip()]


def _forward_outlook_email_op() -> Operation:
    """forward_outlook_email with the empty-recipient guard."""
    base = client_op(
        "forward_outlook_email",
        "forward_message",
        description="Forward an email to other recipients.",
        destructive=True,  # outward-facing send
        parallelizable=False,
        tags=("outlook_mail", "outlook"),
        unwrap_envelope=True,
        fail_message="Failed to forward.",
        input_schema={
            "message_id": {
                "type": "string",
                "description": "Message ID.",
                "example": "AAMk...",
            },
            "to_recipients": {
                "type": "string",
                "description": "Comma-separated recipient emails.",
                "example": "bob@example.com",
            },
            "comment": {
                "type": "string",
                "description": "Optional intro comment.",
                "example": "",
            },
        },
        arg_map=lambda d: {
            "message_id": d["message_id"],
            "to_recipients": _csv_list(d["to_recipients"]),
            "comment": d.get("comment", ""),
        },
    )
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if not _csv_list(input_data.get("to_recipients", "")):
            return {"status": "error", "message": "No recipients provided."}
        return await inner(client, input_data)

    return replace(base, fn=fn)


def _get_outlook_mailbox_settings_op() -> Operation:
    """get_outlook_mailbox_settings with the lean shaping."""
    base = client_op(
        "get_outlook_mailbox_settings",
        "get_mailbox_settings",
        description=(
            "Get the user's mailbox settings. Default returns {timeZone, "
            "language, workingHours, automaticRepliesSetting.status}; set "
            "include_metadata for the raw settings."
        ),
        tags=("outlook_settings",),
        unwrap_envelope=True,
        fail_message="Failed to get settings.",
        input_schema={
            "include_metadata": {
                "type": "boolean",
                "description": "Return the raw mailboxSettings resource (default false = lean).",
                "example": False,
            },
        },
        arg_map=lambda d: {},
    )
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        res = await inner(client, input_data)
        if not input_data.get("include_metadata") and res.get("status") == "success":
            settings = res.get("result")
            if isinstance(settings, dict):
                lean: Dict[str, Any] = {"timeZone": settings.get("timeZone")}
                language = settings.get("language") or {}
                if language.get("displayName"):
                    lean["language"] = {"displayName": language["displayName"]}
                wh = settings.get("workingHours") or {}
                if wh:
                    lean["workingHours"] = {
                        k: wh.get(k)
                        for k in ("daysOfWeek", "startTime", "endTime")
                        if wh.get(k) is not None
                    }
                ars = settings.get("automaticRepliesSetting") or {}
                if ars.get("status"):
                    lean["automaticRepliesSetting"] = {"status": ars["status"]}
                res = {**res, "result": lean}
        return res

    return replace(base, fn=fn)


def _get_outlook_automatic_replies_op() -> Operation:
    """get_outlook_automatic_replies with the lean/HTML-strip shaping."""
    base = client_op(
        "get_outlook_automatic_replies",
        "get_automatic_replies",
        description=(
            "Get the current out-of-office / automatic reply settings. "
            "Default returns {status, schedule, reply messages as plain "
            "text}; set include_metadata for the raw setting."
        ),
        tags=("outlook_settings", "outlook"),
        unwrap_envelope=True,
        fail_message="Failed to get auto-replies.",
        input_schema={
            "include_metadata": {
                "type": "boolean",
                "description": "Return the raw automaticRepliesSetting (default false = lean, HTML stripped).",
                "example": False,
            },
        },
        arg_map=lambda d: {},
    )
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        res = await inner(client, input_data)
        if not input_data.get("include_metadata") and res.get("status") == "success":
            setting = res.get("result")
            if isinstance(setting, dict):
                import html
                import re

                def _strip_html(value):
                    if not isinstance(value, str):
                        return value
                    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()

                res = {
                    **res,
                    "result": {
                        k: v
                        for k, v in {
                            "status": setting.get("status"),
                            "scheduledStartDateTime": setting.get(
                                "scheduledStartDateTime"
                            ),
                            "scheduledEndDateTime": setting.get("scheduledEndDateTime"),
                            "internalReplyMessage": _strip_html(
                                setting.get("internalReplyMessage")
                            ),
                            "externalReplyMessage": _strip_html(
                                setting.get("externalReplyMessage")
                            ),
                        }.items()
                        if v is not None
                    },
                }
        return res

    return replace(base, fn=fn)


def _update_draft_args(d: Dict[str, Any]) -> Dict[str, Any]:
    """Presence-based semantics: only keys present in the request
    replace draft fields; absent keys pass None (client skips them)."""
    return {
        "message_id": d["message_id"],
        "subject": d.get("subject") if "subject" in d else None,
        "body": d.get("body") if "body" in d else None,
        "html": bool(d.get("html", False)),
        "to": _csv_list(d["to"], default=None) if "to" in d else None,
        "cc": _csv_list(d["cc"], default=None) if "cc" in d else None,
        "bcc": _csv_list(d["bcc"], default=None) if "bcc" in d else None,
    }


def _update_automatic_replies_args(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": d["status"],
        "internal_reply": d.get("internal_reply") if "internal_reply" in d else None,
        "external_reply": d.get("external_reply") if "external_reply" in d else None,
        "external_audience": d.get("external_audience", "all"),
        "scheduled_start": d.get("scheduled_start") or None,
        "scheduled_end": d.get("scheduled_end") or None,
    }


def build_operations() -> List[Operation]:
    return [
        # ── Mail — read / send / reply / forward / draft / lifecycle ─────
        client_op(
            "send_outlook_email",
            "send_email",
            description="Send an email via Outlook (Microsoft 365).",
            destructive=True,  # outward-facing send
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            success_message="Email sent.",
            fail_message="Failed to send email.",
            input_schema={
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                    "example": "user@example.com",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject.",
                    "example": "Meeting Follow-up",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text.",
                    "example": "Hi, here are the notes...",
                },
                "cc": {
                    "type": "string",
                    "description": "Optional CC recipients (comma-separated).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "to": d["to"],
                "subject": d["subject"],
                "body": d["body"],
                "cc": d.get("cc"),
            },
        ),
        client_op(
            "list_outlook_emails",
            "list_emails",
            description="List recent emails from Outlook inbox.",
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to list emails.",
            input_schema={
                "count": {
                    "type": "integer",
                    "description": "Number of recent emails to list.",
                    "example": 10,
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Only show unread emails.",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "n": d.get("count", 10),
                "unread_only": d.get("unread_only", False),
            },
        ),
        client_op(
            "get_outlook_email",
            "get_email",
            description=(
                "Get full details of a specific Outlook email by message ID. "
                "Body is plain text by default; set include_metadata for the "
                "HTML body."
            ),
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to get email.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Outlook message ID.",
                    "example": "AAMk...",
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Return the HTML body instead of plain text (default false).",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "include_metadata": bool(d.get("include_metadata", False)),
            },
        ),
        client_op(
            "read_top_outlook_emails",
            "read_top_emails",
            description=(
                "Read the top N recent Outlook emails with details. With "
                "full_body=true, bodies are plain text by default; set "
                "include_metadata for HTML bodies."
            ),
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to read emails.",
            input_schema={
                "count": {
                    "type": "integer",
                    "description": "Number of emails to read.",
                    "example": 5,
                },
                "full_body": {
                    "type": "boolean",
                    "description": "Include full body text.",
                    "example": False,
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "With full_body, return HTML bodies instead of plain text (default false).",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "n": d.get("count", 5),
                "full_body": d.get("full_body", False),
                "include_metadata": bool(d.get("include_metadata", False)),
            },
        ),
        client_op(
            "search_outlook_emails",
            "search_messages",
            description=(
                "Search Outlook messages by free-text query (matches subject, "
                "body, attachments). Sorted by relevance."
            ),
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to search.",
            input_schema={
                "query": {
                    "type": "string",
                    "description": "Search text.",
                    "example": "invoice contoso",
                },
                "top": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 25,
                },
                "folder": {
                    "type": "string",
                    "description": "Optional folder name (inbox/sentitems/etc.) or ID.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "query": d["query"],
                "top": d.get("top", 25),
                "folder": d.get("folder") or None,
            },
        ),
        client_op(
            "reply_outlook_email",
            "reply_to_message",
            description="Reply to the sender of an email. Sent immediately.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to reply.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Original message ID.",
                    "example": "AAMk...",
                },
                "comment": {
                    "type": "string",
                    "description": "Reply body (plain text).",
                    "example": "Thanks, sounds good.",
                },
                "to_recipients": {
                    "type": "string",
                    "description": "Optional comma-separated extra recipients.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "comment": d["comment"],
                "to_recipients": _csv_list(d.get("to_recipients", ""), default=None)
                if d.get("to_recipients")
                else None,
            },
        ),
        client_op(
            "reply_all_outlook_email",
            "reply_all_to_message",
            description="Reply-all to an email. Sent immediately.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to reply-all.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Original message ID.",
                    "example": "AAMk...",
                },
                "comment": {
                    "type": "string",
                    "description": "Reply body.",
                    "example": "",
                },
            },
        ),
        _forward_outlook_email_op(),
        client_op(
            "create_outlook_reply_draft",
            "create_reply_draft",
            description=(
                "Create a draft reply (pre-populated with quoted original). "
                "Edit with update_outlook_draft, then send with "
                "send_outlook_draft."
            ),
            parallelizable=False,
            tags=("outlook_mail",),
            unwrap_envelope=True,
            fail_message="Failed to create reply draft.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Original message ID.",
                    "example": "AAMk...",
                },
                "comment": {
                    "type": "string",
                    "description": "Optional initial reply text.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "comment": d.get("comment", ""),
            },
        ),
        client_op(
            "create_outlook_forward_draft",
            "create_forward_draft",
            description=(
                "Create a draft forward (pre-populated with quoted original). "
                "Edit and send later."
            ),
            parallelizable=False,
            tags=("outlook_mail",),
            unwrap_envelope=True,
            fail_message="Failed to create forward draft.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Original message ID.",
                    "example": "AAMk...",
                },
                "to_recipients": {
                    "type": "string",
                    "description": "Comma-separated recipient emails.",
                    "example": "",
                },
                "comment": {
                    "type": "string",
                    "description": "Optional intro.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "to_recipients": _csv_list(d.get("to_recipients", "")),
                "comment": d.get("comment", ""),
            },
        ),
        client_op(
            "create_outlook_draft",
            "create_draft",
            description=(
                "Create a new email draft (not sent). Returns the draft_id "
                "for later editing/sending."
            ),
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to create draft.",
            input_schema={
                "subject": {
                    "type": "string",
                    "description": "Subject.",
                    "example": "Quick question",
                },
                "body": {"type": "string", "description": "Body.", "example": ""},
                "to": {
                    "type": "string",
                    "description": "Comma-separated recipients (optional).",
                    "example": "",
                },
                "cc": {
                    "type": "string",
                    "description": "Comma-separated CC (optional).",
                    "example": "",
                },
                "bcc": {
                    "type": "string",
                    "description": "Comma-separated BCC (optional).",
                    "example": "",
                },
                "html": {
                    "type": "boolean",
                    "description": "Body is HTML.",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "subject": d["subject"],
                "body": d["body"],
                "to": _csv_list(d.get("to", ""), default=None),
                "cc": _csv_list(d.get("cc", ""), default=None),
                "bcc": _csv_list(d.get("bcc", ""), default=None),
                "html": bool(d.get("html", False)),
            },
        ),
        client_op(
            "update_outlook_draft",
            "update_draft",
            description="Edit a draft's subject/body/recipients before sending.",
            parallelizable=False,
            tags=("outlook_mail",),
            unwrap_envelope=True,
            fail_message="Failed to update draft.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Draft ID.",
                    "example": "",
                },
                "subject": {
                    "type": "string",
                    "description": "New subject (optional).",
                    "example": "",
                },
                "body": {
                    "type": "string",
                    "description": "New body (optional).",
                    "example": "",
                },
                "html": {
                    "type": "boolean",
                    "description": "Body is HTML.",
                    "example": False,
                },
                "to": {
                    "type": "string",
                    "description": "New comma-separated recipients (optional, replaces).",
                    "example": "",
                },
                "cc": {
                    "type": "string",
                    "description": "New CC (optional).",
                    "example": "",
                },
                "bcc": {
                    "type": "string",
                    "description": "New BCC (optional).",
                    "example": "",
                },
            },
            arg_map=_update_draft_args,
        ),
        client_op(
            "send_outlook_draft",
            "send_draft",
            description="Send a previously-created draft.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to send draft.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Draft ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_outlook_email",
            "delete_message",
            description=(
                "Permanently delete a message. Use move_outlook_email to "
                "deleteditems for a soft delete."
            ),
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to delete.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "move_outlook_email",
            "move_message",
            description=(
                "Move a message to another folder. destination_folder_id can "
                "be a well-known name (inbox, drafts, sentitems, "
                "deleteditems, archive, junkemail) or a custom folder ID."
            ),
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to move.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "destination_folder_id": {
                    "type": "string",
                    "description": "Folder ID or well-known name.",
                    "example": "archive",
                },
            },
        ),
        client_op(
            "copy_outlook_email",
            "copy_message",
            description="Copy a message to another folder (original stays).",
            parallelizable=False,
            tags=("outlook_mail",),
            unwrap_envelope=True,
            fail_message="Failed to copy.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "destination_folder_id": {
                    "type": "string",
                    "description": "Folder ID or well-known name.",
                    "example": "",
                },
            },
        ),
        client_op(
            "mark_outlook_email_read",
            "mark_as_read",
            description="Mark an Outlook email as read.",
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            success_message="Email marked as read.",
            fail_message="Failed to mark email.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Outlook message ID.",
                    "example": "AAMk...",
                },
            },
        ),
        client_op(
            "mark_outlook_email_unread",
            "mark_as_unread",
            description="Mark an Outlook email as unread.",
            parallelizable=False,
            tags=("outlook_mail",),
            unwrap_envelope=True,
            fail_message="Failed to mark unread.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "flag_outlook_email",
            "flag_message",
            description=(
                "Set the flag status on an email. flag_status: notFlagged | "
                "flagged | complete."
            ),
            parallelizable=False,
            tags=("outlook_mail", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to flag.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "flag_status": {
                    "type": "string",
                    "description": "notFlagged, flagged, or complete.",
                    "example": "flagged",
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "flag_status": d.get("flag_status", "flagged"),
            },
        ),
        client_op(
            "set_outlook_email_categories",
            "set_message_categories",
            description=(
                "Replace the categories on an Outlook message (use "
                "list_outlook_categories to see available ones)."
            ),
            parallelizable=False,
            tags=("outlook_mail",),
            unwrap_envelope=True,
            fail_message="Failed to set categories.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "categories": {
                    "type": "string",
                    "description": "Comma-separated category display names.",
                    "example": "Personal,Important",
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "categories": _csv_list(d.get("categories", "")),
            },
        ),
        # ── Attachments ──────────────────────────────────────────────────
        client_op(
            "list_outlook_attachments",
            "list_attachments",
            description="List attachments on an Outlook message.",
            tags=("outlook_attachments", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to list attachments.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "download_outlook_attachment",
            "download_attachment",
            description=(
                "Download an attachment to a local path. Only works for "
                "fileAttachment type."
            ),
            parallelizable=False,
            tags=("outlook_attachments", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to download.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "attachment_id": {
                    "type": "string",
                    "description": "Attachment ID.",
                    "example": "",
                },
                "save_to": {
                    "type": "string",
                    "description": "Local path to save to.",
                    "example": "C:/Users/me/downloads/file.pdf",
                },
            },
        ),
        client_op(
            "add_outlook_attachment",
            "add_attachment",
            description="Attach a local file to a DRAFT message (under 3 MB).",
            parallelizable=False,
            tags=("outlook_attachments",),
            unwrap_envelope=True,
            fail_message="Failed to add attachment.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Draft message ID.",
                    "example": "",
                },
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the local file.",
                    "example": "",
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME type (autodetect if omitted).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "file_path": d["file_path"],
                "content_type": d.get("content_type") or None,
            },
        ),
        client_op(
            "delete_outlook_attachment",
            "delete_attachment",
            description="Remove an attachment from a draft.",
            destructive=True,  # delete_* — flagged for uniform confirm behavior
            parallelizable=False,
            tags=("outlook_attachments",),
            unwrap_envelope=True,
            fail_message="Failed to delete attachment.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "attachment_id": {
                    "type": "string",
                    "description": "Attachment ID.",
                    "example": "",
                },
            },
        ),
        # ── Folders ──────────────────────────────────────────────────────
        client_op(
            "list_outlook_folders",
            "list_folders",
            description="List mail folders in Outlook.",
            tags=("outlook_folders", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to list folders.",
            input_schema={},
        ),
        client_op(
            "get_outlook_folder",
            "get_folder",
            description="Get metadata for a single mail folder (counts, parent).",
            tags=("outlook_folders",),
            unwrap_envelope=True,
            fail_message="Failed to get folder.",
            input_schema={
                "folder_id": {
                    "type": "string",
                    "description": "Folder ID or well-known name (inbox, drafts, sentitems, etc.).",
                    "example": "inbox",
                },
            },
        ),
        client_op(
            "create_outlook_folder",
            "create_folder",
            description=(
                "Create a new mail folder. Defaults to top-level (under msgfolderroot)."
            ),
            parallelizable=False,
            tags=("outlook_folders", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to create folder.",
            input_schema={
                "display_name": {
                    "type": "string",
                    "description": "Folder name.",
                    "example": "Receipts",
                },
                "parent_folder_id": {
                    "type": "string",
                    "description": "Parent folder ID or well-known name. Default msgfolderroot.",
                    "example": "msgfolderroot",
                },
            },
            arg_map=lambda d: {
                "display_name": d["display_name"],
                "parent_folder_id": d.get("parent_folder_id", "msgfolderroot"),
            },
        ),
        client_op(
            "update_outlook_folder",
            "update_folder",
            description="Rename a mail folder.",
            parallelizable=False,
            tags=("outlook_folders",),
            unwrap_envelope=True,
            fail_message="Failed to rename folder.",
            input_schema={
                "folder_id": {
                    "type": "string",
                    "description": "Folder ID.",
                    "example": "",
                },
                "display_name": {
                    "type": "string",
                    "description": "New name.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_outlook_folder",
            "delete_folder",
            description=(
                "Delete a mail folder (and all messages in it). Cannot delete "
                "well-known folders."
            ),
            destructive=True,  # deletes the folder and every message in it
            parallelizable=False,
            tags=("outlook_folders",),
            unwrap_envelope=True,
            fail_message="Failed to delete folder.",
            input_schema={
                "folder_id": {
                    "type": "string",
                    "description": "Folder ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "list_outlook_child_folders",
            "list_child_folders",
            description="List child folders of a mail folder.",
            tags=("outlook_folders",),
            unwrap_envelope=True,
            fail_message="Failed to list child folders.",
            input_schema={
                "folder_id": {
                    "type": "string",
                    "description": "Parent folder ID or well-known name. Default msgfolderroot.",
                    "example": "msgfolderroot",
                },
            },
            arg_map=lambda d: {
                "folder_id": d.get("folder_id", "msgfolderroot"),
            },
        ),
        client_op(
            "list_outlook_folder_messages",
            "list_folder_messages",
            description="List messages in a specific folder.",
            tags=("outlook_folders", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to list messages.",
            input_schema={
                "folder_id": {
                    "type": "string",
                    "description": "Folder ID or well-known name.",
                    "example": "inbox",
                },
                "count": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 25,
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Filter to unread.",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "folder_id": d["folder_id"],
                "n": d.get("count", 25),
                "unread_only": bool(d.get("unread_only", False)),
            },
        ),
        # ── Mailbox settings + auto-replies + rules + categories ─────────
        _get_outlook_mailbox_settings_op(),
        _get_outlook_automatic_replies_op(),
        client_op(
            "update_outlook_automatic_replies",
            "update_automatic_replies",
            description=(
                "Set out-of-office reply. status: disabled | alwaysEnabled | "
                "scheduled. external_audience: none | contactsOnly | all."
            ),
            parallelizable=False,
            tags=("outlook_settings", "outlook"),
            unwrap_envelope=True,
            fail_message="Failed to set auto-replies.",
            input_schema={
                "status": {
                    "type": "string",
                    "description": "disabled, alwaysEnabled, or scheduled.",
                    "example": "alwaysEnabled",
                },
                "internal_reply": {
                    "type": "string",
                    "description": "Reply text shown to internal senders (optional).",
                    "example": "Out of office until Friday.",
                },
                "external_reply": {
                    "type": "string",
                    "description": "Reply text shown to external senders (optional).",
                    "example": "",
                },
                "external_audience": {
                    "type": "string",
                    "description": "none, contactsOnly, or all.",
                    "example": "all",
                },
                "scheduled_start": {
                    "type": "string",
                    "description": "ISO 8601 start (only for status=scheduled).",
                    "example": "",
                },
                "scheduled_end": {
                    "type": "string",
                    "description": "ISO 8601 end (only for status=scheduled).",
                    "example": "",
                },
            },
            arg_map=_update_automatic_replies_args,
        ),
        client_op(
            "list_outlook_inbox_rules",
            "list_inbox_rules",
            description="List inbox rules (server-side mail rules).",
            tags=("outlook_settings",),
            unwrap_envelope=True,
            fail_message="Failed to list rules.",
            input_schema={},
        ),
        client_op(
            "create_outlook_inbox_rule",
            "create_inbox_rule",
            description=(
                "Create an inbox rule. conditions and actions are Graph rule "
                "objects — e.g. conditions={'fromAddresses': [{'emailAddress':"
                " {'address': 'x@y.com'}}]}, actions={'moveToFolder': "
                "'<folderId>'}."
            ),
            parallelizable=False,
            tags=("outlook_settings",),
            unwrap_envelope=True,
            fail_message="Failed to create rule.",
            input_schema={
                "display_name": {
                    "type": "string",
                    "description": "Rule name.",
                    "example": "From boss to Important",
                },
                "conditions": {
                    "type": "object",
                    "description": "Graph messageRulePredicates object.",
                    "example": {},
                },
                "actions": {
                    "type": "object",
                    "description": "Graph messageRuleActions object.",
                    "example": {},
                },
                "sequence": {
                    "type": "integer",
                    "description": "Run order (lower runs first).",
                    "example": 1,
                },
                "is_enabled": {
                    "type": "boolean",
                    "description": "Enable on create.",
                    "example": True,
                },
            },
            arg_map=lambda d: {
                "display_name": d["display_name"],
                "conditions": d["conditions"],
                "actions": d["actions"],
                "sequence": d.get("sequence", 1),
                "is_enabled": bool(d.get("is_enabled", True)),
            },
        ),
        client_op(
            "delete_outlook_inbox_rule",
            "delete_inbox_rule",
            description="Delete an inbox rule.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("outlook_settings",),
            unwrap_envelope=True,
            fail_message="Failed to delete rule.",
            input_schema={
                "rule_id": {
                    "type": "string",
                    "description": "Rule ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "list_outlook_categories",
            "list_categories",
            description=(
                "List the user's master categories (color-coded tags for "
                "messages, calendar items, etc.)."
            ),
            tags=("outlook_settings",),
            unwrap_envelope=True,
            fail_message="Failed to list categories.",
            input_schema={},
        ),
        client_op(
            "create_outlook_category",
            "create_category",
            description=(
                "Create a master category. color: preset0..preset24 from "
                "Graph categoryColor enum."
            ),
            parallelizable=False,
            tags=("outlook_settings",),
            unwrap_envelope=True,
            fail_message="Failed to create category.",
            input_schema={
                "display_name": {
                    "type": "string",
                    "description": "Category name.",
                    "example": "Personal",
                },
                "color": {
                    "type": "string",
                    "description": "preset0..preset24.",
                    "example": "preset0",
                },
            },
            arg_map=lambda d: {
                "display_name": d["display_name"],
                "color": d.get("color", "preset0"),
            },
        ),
        client_op(
            "delete_outlook_category",
            "delete_category",
            description="Delete a master category.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("outlook_settings",),
            unwrap_envelope=True,
            fail_message="Failed to delete category.",
            input_schema={
                "category_id": {
                    "type": "string",
                    "description": "Category ID.",
                    "example": "",
                },
            },
        ),
    ]
