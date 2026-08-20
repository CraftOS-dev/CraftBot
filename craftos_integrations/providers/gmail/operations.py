"""Gmail operations — ported from the legacy gmail_actions.py schemas.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced).

Complete port of app/data/action/integrations/google_workspace/
gmail_actions.py, minus the two backwards-compat aliases
(send_google_workspace_email / read_recent_google_workspace_emails):
they existed only to keep old skill/memory action names working in the
single-account system, and send_google_workspace_email's ``from_email``
input is account selection — handled centrally by the system.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List

from ...contracts import Operation
from .._shared import client_op


def _get_gmail_thread_op() -> Operation:
    """get_gmail_thread with the legacy lean-shaping of the raw thread."""
    base = client_op(
        "get_gmail_thread",
        "get_thread",
        description=(
            "Get a thread (conversation) and its messages. Default returns "
            "per-message {id, from, to, subject, date, snippet}; set "
            "include_metadata for the raw thread."
        ),
        tags=("gmail_threads", "gmail"),
        unwrap_envelope=True,
        fail_message="Failed to get thread.",
        input_schema={
            "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
            "fmt": {
                "type": "string",
                "description": "metadata | full | minimal.",
                "example": "metadata",
            },
            "include_metadata": {
                "type": "boolean",
                "description": "Return the raw thread resource (default false = lean).",
                "example": False,
            },
        },
        arg_map=lambda d: {
            "thread_id": d["thread_id"],
            "fmt": d.get("fmt", "metadata"),
        },
    )
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        res = await inner(client, input_data)
        if not input_data.get("include_metadata") and res.get("status") == "success":
            thread = res.get("result")
            if isinstance(thread, dict):
                lean_messages = []
                for msg in thread.get("messages", []) or []:
                    if not isinstance(msg, dict):
                        continue
                    headers = {
                        h.get("name", ""): h.get("value", "")
                        for h in msg.get("payload", {}).get("headers", [])
                    }
                    lean_messages.append(
                        {
                            "id": msg.get("id"),
                            "from": headers.get("From", ""),
                            "to": headers.get("To", ""),
                            "subject": headers.get("Subject", ""),
                            "date": headers.get("Date", ""),
                            "snippet": msg.get("snippet", ""),
                        }
                    )
                res = {
                    **res,
                    "result": {"id": thread.get("id"), "messages": lean_messages},
                }
        return res

    return replace(base, fn=fn)


def _get_gmail_draft_op() -> Operation:
    """get_gmail_draft with the legacy lean-shaping of the raw draft."""
    base = client_op(
        "get_gmail_draft",
        "get_draft",
        description=(
            "Get a Gmail draft by ID. Default returns {id, message_id, to, "
            "subject, snippet}; set include_metadata for the raw draft."
        ),
        tags=("gmail_drafts",),
        unwrap_envelope=True,
        fail_message="Failed to get draft.",
        input_schema={
            "draft_id": {"type": "string", "description": "Draft ID.", "example": ""},
            "fmt": {
                "type": "string",
                "description": "metadata | full | minimal.",
                "example": "metadata",
            },
            "include_metadata": {
                "type": "boolean",
                "description": "Return the raw draft resource (default false = lean).",
                "example": False,
            },
        },
        arg_map=lambda d: {
            "draft_id": d["draft_id"],
            "fmt": d.get("fmt", "metadata"),
        },
    )
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        res = await inner(client, input_data)
        if not input_data.get("include_metadata") and res.get("status") == "success":
            draft = res.get("result")
            if isinstance(draft, dict):
                msg = draft.get("message") or {}
                headers = {
                    h.get("name", ""): h.get("value", "")
                    for h in msg.get("payload", {}).get("headers", [])
                }
                res = {
                    **res,
                    "result": {
                        "id": draft.get("id"),
                        "message_id": msg.get("id"),
                        "to": headers.get("To", ""),
                        "subject": headers.get("Subject", ""),
                        "snippet": msg.get("snippet", ""),
                    },
                }
        return res

    return replace(base, fn=fn)


def build_operations() -> List[Operation]:
    return [
        # ── Mail — send / list / get / search / reply / forward / lifecycle ──
        client_op(
            "send_gmail",
            "send_email",
            description="Send an email via Gmail.",
            destructive=True,  # outward-facing send — hosts confirm/clarify
            parallelizable=False,
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            success_message="Email sent.",
            fail_message="Failed to send email.",
            input_schema={
                "to": {
                    "type": "string",
                    "description": (
                        "Recipient email address. OMIT to send to the user's "
                        "own address (the connected account) — never store or "
                        "guess the user's email."
                    ),
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
                "attachments": {
                    "type": "array",
                    "description": "Optional list of file paths to attach.",
                    "example": [],
                },
            },
            arg_map=lambda d: {
                # Omitted/empty `to` → the client sends to the account owner.
                "to": d.get("to"),
                "subject": d["subject"],
                "body": d["body"],
                "attachments": d.get("attachments"),
            },
        ),
        client_op(
            "list_gmail",
            "list_emails",
            description="List recent emails from Gmail inbox.",
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to list emails.",
            input_schema={
                "count": {
                    "type": "integer",
                    "description": "Number of recent emails to list.",
                    "example": 5,
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Only unread emails.",
                    "example": True,
                },
            },
            arg_map=lambda d: {
                "n": d.get("count", 5),
                "unread_only": d.get("unread_only", True),
            },
        ),
        client_op(
            "get_gmail",
            "get_email",
            description="Get a single Gmail message by id.",
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to get email.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Gmail message id (from list/search).",
                    "example": "18c2f...",
                },
                "full_body": {
                    "type": "boolean",
                    "description": "Return the full body instead of a snippet.",
                    "example": False,
                },
            },
        ),
        client_op(
            "read_top_emails",
            "read_top_emails",
            description="Read the top N recent emails with details.",
            tags=("gmail_mail", "gmail"),
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
            },
            arg_map=lambda d: {
                "n": d.get("count", 5),
                "full_body": d.get("full_body", False),
            },
        ),
        client_op(
            "search_gmail",
            "search_messages",
            description="Search Gmail with a query (Gmail search syntax).",
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to search emails.",
            input_schema={
                "query": {
                    "type": "string",
                    "description": "Gmail search query.",
                    "example": "from:alice subject:invoice newer_than:7d",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results.",
                    "example": 10,
                },
            },
        ),
        client_op(
            "reply_gmail",
            "reply_to_message",
            description="Reply to a Gmail message (keeps the thread).",
            destructive=True,
            parallelizable=False,
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            success_message="Reply sent.",
            fail_message="Failed to send reply.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Id of the message being replied to.",
                    "example": "18c2f...",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body text.",
                    "example": "Thanks — confirmed for Tuesday.",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "Reply to all recipients.",
                    "example": False,
                },
            },
        ),
        client_op(
            "forward_gmail",
            "forward_message",
            description="Forward a Gmail message to another address. The original message's body and attachments are included automatically.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to forward.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Original message ID.",
                    "example": "",
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email.",
                    "example": "bob@example.com",
                },
                "body": {
                    "type": "string",
                    "description": "Optional intro text, prepended above the forwarded content. The original body is always included — do not copy it here.",
                    "example": "",
                },
                "attachments": {
                    "type": "array",
                    "description": "Optional EXTRA local file paths to attach. The original message's attachments are forwarded automatically.",
                    "example": [],
                },
            },
            arg_map=lambda d: {
                "message_id": d["message_id"],
                "to": d["to"],
                "body": d.get("body", ""),
                "attachments": d.get("attachments"),
            },
        ),
        client_op(
            "modify_gmail_labels",
            "modify_message_labels",
            description=(
                "Add/remove labels on a Gmail message. Common label IDs: "
                "INBOX, UNREAD, STARRED, IMPORTANT, TRASH, SPAM, "
                "CATEGORY_PERSONAL."
            ),
            parallelizable=False,
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to modify labels.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "add_label_ids": {
                    "type": "array",
                    "description": "Label IDs to add.",
                    "example": ["STARRED"],
                },
                "remove_label_ids": {
                    "type": "array",
                    "description": "Label IDs to remove.",
                    "example": ["UNREAD"],
                },
            },
        ),
        client_op(
            "trash_gmail",
            "trash_message",
            description="Move a Gmail message to Trash (reversible).",
            parallelizable=False,
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            success_message="Message moved to Trash.",
            fail_message="Failed to trash message.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Gmail message id.",
                    "example": "18c2f...",
                },
            },
        ),
        client_op(
            "untrash_gmail",
            "untrash_message",
            description="Recover a Gmail message from Trash.",
            parallelizable=False,
            tags=("gmail_mail",),
            unwrap_envelope=True,
            fail_message="Failed to untrash.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_gmail",
            "delete_message",
            description="Permanently delete a Gmail message (NOT reversible — prefer trash_gmail).",
            destructive=True,
            parallelizable=False,
            tags=("gmail_mail",),
            unwrap_envelope=True,
            success_message="Message permanently deleted.",
            fail_message="Failed to delete message.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Gmail message id.",
                    "example": "18c2f...",
                },
            },
        ),
        client_op(
            "batch_modify_gmail",
            "batch_modify_messages",
            description="Bulk add/remove labels across multiple messages in one call.",
            parallelizable=False,
            tags=("gmail_mail",),
            unwrap_envelope=True,
            fail_message="Failed to batch modify.",
            input_schema={
                "message_ids": {
                    "type": "array",
                    "description": "List of message IDs.",
                    "example": [],
                },
                "add_label_ids": {
                    "type": "array",
                    "description": "Label IDs to add.",
                    "example": [],
                },
                "remove_label_ids": {
                    "type": "array",
                    "description": "Label IDs to remove.",
                    "example": [],
                },
            },
        ),
        client_op(
            "batch_delete_gmail",
            "batch_delete_messages",
            description="Permanently delete multiple messages. Irreversible.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("gmail_mail",),
            unwrap_envelope=True,
            fail_message="Failed to batch delete.",
            input_schema={
                "message_ids": {
                    "type": "array",
                    "description": "List of message IDs.",
                    "example": [],
                },
            },
        ),
        # ── Threads ──────────────────────────────────────────────────────
        client_op(
            "list_gmail_threads",
            "list_threads",
            description="List Gmail conversation threads.",
            tags=("gmail_threads", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to list threads.",
            input_schema={
                "query": {
                    "type": "string",
                    "description": "Optional Gmail q query.",
                    "example": "",
                },
                "label_ids": {
                    "type": "array",
                    "description": "Optional label filter.",
                    "example": ["INBOX"],
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max threads.",
                    "example": 25,
                },
            },
            arg_map=lambda d: {
                "query": d.get("query") or None,
                "label_ids": d.get("label_ids"),
                "max_results": d.get("max_results", 25),
            },
        ),
        _get_gmail_thread_op(),
        client_op(
            "modify_gmail_thread_labels",
            "modify_thread_labels",
            description="Add/remove labels on every message in a thread.",
            parallelizable=False,
            tags=("gmail_threads",),
            unwrap_envelope=True,
            fail_message="Failed to modify thread labels.",
            input_schema={
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID.",
                    "example": "",
                },
                "add_label_ids": {
                    "type": "array",
                    "description": "Labels to add.",
                    "example": [],
                },
                "remove_label_ids": {
                    "type": "array",
                    "description": "Labels to remove.",
                    "example": [],
                },
            },
        ),
        client_op(
            "trash_gmail_thread",
            "trash_thread",
            description="Move an entire Gmail thread to Trash.",
            parallelizable=False,
            tags=("gmail_threads",),
            unwrap_envelope=True,
            fail_message="Failed to trash thread.",
            input_schema={
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "untrash_gmail_thread",
            "untrash_thread",
            description="Recover a Gmail thread from Trash.",
            parallelizable=False,
            tags=("gmail_threads",),
            unwrap_envelope=True,
            fail_message="Failed to untrash thread.",
            input_schema={
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_gmail_thread",
            "delete_thread",
            description="Permanently delete a Gmail thread (all messages). Irreversible.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("gmail_threads",),
            unwrap_envelope=True,
            fail_message="Failed to delete thread.",
            input_schema={
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID.",
                    "example": "",
                },
            },
        ),
        # ── Drafts ───────────────────────────────────────────────────────
        client_op(
            "list_gmail_drafts",
            "list_drafts",
            description="List Gmail drafts.",
            tags=("gmail_drafts", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to list drafts.",
            input_schema={
                "max_results": {
                    "type": "integer",
                    "description": "Max drafts.",
                    "example": 25,
                },
                "query": {
                    "type": "string",
                    "description": "Optional q query.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "max_results": d.get("max_results", 25),
                "query": d.get("query") or None,
            },
        ),
        _get_gmail_draft_op(),
        client_op(
            "create_gmail_draft",
            "create_draft",
            description="Create a Gmail draft (not sent).",
            tags=("gmail_drafts", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to create draft.",
            input_schema={
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                    "example": "user@example.com",
                },
                "subject": {
                    "type": "string",
                    "description": "Draft subject.",
                    "example": "Q3 report",
                },
                "body": {
                    "type": "string",
                    "description": "Draft body text.",
                    "example": "Draft text...",
                },
            },
        ),
        client_op(
            "update_gmail_draft",
            "update_draft",
            description="Replace a Gmail draft's content. All fields are required (PUT semantics).",
            parallelizable=False,
            tags=("gmail_drafts",),
            unwrap_envelope=True,
            fail_message="Failed to update draft.",
            input_schema={
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID.",
                    "example": "",
                },
                "to": {"type": "string", "description": "Recipient.", "example": ""},
                "subject": {"type": "string", "description": "Subject.", "example": ""},
                "body": {"type": "string", "description": "Body text.", "example": ""},
                "cc": {"type": "string", "description": "Optional CC.", "example": ""},
                "bcc": {"type": "string", "description": "Optional BCC.", "example": ""},
                "attachments": {
                    "type": "array",
                    "description": "Local file paths.",
                    "example": [],
                },
            },
            arg_map=lambda d: {
                "draft_id": d["draft_id"],
                "to": d["to"],
                "subject": d["subject"],
                "body": d["body"],
                "cc": d.get("cc") or None,
                "bcc": d.get("bcc") or None,
                "attachments": d.get("attachments"),
            },
        ),
        client_op(
            "send_gmail_draft",
            "send_draft",
            description="Send a previously-created Gmail draft.",
            destructive=True,  # outward-facing send
            parallelizable=False,
            tags=("gmail_drafts", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to send draft.",
            input_schema={
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_gmail_draft",
            "delete_draft",
            description="Permanently delete a Gmail draft.",
            destructive=True,  # permanent delete (drafts have no trash)
            parallelizable=False,
            tags=("gmail_drafts",),
            unwrap_envelope=True,
            fail_message="Failed to delete draft.",
            input_schema={
                "draft_id": {
                    "type": "string",
                    "description": "Draft ID.",
                    "example": "",
                },
            },
        ),
        # ── Labels ───────────────────────────────────────────────────────
        client_op(
            "list_gmail_labels",
            "list_labels",
            description="List all Gmail labels (system + user).",
            tags=("gmail_labels", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to list labels.",
            input_schema={},
        ),
        client_op(
            "get_gmail_label",
            "get_label",
            description="Get a single Gmail label by ID.",
            tags=("gmail_labels",),
            unwrap_envelope=True,
            fail_message="Failed to get label.",
            input_schema={
                "label_id": {
                    "type": "string",
                    "description": "Label ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "create_gmail_label",
            "create_label",
            description=(
                "Create a new user label. label_list_visibility: "
                "labelShow|labelShowIfUnread|labelHide. "
                "message_list_visibility: show|hide."
            ),
            parallelizable=False,
            tags=("gmail_labels", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to create label.",
            input_schema={
                "name": {
                    "type": "string",
                    "description": "Label name (use '/' for nesting, e.g. 'Work/Clients').",
                    "example": "Receipts",
                },
                "label_list_visibility": {
                    "type": "string",
                    "description": "labelShow / labelShowIfUnread / labelHide.",
                    "example": "labelShow",
                },
                "message_list_visibility": {
                    "type": "string",
                    "description": "show / hide.",
                    "example": "show",
                },
                "background_color": {
                    "type": "string",
                    "description": "Hex color (optional, requires text_color).",
                    "example": "",
                },
                "text_color": {
                    "type": "string",
                    "description": "Hex color (optional, requires background_color).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "name": d["name"],
                "label_list_visibility": d.get("label_list_visibility", "labelShow"),
                "message_list_visibility": d.get("message_list_visibility", "show"),
                "background_color": d.get("background_color") or None,
                "text_color": d.get("text_color") or None,
            },
        ),
        client_op(
            "update_gmail_label",
            "update_label",
            description="Update (rename / recolor) a Gmail label.",
            parallelizable=False,
            tags=("gmail_labels",),
            unwrap_envelope=True,
            fail_message="Failed to update label.",
            input_schema={
                "label_id": {
                    "type": "string",
                    "description": "Label ID.",
                    "example": "",
                },
                "name": {
                    "type": "string",
                    "description": "New name (optional).",
                    "example": "",
                },
                "label_list_visibility": {
                    "type": "string",
                    "description": "labelShow / labelShowIfUnread / labelHide.",
                    "example": "",
                },
                "message_list_visibility": {
                    "type": "string",
                    "description": "show / hide.",
                    "example": "",
                },
                "background_color": {
                    "type": "string",
                    "description": "Hex color (optional).",
                    "example": "",
                },
                "text_color": {
                    "type": "string",
                    "description": "Hex color (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "label_id": d["label_id"],
                "name": d.get("name") or None,
                "label_list_visibility": d.get("label_list_visibility") or None,
                "message_list_visibility": d.get("message_list_visibility") or None,
                "background_color": d.get("background_color") or None,
                "text_color": d.get("text_color") or None,
            },
        ),
        client_op(
            "delete_gmail_label",
            "delete_label",
            description="Delete a Gmail label (also removes it from all messages/threads).",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("gmail_labels",),
            unwrap_envelope=True,
            fail_message="Failed to delete label.",
            input_schema={
                "label_id": {
                    "type": "string",
                    "description": "Label ID.",
                    "example": "",
                },
            },
        ),
        # ── Attachments + profile ────────────────────────────────────────
        client_op(
            "download_gmail_attachment",
            "download_attachment",
            description=(
                "Download a Gmail attachment to a local path. "
                "First call get_gmail with full_body=true to get the attachments list — "
                "each entry has attachment_id and filename. "
                "Pass save_to as a directory path and filename separately, or as a full file path."
            ),
            parallelizable=False,
            tags=("gmail_attachments", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to download attachment.",
            input_schema={
                "message_id": {
                    "type": "string",
                    "description": "Message ID.",
                    "example": "",
                },
                "attachment_id": {
                    "type": "string",
                    "description": "Attachment ID from get_gmail(full_body=true).attachments[].attachment_id.",
                    "example": "",
                },
                "save_to": {
                    "type": "string",
                    "description": "Local path to save to. May be a directory; use filename to set the file name.",
                    "example": "C:/Users/me/downloads/",
                },
                "filename": {
                    "type": "string",
                    "description": "Filename to use when save_to is a directory. Use the filename from get_gmail attachments list.",
                    "example": "invoice.pdf",
                },
            },
        ),
        client_op(
            "get_gmail_profile",
            "get_profile",
            description=(
                "Get the authenticated user's Gmail profile: email address, "
                "message/thread totals, historyId."
            ),
            tags=("gmail_mail", "gmail"),
            unwrap_envelope=True,
            fail_message="Failed to get profile.",
            input_schema={},
        ),
    ]
