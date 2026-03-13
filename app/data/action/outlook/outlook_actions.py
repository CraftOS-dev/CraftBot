from agent_core import action


@action(
    name="send_outlook_email",
    description="Send an email via Outlook (Microsoft 365).",
    action_sets=["outlook"],
    input_schema={
        "to": {"type": "string", "description": "Recipient email address.", "example": "user@example.com"},
        "subject": {"type": "string", "description": "Email subject.", "example": "Meeting Follow-up"},
        "body": {"type": "string", "description": "Email body text.", "example": "Hi, here are the notes..."},
        "cc": {"type": "string", "description": "Optional CC recipients (comma-separated).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def send_outlook_email(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.outlook import OutlookClient
        client = OutlookClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Outlook credential. Use /outlook login first."}
        result = client.send_email(
            to=input_data["to"],
            subject=input_data["subject"],
            body=input_data["body"],
            cc=input_data.get("cc"),
        )
        if result.get("ok"):
            return {"status": "success", "message": "Email sent."}
        return {"status": "error", "message": result.get("error", "Failed to send email.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="list_outlook_emails",
    description="List recent emails from Outlook inbox.",
    action_sets=["outlook"],
    input_schema={
        "count": {"type": "integer", "description": "Number of recent emails to list.", "example": 10},
        "unread_only": {"type": "boolean", "description": "Only show unread emails.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_emails(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.outlook import OutlookClient
        client = OutlookClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Outlook credential. Use /outlook login first."}
        result = client.list_emails(
            n=input_data.get("count", 10),
            unread_only=input_data.get("unread_only", False),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to list emails.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_outlook_email",
    description="Get full details of a specific Outlook email by message ID.",
    action_sets=["outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Outlook message ID.", "example": "AAMk..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_outlook_email(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.outlook import OutlookClient
        client = OutlookClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Outlook credential. Use /outlook login first."}
        result = client.get_email(message_id=input_data["message_id"])
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to get email.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="read_top_outlook_emails",
    description="Read the top N recent Outlook emails with details.",
    action_sets=["outlook"],
    input_schema={
        "count": {"type": "integer", "description": "Number of emails to read.", "example": 5},
        "full_body": {"type": "boolean", "description": "Include full body text.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def read_top_outlook_emails(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.outlook import OutlookClient
        client = OutlookClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Outlook credential. Use /outlook login first."}
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
    name="mark_outlook_email_read",
    description="Mark an Outlook email as read.",
    action_sets=["outlook"],
    input_schema={
        "message_id": {"type": "string", "description": "Outlook message ID.", "example": "AAMk..."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def mark_outlook_email_read(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.outlook import OutlookClient
        client = OutlookClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Outlook credential. Use /outlook login first."}
        result = client.mark_as_read(message_id=input_data["message_id"])
        if result.get("ok"):
            return {"status": "success", "message": "Email marked as read."}
        return {"status": "error", "message": result.get("error", "Failed to mark email.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="list_outlook_folders",
    description="List mail folders in Outlook.",
    action_sets=["outlook"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_outlook_folders(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.outlook import OutlookClient
        client = OutlookClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Outlook credential. Use /outlook login first."}
        result = client.list_folders()
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to list folders.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}
