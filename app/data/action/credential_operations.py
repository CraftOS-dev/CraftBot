"""Agent surfaces accept identifiers and operation data, never source values."""

from agent_core import action


@action(
    name="use_saved_credential",
    description="Request one installed credential operation using an owner-selected source reference. The protected host asks the owner to approve the caller, account, operation and destination. Never request or provide a password/API-key value. Use Settings > Credentials for secure entry. Unknown helpers fail closed.",
    mode="ALL",
    execution_mode="internal",
    parallelizable=False,
    irreversible=True,
    input_schema={
        "reference": {
            "type": "string",
            "description": "Owner-provided craftbot-vault:// source reference.",
        },
        "helper": {"type": "string", "description": "Installed helper ID."},
        "operation": {"type": "string", "description": "Installed operation name."},
        "body": {
            "type": "object",
            "description": "Operation JSON data; never a URL, headers or source credentials.",
        },
    },
    output_schema={"status": {"type": "string"}, "result": {"type": "object"}},
)
async def use_saved_credential(input_data: dict) -> dict:
    from app.credentials.invocation import invoke_async

    try:
        response = await invoke_async(
            input_data["reference"],
            input_data["helper"],
            input_data["operation"],
            input_data.get("body"),
            subject="Agent credential operation",
        )
        body = response["body"]
        return {
            "status": "success" if 200 <= response["status"] < 300 else "error",
            "result": {
                "http_status": response["status"],
                "body": body[:12000],
                "truncated": len(body) > 12000,
            },
        }
    except Exception:
        return {
            "status": "error",
            "message": "Credential use needs a supported helper, current reference and owner approval. Open Settings > Credentials to add or unlock an item.",
        }


@action(
    name="request_credential_entry",
    description="Ask the owner to save a credential in the protected native dialog for an installed helper. Requires an owner-selected initialized profile ID. Returns only a reference. Saving grants no permission to use the credential. Never ask for secret values in chat or action input.",
    mode="ALL",
    execution_mode="internal",
    parallelizable=False,
    irreversible=True,
    input_schema={
        "profile_id": {
            "type": "string",
            "description": "Owner-selected vault profile UUID.",
        },
        "helper": {"type": "string", "description": "Installed helper ID."},
        "operation": {"type": "string", "description": "Installed operation name."},
        "account": {
            "type": "string",
            "description": "Visible account label; no username, key or password value.",
        },
    },
    output_schema={"status": {"type": "string"}, "reference": {"type": "string"}},
)
async def request_credential_entry(input_data: dict) -> dict:
    from app.credentials.consumer_runtime import execute_action

    code = """def secure_entry(data):
    import credential_client
    result = credential_client.request_entry(data['helper'], data['operation'], data['account'])
    return {'status': 'success', 'reference': result['reference']}
"""
    try:
        return await execute_action(
            code,
            {key: input_data[key] for key in ("helper", "operation", "account")},
            profile_id=input_data["profile_id"],
            subject="Agent secure credential entry",
            timeout=600,
        )
    except Exception:
        return {
            "status": "error",
            "message": "Secure entry requires the installed service, an initialized owner-selected profile, supported helper and native owner approval.",
        }
