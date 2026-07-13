from agent_core import action


# ------------------------------------------------------------------
# Mail — read / send / reply / forward / draft / lifecycle
# ------------------------------------------------------------------


@action(
    name="send_outlook_email",
    irreversible=True,
    description="Send an email via Outlook (Microsoft 365).",
    action_sets=["outlook_mail", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "send_email",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Email sent.",
        fail_message="Failed to send email.",
        to=input_data["to"],
        subject=input_data["subject"],
        body=input_data["body"],
        cc=input_data.get("cc"),
    )


@action(
    name="list_outlook_emails",
    description="List recent emails from Outlook inbox.",
    action_sets=["outlook_mail", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_emails",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list emails.",
        n=input_data.get("count", 10),
        unread_only=input_data.get("unread_only", False),
    )


@action(
    name="get_outlook_email",
    description="Get full details of a specific Outlook email by message ID. Body is plain text by default; set include_metadata for the HTML body.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Outlook message ID.",
            "example": "AAMk...",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return the HTML body instead of plain text (default false).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "get_email",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get email.",
        message_id=input_data["message_id"],
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="read_top_outlook_emails",
    description="Read the top N recent Outlook emails with details. With full_body=true, bodies are plain text by default; set include_metadata for HTML bodies.",
    action_sets=["outlook_mail", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "With full_body, return HTML bodies instead of plain text (default false).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_top_outlook_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "read_top_emails",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to read emails.",
        n=input_data.get("count", 5),
        full_body=input_data.get("full_body", False),
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="search_outlook_emails",
    description="Search Outlook messages by free-text query (matches subject, body, attachments). Sorted by relevance.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Search text.",
            "example": "invoice contoso",
        },
        "top": {"type": "integer", "description": "Max results.", "example": 25},
        "folder": {
            "type": "string",
            "description": "Optional folder name (inbox/sentitems/etc.) or ID.",
            "example": "",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_outlook_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "search_messages",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to search.",
        query=input_data["query"],
        top=input_data.get("top", 25),
        folder=input_data.get("folder") or None,
    )


@action(
    name="reply_outlook_email",
    irreversible=True,
    description="Reply to the sender of an email. Sent immediately.",
    action_sets=["outlook_mail", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def reply_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.utils.text import csv_list

    to = (
        csv_list(input_data.get("to_recipients", ""), default=None)
        if input_data.get("to_recipients")
        else None
    )
    return run_client_sync(
        "outlook",
        "reply_to_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to reply.",
        message_id=input_data["message_id"],
        comment=input_data["comment"],
        to_recipients=to,
    )


@action(
    name="reply_all_outlook_email",
    irreversible=True,
    description="Reply-all to an email. Sent immediately.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Original message ID.",
            "example": "AAMk...",
        },
        "comment": {"type": "string", "description": "Reply body.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def reply_all_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "reply_all_to_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to reply-all.",
        message_id=input_data["message_id"],
        comment=input_data["comment"],
    )


@action(
    name="forward_outlook_email",
    irreversible=True,
    description="Forward an email to other recipients.",
    action_sets=["outlook_mail", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def forward_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.utils.text import csv_list

    to = csv_list(input_data["to_recipients"])
    if not to:
        return {"status": "error", "message": "No recipients provided."}
    return run_client_sync(
        "outlook",
        "forward_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to forward.",
        message_id=input_data["message_id"],
        to_recipients=to,
        comment=input_data.get("comment", ""),
    )


@action(
    name="create_outlook_reply_draft",
    description="Create a draft reply (pre-populated with quoted original). Edit with update_outlook_draft, then send with send_outlook_draft.",
    action_sets=["outlook_mail"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_outlook_reply_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "create_reply_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create reply draft.",
        message_id=input_data["message_id"],
        comment=input_data.get("comment", ""),
    )


@action(
    name="create_outlook_forward_draft",
    description="Create a draft forward (pre-populated with quoted original). Edit and send later.",
    action_sets=["outlook_mail"],
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
        "comment": {"type": "string", "description": "Optional intro.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_outlook_forward_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.utils.text import csv_list

    to = csv_list(input_data.get("to_recipients", ""))
    return run_client_sync(
        "outlook",
        "create_forward_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create forward draft.",
        message_id=input_data["message_id"],
        to_recipients=to,
        comment=input_data.get("comment", ""),
    )


@action(
    name="create_outlook_draft",
    description="Create a new email draft (not sent). Returns the draft_id for later editing/sending.",
    action_sets=["outlook_mail", "outlook"],
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
        "html": {"type": "boolean", "description": "Body is HTML.", "example": False},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_outlook_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.utils.text import csv_list

    return run_client_sync(
        "outlook",
        "create_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create draft.",
        subject=input_data["subject"],
        body=input_data["body"],
        to=csv_list(input_data.get("to", ""), default=None),
        cc=csv_list(input_data.get("cc", ""), default=None),
        bcc=csv_list(input_data.get("bcc", ""), default=None),
        html=bool(input_data.get("html", False)),
    )


@action(
    name="update_outlook_draft",
    description="Edit a draft's subject/body/recipients before sending.",
    action_sets=["outlook_mail"],
    input_schema={
        "message_id": {"type": "string", "description": "Draft ID.", "example": ""},
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
        "html": {"type": "boolean", "description": "Body is HTML.", "example": False},
        "to": {
            "type": "string",
            "description": "New comma-separated recipients (optional, replaces).",
            "example": "",
        },
        "cc": {"type": "string", "description": "New CC (optional).", "example": ""},
        "bcc": {"type": "string", "description": "New BCC (optional).", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_outlook_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.utils.text import csv_list

    return run_client_sync(
        "outlook",
        "update_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to update draft.",
        message_id=input_data["message_id"],
        subject=input_data.get("subject") if "subject" in input_data else None,
        body=input_data.get("body") if "body" in input_data else None,
        html=bool(input_data.get("html", False)),
        to=csv_list(input_data["to"], default=None) if "to" in input_data else None,
        cc=csv_list(input_data["cc"], default=None) if "cc" in input_data else None,
        bcc=csv_list(input_data["bcc"], default=None) if "bcc" in input_data else None,
    )


@action(
    name="send_outlook_draft",
    irreversible=True,
    description="Send a previously-created draft.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Draft ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_outlook_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "send_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to send draft.",
        message_id=input_data["message_id"],
    )


@action(
    name="delete_outlook_email",
    description="Permanently delete a message. Use move_outlook_email to deleteditems for a soft delete.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "delete_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete.",
        message_id=input_data["message_id"],
    )


@action(
    name="move_outlook_email",
    description="Move a message to another folder. destination_folder_id can be a well-known name (inbox, drafts, sentitems, deleteditems, archive, junkemail) or a custom folder ID.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "destination_folder_id": {
            "type": "string",
            "description": "Folder ID or well-known name.",
            "example": "archive",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def move_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "move_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to move.",
        message_id=input_data["message_id"],
        destination_folder_id=input_data["destination_folder_id"],
    )


@action(
    name="copy_outlook_email",
    description="Copy a message to another folder (original stays).",
    action_sets=["outlook_mail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "destination_folder_id": {
            "type": "string",
            "description": "Folder ID or well-known name.",
            "example": "",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def copy_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "copy_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to copy.",
        message_id=input_data["message_id"],
        destination_folder_id=input_data["destination_folder_id"],
    )


@action(
    name="mark_outlook_email_read",
    description="Mark an Outlook email as read.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Outlook message ID.",
            "example": "AAMk...",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def mark_outlook_email_read(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "mark_as_read",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Email marked as read.",
        fail_message="Failed to mark email.",
        message_id=input_data["message_id"],
    )


@action(
    name="mark_outlook_email_unread",
    description="Mark an Outlook email as unread.",
    action_sets=["outlook_mail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def mark_outlook_email_unread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "mark_as_unread",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to mark unread.",
        message_id=input_data["message_id"],
    )


@action(
    name="flag_outlook_email",
    description="Set the flag status on an email. flag_status: notFlagged | flagged | complete.",
    action_sets=["outlook_mail", "outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "flag_status": {
            "type": "string",
            "description": "notFlagged, flagged, or complete.",
            "example": "flagged",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def flag_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "flag_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to flag.",
        message_id=input_data["message_id"],
        flag_status=input_data.get("flag_status", "flagged"),
    )


@action(
    name="set_outlook_email_categories",
    description="Replace the categories on an Outlook message (use list_outlook_categories to see available ones).",
    action_sets=["outlook_mail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "categories": {
            "type": "string",
            "description": "Comma-separated category display names.",
            "example": "Personal,Important",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_outlook_email_categories(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync
    from app.utils.text import csv_list

    categories = csv_list(input_data.get("categories", ""))
    return run_client_sync(
        "outlook",
        "set_message_categories",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to set categories.",
        message_id=input_data["message_id"],
        categories=categories,
    )


# ------------------------------------------------------------------
# Attachments
# ------------------------------------------------------------------


@action(
    name="list_outlook_attachments",
    description="List attachments on an Outlook message.",
    action_sets=["outlook_attachments", "outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_attachments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_attachments",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list attachments.",
        message_id=input_data["message_id"],
    )


@action(
    name="download_outlook_attachment",
    description="Download an attachment to a local path. Only works for fileAttachment type.",
    action_sets=["outlook_attachments", "outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def download_outlook_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "download_attachment",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to download.",
        message_id=input_data["message_id"],
        attachment_id=input_data["attachment_id"],
        save_to=input_data["save_to"],
    )


@action(
    name="add_outlook_attachment",
    description="Attach a local file to a DRAFT message (under 3 MB).",
    action_sets=["outlook_attachments"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_outlook_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "add_attachment",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to add attachment.",
        message_id=input_data["message_id"],
        file_path=input_data["file_path"],
        content_type=input_data.get("content_type") or None,
    )


@action(
    name="delete_outlook_attachment",
    description="Remove an attachment from a draft.",
    action_sets=["outlook_attachments"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
        "attachment_id": {
            "type": "string",
            "description": "Attachment ID.",
            "example": "",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_outlook_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "delete_attachment",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete attachment.",
        message_id=input_data["message_id"],
        attachment_id=input_data["attachment_id"],
    )


# ------------------------------------------------------------------
# Folders
# ------------------------------------------------------------------


@action(
    name="list_outlook_folders",
    description="List mail folders in Outlook.",
    action_sets=["outlook_folders", "outlook"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_folders(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_folders",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list folders.",
    )


@action(
    name="get_outlook_folder",
    description="Get metadata for a single mail folder (counts, parent).",
    action_sets=["outlook_folders"],
    input_schema={
        "folder_id": {
            "type": "string",
            "description": "Folder ID or well-known name (inbox, drafts, sentitems, etc.).",
            "example": "inbox",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_outlook_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "get_folder",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get folder.",
        folder_id=input_data["folder_id"],
    )


@action(
    name="create_outlook_folder",
    description="Create a new mail folder. Defaults to top-level (under msgfolderroot).",
    action_sets=["outlook_folders", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_outlook_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "create_folder",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create folder.",
        display_name=input_data["display_name"],
        parent_folder_id=input_data.get("parent_folder_id", "msgfolderroot"),
    )


@action(
    name="update_outlook_folder",
    description="Rename a mail folder.",
    action_sets=["outlook_folders"],
    input_schema={
        "folder_id": {"type": "string", "description": "Folder ID.", "example": ""},
        "display_name": {"type": "string", "description": "New name.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_outlook_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "update_folder",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to rename folder.",
        folder_id=input_data["folder_id"],
        display_name=input_data["display_name"],
    )


@action(
    name="delete_outlook_folder",
    description="Delete a mail folder (and all messages in it). Cannot delete well-known folders.",
    action_sets=["outlook_folders"],
    input_schema={
        "folder_id": {"type": "string", "description": "Folder ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_outlook_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "delete_folder",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete folder.",
        folder_id=input_data["folder_id"],
    )


@action(
    name="list_outlook_child_folders",
    description="List child folders of a mail folder.",
    action_sets=["outlook_folders"],
    input_schema={
        "folder_id": {
            "type": "string",
            "description": "Parent folder ID or well-known name. Default msgfolderroot.",
            "example": "msgfolderroot",
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_child_folders(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_child_folders",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list child folders.",
        folder_id=input_data.get("folder_id", "msgfolderroot"),
    )


@action(
    name="list_outlook_folder_messages",
    description="List messages in a specific folder.",
    action_sets=["outlook_folders", "outlook"],
    input_schema={
        "folder_id": {
            "type": "string",
            "description": "Folder ID or well-known name.",
            "example": "inbox",
        },
        "count": {"type": "integer", "description": "Max results.", "example": 25},
        "unread_only": {
            "type": "boolean",
            "description": "Filter to unread.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_folder_messages(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_folder_messages",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list messages.",
        folder_id=input_data["folder_id"],
        n=input_data.get("count", 25),
        unread_only=bool(input_data.get("unread_only", False)),
    )


# ------------------------------------------------------------------
# Mailbox settings + auto-replies + rules + categories
# ------------------------------------------------------------------


@action(
    name="get_outlook_mailbox_settings",
    description="Get the user's mailbox settings. Default returns {timeZone, language, workingHours, automaticRepliesSetting.status}; set include_metadata for the raw settings.",
    action_sets=["outlook_settings"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return the raw mailboxSettings resource (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_outlook_mailbox_settings(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "outlook",
        "get_mailbox_settings",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get settings.",
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        settings = res.get("result")
        if isinstance(settings, dict):
            lean = {"timeZone": settings.get("timeZone")}
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


@action(
    name="get_outlook_automatic_replies",
    description="Get the current out-of-office / automatic reply settings. Default returns {status, schedule, reply messages as plain text}; set include_metadata for the raw setting.",
    action_sets=["outlook_settings", "outlook"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return the raw automaticRepliesSetting (default false = lean, HTML stripped).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_outlook_automatic_replies(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "outlook",
        "get_automatic_replies",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get auto-replies.",
    )
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


@action(
    name="update_outlook_automatic_replies",
    description="Set out-of-office reply. status: disabled | alwaysEnabled | scheduled. external_audience: none | contactsOnly | all.",
    action_sets=["outlook_settings", "outlook"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_outlook_automatic_replies(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "update_automatic_replies",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to set auto-replies.",
        status=input_data["status"],
        internal_reply=input_data.get("internal_reply")
        if "internal_reply" in input_data
        else None,
        external_reply=input_data.get("external_reply")
        if "external_reply" in input_data
        else None,
        external_audience=input_data.get("external_audience", "all"),
        scheduled_start=input_data.get("scheduled_start") or None,
        scheduled_end=input_data.get("scheduled_end") or None,
    )


@action(
    name="list_outlook_inbox_rules",
    description="List inbox rules (server-side mail rules).",
    action_sets=["outlook_settings"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_inbox_rules(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_inbox_rules",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list rules.",
    )


@action(
    name="create_outlook_inbox_rule",
    description="Create an inbox rule. conditions and actions are Graph rule objects — e.g. conditions={'fromAddresses': [{'emailAddress': {'address': 'x@y.com'}}]}, actions={'moveToFolder': '<folderId>'}.",
    action_sets=["outlook_settings"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_outlook_inbox_rule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "create_inbox_rule",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create rule.",
        display_name=input_data["display_name"],
        conditions=input_data["conditions"],
        actions=input_data["actions"],
        sequence=input_data.get("sequence", 1),
        is_enabled=bool(input_data.get("is_enabled", True)),
    )


@action(
    name="delete_outlook_inbox_rule",
    description="Delete an inbox rule.",
    action_sets=["outlook_settings"],
    input_schema={
        "rule_id": {"type": "string", "description": "Rule ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_outlook_inbox_rule(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "delete_inbox_rule",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete rule.",
        rule_id=input_data["rule_id"],
    )


@action(
    name="list_outlook_categories",
    description="List the user's master categories (color-coded tags for messages, calendar items, etc.).",
    action_sets=["outlook_settings"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_categories(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_categories",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list categories.",
    )


@action(
    name="create_outlook_category",
    description="Create a master category. color: preset0..preset24 from Graph categoryColor enum.",
    action_sets=["outlook_settings"],
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
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_outlook_category(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "create_category",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create category.",
        display_name=input_data["display_name"],
        color=input_data.get("color", "preset0"),
    )


@action(
    name="delete_outlook_category",
    description="Delete a master category.",
    action_sets=["outlook_settings"],
    input_schema={
        "category_id": {"type": "string", "description": "Category ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Outlook account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_outlook_category(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "delete_category",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete category.",
        category_id=input_data["category_id"],
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Subscriptions / webhooks (subscribe to mailbox changes)
#     Server-side push notification setup; not interactive.
# - Large attachment upload sessions (>3 MB via uploadSession)
#     The simple add_attachment covers the realistic agent use case (<3 MB).
# - Schema extensions and open extensions
#     Custom property storage on resources; niche developer tooling.
# - Find meeting times / get schedule
#     Calendar surface — would belong to a separate outlook_calendar action set,
#     not this mail-focused expansion.
# - Delta queries (incremental sync via $deltaToken)
#     Synchronization plumbing, not per-action work.
# - Permissions delegation (sharedMailbox, sendOnBehalf)
#     Admin / multi-user concerns.
