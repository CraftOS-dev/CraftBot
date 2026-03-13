from agent_core import action


@action(
    name="send_gmail",
    description="Send an email via Gmail.",
    action_sets=["google_workspace"],
    input_schema={
        "to": {"type": "string", "description": "Recipient email address.", "example": "user@example.com"},
        "subject": {"type": "string", "description": "Email subject.", "example": "Meeting Follow-up"},
        "body": {"type": "string", "description": "Email body text.", "example": "Hi, here are the notes..."},
        "attachments": {"type": "array", "description": "Optional list of file paths to attach.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_gmail(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.send_email(
            to=input_data["to"],
            subject=input_data["subject"],
            body=input_data["body"],
            attachments=input_data.get("attachments"),
        )
        if result.get("ok"):
            return {"status": "success", "message": "Email sent."}
        return {"status": "error", "message": result.get("error", "Failed to send email.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="list_gmail",
    description="List recent emails from Gmail inbox.",
    action_sets=["google_workspace"],
    input_schema={
        "count": {"type": "integer", "description": "Number of recent emails to list.", "example": 5},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_gmail(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.list_emails(n=input_data.get("count", 5))
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to list emails.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_gmail",
    description="Get details of a specific Gmail message by ID.",
    action_sets=["google_workspace"],
    input_schema={
        "message_id": {"type": "string", "description": "Gmail message ID.", "example": "18abc123def"},
        "full_body": {"type": "boolean", "description": "Whether to include full email body.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_gmail(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.get_email(
            message_id=input_data["message_id"],
            full_body=input_data.get("full_body", False),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to get email.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="read_top_emails",
    description="Read the top N recent emails with details.",
    action_sets=["google_workspace"],
    input_schema={
        "count": {"type": "integer", "description": "Number of emails to read.", "example": 5},
        "full_body": {"type": "boolean", "description": "Include full body text.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_top_emails(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.read_top_emails(
            n=input_data.get("count", 5),
            full_body=input_data.get("full_body", False),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to read emails.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="send_google_workspace_email",
    description="Send email via Google Workspace.",
    action_sets=["google_workspace"],
    input_schema={
        "to_email": {"type": "string", "description": "Recipient.", "example": "user@example.com"},
        "subject": {"type": "string", "description": "Subject.", "example": "Hello"},
        "body": {"type": "string", "description": "Body.", "example": "Hi"},
        "from_email": {"type": "string", "description": "Optional sender email.", "example": "me@example.com"},
        "attachments": {"type": "array", "description": "Attachments.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_google_workspace_email(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.send_email(
            to=input_data["to_email"],
            subject=input_data["subject"],
            body=input_data["body"],
            from_email=input_data.get("from_email"),
            attachments=input_data.get("attachments"),
        )
        if result.get("ok"):
            return {"status": "success", "message": "Email sent.", "result": result.get("result")}
        return {"status": "error", "message": result.get("error", "Failed to send email.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="read_recent_google_workspace_emails",
    description="Read recent emails.",
    action_sets=["google_workspace"],
    input_schema={
        "n": {"type": "integer", "description": "Count.", "example": 5},
        "full_body": {"type": "boolean", "description": "Full body.", "example": False},
        "from_email": {"type": "string", "description": "Optional sender email.", "example": "me@example.com"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_recent_google_workspace_emails(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.read_top_emails(
            n=input_data.get("n", 5),
            full_body=input_data.get("full_body", False),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to read emails.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}
