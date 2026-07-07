from agent_core import action


# ------------------------------------------------------------------
# Mail — send / list / get / search / reply / forward / lifecycle
# ------------------------------------------------------------------


@action(
    name="send_gmail",
    irreversible=True,
    description="Send an email via Gmail.",
    action_sets=["gmail_mail", "gmail"],
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
        "attachments": {
            "type": "array",
            "description": "Optional list of file paths to attach.",
            "example": [],
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "send_email",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Email sent.",
        fail_message="Failed to send email.",
        to=input_data["to"],
        subject=input_data["subject"],
        body=input_data["body"],
        attachments=input_data.get("attachments"),
    )


@action(
    name="list_gmail",
    description="List recent emails from Gmail inbox.",
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "count": {
            "type": "integer",
            "description": "Number of recent emails to list.",
            "example": 5,
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "list_emails",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list emails.",
        n=input_data.get("count", 5),
    )


@action(
    name="get_gmail",
    description=(
        "Get details of a specific Gmail message by ID. "
        "When full_body=true the response includes body text and an attachments list "
        "(each entry: attachment_id, filename, mimeType, size). "
        "Use attachment_id and filename with download_gmail_attachment."
    ),
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Gmail message ID.",
            "example": "18abc123def",
        },
        "full_body": {
            "type": "boolean",
            "description": "Whether to include full email body and attachment metadata.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "get_email",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get email.",
        message_id=input_data["message_id"],
        full_body=input_data.get("full_body", False),
    )


@action(
    name="read_top_emails",
    description="Read the top N recent emails with details.",
    action_sets=["gmail_mail", "gmail"],
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
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_top_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "read_top_emails",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to read emails.",
        n=input_data.get("count", 5),
        full_body=input_data.get("full_body", False),
    )


@action(
    name="search_gmail",
    description="Search Gmail using Gmail's q syntax (e.g. 'from:alice subject:invoice newer_than:7d has:attachment').",
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Gmail q query.",
            "example": "from:alice@example.com is:unread",
        },
        "max_results": {
            "type": "integer",
            "description": "Max results.",
            "example": 25,
        },
        "include_spam_trash": {
            "type": "boolean",
            "description": "Include Spam/Trash.",
            "example": False,
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "search_messages",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to search.",
        query=input_data["query"],
        max_results=input_data.get("max_results", 25),
        include_spam_trash=bool(input_data.get("include_spam_trash", False)),
    )


@action(
    name="reply_gmail",
    irreversible=True,
    description="Reply to a Gmail message. Preserves thread + In-Reply-To/References headers. Set reply_all=true to also CC the original To/Cc.",
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Original message ID.",
            "example": "",
        },
        "body": {"type": "string", "description": "Reply text.", "example": ""},
        "reply_all": {
            "type": "boolean",
            "description": "Reply-all (CC original recipients).",
            "example": False,
        },
        "attachments": {
            "type": "array",
            "description": "Optional attachment file paths.",
            "example": [],
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def reply_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "reply_to_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to reply.",
        message_id=input_data["message_id"],
        body=input_data["body"],
        reply_all=bool(input_data.get("reply_all", False)),
        attachments=input_data.get("attachments"),
    )


@action(
    name="forward_gmail",
    irreversible=True,
    description="Forward a Gmail message to another address.",
    action_sets=["gmail_mail", "gmail"],
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
            "description": "Optional intro text.",
            "example": "",
        },
        "attachments": {
            "type": "array",
            "description": "Optional attachment file paths.",
            "example": [],
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def forward_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "forward_message",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to forward.",
        message_id=input_data["message_id"],
        to=input_data["to"],
        body=input_data.get("body", ""),
        attachments=input_data.get("attachments"),
    )


@action(
    name="modify_gmail_labels",
    description="Add/remove labels on a Gmail message. Common label IDs: INBOX, UNREAD, STARRED, IMPORTANT, TRASH, SPAM, CATEGORY_PERSONAL.",
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
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
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def modify_gmail_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "modify_message_labels",
        unwrap_envelope=True,
        fail_message="Failed to modify labels.",
        message_id=input_data["message_id"],
        add_label_ids=input_data.get("add_label_ids"),
        remove_label_ids=input_data.get("remove_label_ids"),
    )


@action(
    name="trash_gmail",
    description="Move a Gmail message to Trash (soft delete; recoverable for 30 days).",
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def trash_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "trash_message",
        unwrap_envelope=True,
        fail_message="Failed to trash.",
        message_id=input_data["message_id"],
    )


@action(
    name="untrash_gmail",
    description="Recover a Gmail message from Trash.",
    action_sets=["gmail_mail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def untrash_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "untrash_message",
        unwrap_envelope=True,
        fail_message="Failed to untrash.",
        message_id=input_data["message_id"],
    )


@action(
    name="delete_gmail",
    description="Permanently delete a Gmail message. Irreversible. Prefer trash_gmail for soft delete.",
    action_sets=["gmail_mail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "delete_message",
        unwrap_envelope=True,
        fail_message="Failed to delete.",
        message_id=input_data["message_id"],
    )


@action(
    name="batch_modify_gmail",
    description="Bulk add/remove labels across multiple messages in one call.",
    action_sets=["gmail_mail"],
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
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def batch_modify_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "batch_modify_messages",
        unwrap_envelope=True,
        fail_message="Failed to batch modify.",
        message_ids=input_data["message_ids"],
        add_label_ids=input_data.get("add_label_ids"),
        remove_label_ids=input_data.get("remove_label_ids"),
    )


@action(
    name="batch_delete_gmail",
    description="Permanently delete multiple messages. Irreversible.",
    action_sets=["gmail_mail"],
    input_schema={
        "message_ids": {
            "type": "array",
            "description": "List of message IDs.",
            "example": [],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def batch_delete_gmail(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "batch_delete_messages",
        unwrap_envelope=True,
        fail_message="Failed to batch delete.",
        message_ids=input_data["message_ids"],
    )


# ------------------------------------------------------------------
# Threads
# ------------------------------------------------------------------


@action(
    name="list_gmail_threads",
    description="List Gmail conversation threads.",
    action_sets=["gmail_threads", "gmail"],
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
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_gmail_threads(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "list_threads",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list threads.",
        query=input_data.get("query") or None,
        label_ids=input_data.get("label_ids"),
        max_results=input_data.get("max_results", 25),
    )


@action(
    name="get_gmail_thread",
    description="Get a thread (conversation) and its messages.",
    action_sets=["gmail_threads", "gmail"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
        "fmt": {
            "type": "string",
            "description": "metadata | full | minimal.",
            "example": "metadata",
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_gmail_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "get_thread",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get thread.",
        thread_id=input_data["thread_id"],
        fmt=input_data.get("fmt", "metadata"),
    )


@action(
    name="modify_gmail_thread_labels",
    description="Add/remove labels on every message in a thread.",
    action_sets=["gmail_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
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
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def modify_gmail_thread_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "modify_thread_labels",
        unwrap_envelope=True,
        fail_message="Failed to modify thread labels.",
        thread_id=input_data["thread_id"],
        add_label_ids=input_data.get("add_label_ids"),
        remove_label_ids=input_data.get("remove_label_ids"),
    )


@action(
    name="trash_gmail_thread",
    description="Move an entire Gmail thread to Trash.",
    action_sets=["gmail_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def trash_gmail_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "trash_thread",
        unwrap_envelope=True,
        fail_message="Failed to trash thread.",
        thread_id=input_data["thread_id"],
    )


@action(
    name="untrash_gmail_thread",
    description="Recover a Gmail thread from Trash.",
    action_sets=["gmail_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def untrash_gmail_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "untrash_thread",
        unwrap_envelope=True,
        fail_message="Failed to untrash thread.",
        thread_id=input_data["thread_id"],
    )


@action(
    name="delete_gmail_thread",
    description="Permanently delete a Gmail thread (all messages). Irreversible.",
    action_sets=["gmail_threads"],
    input_schema={
        "thread_id": {"type": "string", "description": "Thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_gmail_thread(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "delete_thread",
        unwrap_envelope=True,
        fail_message="Failed to delete thread.",
        thread_id=input_data["thread_id"],
    )


# ------------------------------------------------------------------
# Drafts
# ------------------------------------------------------------------


@action(
    name="list_gmail_drafts",
    description="List Gmail drafts.",
    action_sets=["gmail_drafts", "gmail"],
    input_schema={
        "max_results": {"type": "integer", "description": "Max drafts.", "example": 25},
        "query": {"type": "string", "description": "Optional q query.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_gmail_drafts(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "list_drafts",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list drafts.",
        max_results=input_data.get("max_results", 25),
        query=input_data.get("query") or None,
    )


@action(
    name="get_gmail_draft",
    description="Get a Gmail draft by ID.",
    action_sets=["gmail_drafts"],
    input_schema={
        "draft_id": {"type": "string", "description": "Draft ID.", "example": ""},
        "fmt": {
            "type": "string",
            "description": "metadata | full | minimal.",
            "example": "metadata",
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_gmail_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "get_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get draft.",
        draft_id=input_data["draft_id"],
        fmt=input_data.get("fmt", "metadata"),
    )


@action(
    name="create_gmail_draft",
    description="Create a Gmail draft (not sent). Returns the draft ID for later edit/send.",
    action_sets=["gmail_drafts", "gmail"],
    input_schema={
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
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_gmail_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "create_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to create draft.",
        to=input_data["to"],
        subject=input_data["subject"],
        body=input_data["body"],
        cc=input_data.get("cc") or None,
        bcc=input_data.get("bcc") or None,
        attachments=input_data.get("attachments"),
    )


@action(
    name="update_gmail_draft",
    description="Replace a Gmail draft's content. All fields are required (PUT semantics).",
    action_sets=["gmail_drafts"],
    input_schema={
        "draft_id": {"type": "string", "description": "Draft ID.", "example": ""},
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
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_gmail_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "update_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to update draft.",
        draft_id=input_data["draft_id"],
        to=input_data["to"],
        subject=input_data["subject"],
        body=input_data["body"],
        cc=input_data.get("cc") or None,
        bcc=input_data.get("bcc") or None,
        attachments=input_data.get("attachments"),
    )


@action(
    name="send_gmail_draft",
    irreversible=True,
    description="Send a previously-created Gmail draft.",
    action_sets=["gmail_drafts", "gmail"],
    input_schema={
        "draft_id": {"type": "string", "description": "Draft ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_gmail_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "send_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to send draft.",
        draft_id=input_data["draft_id"],
    )


@action(
    name="delete_gmail_draft",
    description="Permanently delete a Gmail draft.",
    action_sets=["gmail_drafts"],
    input_schema={
        "draft_id": {"type": "string", "description": "Draft ID.", "example": ""},
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_gmail_draft(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "delete_draft",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to delete draft.",
        draft_id=input_data["draft_id"],
    )


# ------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------


@action(
    name="list_gmail_labels",
    description="List all Gmail labels (system + user).",
    action_sets=["gmail_labels", "gmail"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_gmail_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "list_labels",
        unwrap_envelope=True,
        fail_message="Failed to list labels.",
    )


@action(
    name="get_gmail_label",
    description="Get a single Gmail label by ID.",
    action_sets=["gmail_labels"],
    input_schema={
        "label_id": {"type": "string", "description": "Label ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_gmail_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "get_label",
        unwrap_envelope=True,
        fail_message="Failed to get label.",
        label_id=input_data["label_id"],
    )


@action(
    name="create_gmail_label",
    description="Create a new user label. label_list_visibility: labelShow|labelShowIfUnread|labelHide. message_list_visibility: show|hide.",
    action_sets=["gmail_labels", "gmail"],
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
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_gmail_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "create_label",
        unwrap_envelope=True,
        fail_message="Failed to create label.",
        name=input_data["name"],
        label_list_visibility=input_data.get("label_list_visibility", "labelShow"),
        message_list_visibility=input_data.get("message_list_visibility", "show"),
        background_color=input_data.get("background_color") or None,
        text_color=input_data.get("text_color") or None,
    )


@action(
    name="update_gmail_label",
    description="Update (rename / recolor) a Gmail label.",
    action_sets=["gmail_labels"],
    input_schema={
        "label_id": {"type": "string", "description": "Label ID.", "example": ""},
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
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_gmail_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "update_label",
        unwrap_envelope=True,
        fail_message="Failed to update label.",
        label_id=input_data["label_id"],
        name=input_data.get("name") or None,
        label_list_visibility=input_data.get("label_list_visibility") or None,
        message_list_visibility=input_data.get("message_list_visibility") or None,
        background_color=input_data.get("background_color") or None,
        text_color=input_data.get("text_color") or None,
    )


@action(
    name="delete_gmail_label",
    description="Delete a Gmail label (also removes it from all messages/threads).",
    action_sets=["gmail_labels"],
    input_schema={
        "label_id": {"type": "string", "description": "Label ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_gmail_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "delete_label",
        unwrap_envelope=True,
        fail_message="Failed to delete label.",
        label_id=input_data["label_id"],
    )


# ------------------------------------------------------------------
# Attachments + profile
# ------------------------------------------------------------------


@action(
    name="download_gmail_attachment",
    description=(
        "Download a Gmail attachment to a local path. "
        "First call get_gmail with full_body=true to get the attachments list — "
        "each entry has attachment_id and filename. "
        "Pass save_to as a directory path and filename separately, or as a full file path."
    ),
    action_sets=["gmail_attachments", "gmail"],
    input_schema={
        "message_id": {"type": "string", "description": "Message ID.", "example": ""},
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
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def download_gmail_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "download_attachment",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to download attachment.",
        message_id=input_data["message_id"],
        attachment_id=input_data["attachment_id"],
        save_to=input_data["save_to"],
        filename=input_data.get("filename"),
    )


@action(
    name="get_gmail_profile",
    description="Get the authenticated user's Gmail profile: email address, message/thread totals, historyId.",
    action_sets=["gmail_mail", "gmail"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_gmail_profile(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "get_profile",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to get profile.",
    )


# ------------------------------------------------------------------
# Backwards-compat aliases (legacy action names — kept for skills/memory)
# ------------------------------------------------------------------


@action(
    name="send_google_workspace_email",
    irreversible=True,
    description="Send email via Google Workspace.",
    action_sets=["gmail_mail"],
    input_schema={
        "to_email": {
            "type": "string",
            "description": "Recipient.",
            "example": "user@example.com",
        },
        "subject": {"type": "string", "description": "Subject.", "example": "Hello"},
        "body": {"type": "string", "description": "Body.", "example": "Hi"},
        "from_email": {
            "type": "string",
            "description": "Optional sender email.",
            "example": "me@example.com",
        },
        "attachments": {"type": "array", "description": "Attachments.", "example": []},
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def send_google_workspace_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "send_email",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Email sent.",
        fail_message="Failed to send email.",
        to=input_data["to_email"],
        subject=input_data["subject"],
        body=input_data["body"],
        from_email=input_data.get("from_email"),
        attachments=input_data.get("attachments"),
    )


@action(
    name="read_recent_google_workspace_emails",
    description="Read recent emails.",
    action_sets=["gmail_mail"],
    input_schema={
        "n": {"type": "integer", "description": "Count.", "example": 5},
        "full_body": {"type": "boolean", "description": "Full body.", "example": False},
        "from_email": {
            "type": "string",
            "description": "Optional sender email.",
            "example": "me@example.com",
        },
        "account": {
            "type": "string",
            "description": "Optional Gmail account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_recent_google_workspace_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "gmail",
        "read_top_emails",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to read emails.",
        n=input_data.get("n", 5),
        full_body=input_data.get("full_body", False),
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - History API (users.history.list)
#     Incremental sync plumbing. The listener uses it internally.
# - Watch / push notifications (users.watch, users.stop)
#     Cloud Pub/Sub webhook setup; server-side infrastructure.
# - Settings (users.settings.*): vacation, filters, forwarding, sendAs, smimeInfo, cse
#     Each is a separate admin-style sub-resource. Could be added as
#     gmail_settings if needed. For an assistant, ad-hoc rules are
#     usually managed in the Gmail UI rather than via API.
# - Drafts.list with format=full
#     The metadata format works for the common "list and resume" case.
# - Messages.import / messages.insert (raw upload of an existing email)
#     Migration tooling, not interactive use.
