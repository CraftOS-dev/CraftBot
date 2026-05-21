from agent_core import action


@action(
    name="send_outlook_email",
    description="Send an email via Outlook (Microsoft 365).",
    action_sets=["outlook"],
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
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "send_email",
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
    action_sets=["outlook"],
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
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_emails",
        unwrap_envelope=True,
        fail_message="Failed to list emails.",
        n=input_data.get("count", 10),
        unread_only=input_data.get("unread_only", False),
    )


@action(
    name="get_outlook_email",
    description="Get full details of a specific Outlook email by message ID.",
    action_sets=["outlook"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Outlook message ID.",
            "example": "AAMk...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_outlook_email(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "get_email",
        unwrap_envelope=True,
        fail_message="Failed to get email.",
        message_id=input_data["message_id"],
    )


@action(
    name="read_top_outlook_emails",
    description="Read the top N recent Outlook emails with details.",
    action_sets=["outlook"],
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
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_top_outlook_emails(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "read_top_emails",
        unwrap_envelope=True,
        fail_message="Failed to read emails.",
        n=input_data.get("count", 5),
        full_body=input_data.get("full_body", False),
    )


@action(
    name="mark_outlook_email_read",
    description="Mark an Outlook email as read.",
    action_sets=["outlook"],
    input_schema={
        "message_id": {
            "type": "string",
            "description": "Outlook message ID.",
            "example": "AAMk...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def mark_outlook_email_read(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "mark_as_read",
        unwrap_envelope=True,
        success_message="Email marked as read.",
        fail_message="Failed to mark email.",
        message_id=input_data["message_id"],
    )


@action(
    name="list_outlook_folders",
    description="List mail folders in Outlook.",
    action_sets=["outlook"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_folders(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "outlook",
        "list_folders",
        unwrap_envelope=True,
        fail_message="Failed to list folders.",
    )
