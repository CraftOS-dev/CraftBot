"""
Actions for managing external app integrations (connect, disconnect, list, status).

These actions allow the agent to help users connect to external apps like
WhatsApp, Telegram, Slack, Discord, etc. directly through conversation,
without requiring the user to navigate to settings in browser or terminal.
"""

from agent_core import action


@action(
    name="list_available_integrations",
    description=(
        "List all available external app integrations and their connection status. "
        "Use this when the user asks what apps they can connect, wants to see which "
        "integrations are available, or asks about their connected accounts. "
        "Returns each integration's name, type, connection status, and connected accounts."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "filter_connected": {
            "type": "boolean",
            "description": "If true, only show connected integrations. If false, show all available integrations.",
            "example": False,
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result status.",
        },
        "integrations": {
            "type": "array",
            "description": "List of integration info objects.",
        },
        "message": {
            "type": "string",
            "description": "Human-readable summary.",
        },
    },
    test_payload={
        "filter_connected": False,
        "simulated_mode": True,
    },
)
def list_available_integrations(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "integrations": [], "message": "Simulated mode"}

    try:
        from craftos_integrations import list_integrations_sync as list_integrations

        integrations = list_integrations()
        filter_connected = input_data.get("filter_connected", False)

        if filter_connected:
            integrations = [i for i in integrations if i["connected"]]

        return {
            "status": "success",
            "integrations": integrations,
            "message": f"Found {len(integrations)} integration(s).",
        }
    except Exception as e:
        return {"status": "error", "integrations": [], "message": str(e)}


@action(
    name="connect_integration",
    description=(
        "Connect an external app integration. Use this when the user wants to connect "
        "to an external app such as WhatsApp, Telegram, Slack, Discord, Notion, LinkedIn, "
        "Google Workspace, or others. "
        "For token-based integrations (Telegram Bot, Discord, Slack, WhatsApp Business, Notion), "
        "the user needs to provide their credentials/tokens - ask the user for the required "
        "fields before calling this action. "
        "For OAuth integrations (Google, LinkedIn, Slack invite), this will start the OAuth "
        "flow and provide a URL for the user to open in their browser. "
        "For interactive integrations (WhatsApp Web), this will start a QR code session "
        "that the user needs to scan with their phone. "
        "IMPORTANT: Before calling this action, first use list_available_integrations to "
        "check which integrations are available and their auth requirements, then ask the "
        "user for any required credentials."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "integration_id": {
            "type": "string",
            "description": (
                "The integration to connect. Valid values: slack, discord, telegram, "
                "whatsapp, whatsapp_business, google, notion, linkedin."
            ),
            "example": "telegram",
        },
        "credentials": {
            "type": "object",
            "description": (
                "Credentials for token-based auth. Keys depend on the integration: "
                "slack: {bot_token, workspace_name(optional)}, "
                "discord: {bot_token}, "
                "telegram: {bot_token}, "
                "whatsapp_business: {access_token, phone_number_id}, "
                "notion: {token}. "
                "Leave empty for OAuth or interactive (QR code) flows."
            ),
            "example": {"bot_token": "123456:ABC-DEF"},
        },
        "auth_method": {
            "type": "string",
            "description": (
                "Which auth method to use. 'token' for providing credentials directly, "
                "'oauth' for browser-based OAuth flow, 'interactive' for QR code scan "
                "(WhatsApp Web, Telegram user account). If not specified, the best "
                "method is chosen automatically based on the integration type."
            ),
            "example": "token",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result status: success, error, qr_ready, or oauth_started.",
        },
        "message": {
            "type": "string",
            "description": "Human-readable result message.",
        },
        "auth_type": {
            "type": "string",
            "description": "The auth type used for this connection.",
        },
        "qr_code": {
            "type": "string",
            "description": "Base64 QR code image data (only for interactive/QR flows).",
        },
        "session_id": {
            "type": "string",
            "description": "Session ID for QR code status polling (only for interactive flows).",
        },
        "required_fields": {
            "type": "array",
            "description": "List of required credential fields if credentials were missing.",
        },
    },
    test_payload={
        "integration_id": "telegram",
        "credentials": {"bot_token": "test_token"},
        "simulated_mode": True,
    },
)
def connect_integration(input_data: dict) -> dict:
    import asyncio

    if input_data.get("simulated_mode"):
        return {"status": "success", "message": "Simulated mode", "auth_type": "token"}

    integration_id = input_data.get("integration_id", "").strip().lower()
    credentials = input_data.get("credentials", {}) or {}
    auth_method = input_data.get("auth_method", "").strip().lower()

    if not integration_id:
        return {"status": "error", "message": "integration_id is required."}

    try:
        from craftos_integrations import (
            connect_token as connect_integration_token,
            connect_oauth as connect_integration_oauth,
            connect_interactive as connect_integration_interactive,
            get_integration_fields,
            integration_registry,
        )
        from craftos_integrations.integrations.whatsapp_web import (
            start_qr_session as start_whatsapp_qr_session,
        )

        INTEGRATION_REGISTRY = integration_registry()

        if integration_id not in INTEGRATION_REGISTRY:
            available = ", ".join(INTEGRATION_REGISTRY.keys())
            return {
                "status": "error",
                "message": f"Unknown integration: '{integration_id}'. Available: {available}",
            }

        info = INTEGRATION_REGISTRY[integration_id]
        supported_auth = info["auth_type"]

        # Determine which auth method to use
        if not auth_method:
            if credentials:
                auth_method = "token"
            elif supported_auth == "oauth":
                auth_method = "oauth"
            elif supported_auth == "interactive":
                auth_method = "interactive"
            elif supported_auth == "token_with_interactive":
                # If no credentials provided, default to token (user needs to provide them)
                auth_method = "token"
            elif supported_auth == "both":
                # Default to token if credentials are provided, otherwise oauth
                auth_method = "token" if credentials else "oauth"
            else:
                auth_method = "token"

        # --- Token-based connection ---
        if auth_method == "token":
            required_fields = get_integration_fields(integration_id)

            if not credentials and required_fields:
                return {
                    "status": "needs_credentials",
                    "message": (
                        f"To connect {info['name']}, please provide the following credentials."
                    ),
                    "auth_type": "token",
                    "required_fields": [
                        {
                            "key": f["key"],
                            "label": f["label"],
                            "placeholder": f.get("placeholder", ""),
                            "is_secret": f.get("password", False),
                        }
                        for f in required_fields
                    ],
                }

            # Validate required fields are present
            missing = []
            for field in required_fields:
                if field.get("password", False) or not field.get(
                    "placeholder", ""
                ).startswith("(optional"):
                    if not credentials.get(field["key"]):
                        # Check if the field is truly required (non-optional)
                        label = field.get("label", field["key"])
                        if "optional" not in label.lower():
                            missing.append(field)

            if missing:
                return {
                    "status": "needs_credentials",
                    "message": "Some required credentials are missing.",
                    "auth_type": "token",
                    "required_fields": [
                        {
                            "key": f["key"],
                            "label": f["label"],
                            "placeholder": f.get("placeholder", ""),
                            "is_secret": f.get("password", False),
                        }
                        for f in missing
                    ],
                }

            loop = asyncio.new_event_loop()
            try:
                success, message = loop.run_until_complete(
                    connect_integration_token(integration_id, credentials)
                )
            finally:
                loop.close()

            return {
                "status": "success" if success else "error",
                "message": message,
                "auth_type": "token",
            }

        # --- OAuth-based connection ---
        elif auth_method == "oauth":
            if supported_auth not in ("oauth", "both"):
                return {
                    "status": "error",
                    "message": f"OAuth is not supported for {info['name']}. Use token-based auth instead.",
                    "auth_type": supported_auth,
                }

            loop = asyncio.new_event_loop()
            try:
                success, message = loop.run_until_complete(
                    connect_integration_oauth(integration_id)
                )
            finally:
                loop.close()

            return {
                "status": "success" if success else "error",
                "message": message,
                "auth_type": "oauth",
            }

        # --- Interactive (QR code) connection ---
        elif auth_method == "interactive":
            if supported_auth not in ("interactive", "token_with_interactive"):
                return {
                    "status": "error",
                    "message": f"Interactive login is not supported for {info['name']}.",
                    "auth_type": supported_auth,
                }

            # Special handling for WhatsApp QR code flow
            if integration_id == "whatsapp":
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(start_whatsapp_qr_session())
                finally:
                    loop.close()

                if result.get("success") and result.get("status") == "qr_ready":
                    return {
                        "status": "qr_ready",
                        "message": result.get(
                            "message", "Scan the QR code with WhatsApp on your phone."
                        ),
                        "auth_type": "interactive",
                        "qr_code": result.get("qr_code", ""),
                        "session_id": result.get("session_id", ""),
                    }
                elif result.get("success") and result.get("status") == "connected":
                    return {
                        "status": "success",
                        "message": result.get(
                            "message", "WhatsApp connected successfully!"
                        ),
                        "auth_type": "interactive",
                    }
                else:
                    return {
                        "status": "error",
                        "message": result.get(
                            "message", "Failed to start WhatsApp session."
                        ),
                        "auth_type": "interactive",
                    }

            # Generic interactive flow for other integrations (e.g., Telegram user)
            loop = asyncio.new_event_loop()
            try:
                success, message = loop.run_until_complete(
                    connect_integration_interactive(integration_id)
                )
            finally:
                loop.close()

            return {
                "status": "success" if success else "error",
                "message": message,
                "auth_type": "interactive",
            }

        else:
            return {
                "status": "error",
                "message": f"Unknown auth method: '{auth_method}'. Use 'token', 'oauth', or 'interactive'.",
            }

    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


@action(
    name="check_integration_status",
    description=(
        "Check the connection status of a specific integration, or check the status "
        "of an ongoing WhatsApp QR code session. Use this to verify if an integration "
        "is connected, or to poll whether a QR code has been scanned."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "integration_id": {
            "type": "string",
            "description": "The integration to check status for.",
            "example": "telegram",
        },
        "session_id": {
            "type": "string",
            "description": "Session ID for checking WhatsApp QR scan status (from connect_integration result).",
            "example": "",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
        },
        "connected": {
            "type": "boolean",
            "description": "Whether the integration is currently connected.",
        },
        "accounts": {
            "type": "array",
            "description": "List of connected accounts.",
        },
        "message": {
            "type": "string",
            "description": "Human-readable status message.",
        },
    },
    test_payload={
        "integration_id": "telegram",
        "simulated_mode": True,
    },
)
def check_integration_status(input_data: dict) -> dict:
    import asyncio

    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "connected": False,
            "accounts": [],
            "message": "Simulated",
        }

    integration_id = input_data.get("integration_id", "").strip().lower()
    session_id = input_data.get("session_id", "").strip()

    if not integration_id:
        return {"status": "error", "message": "integration_id is required."}

    try:
        # If a session_id is provided, check WhatsApp QR session status
        if session_id and integration_id == "whatsapp":
            from craftos_integrations.integrations.whatsapp_web import (
                check_qr_session_status as check_whatsapp_session_status,
            )

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    check_whatsapp_session_status(session_id)
                )
            finally:
                loop.close()

            return {
                "status": result.get("status", "error"),
                "connected": result.get("connected", False),
                "accounts": [],
                "message": result.get("message", ""),
            }

        # Otherwise check general integration status
        from craftos_integrations import (
            get_integration_info_sync as get_integration_info,
        )

        info = get_integration_info(integration_id)
        if not info:
            return {
                "status": "error",
                "connected": False,
                "accounts": [],
                "message": f"Unknown integration: '{integration_id}'.",
            }

        return {
            "status": "success",
            "connected": info["connected"],
            "accounts": info.get("accounts", []),
            "message": (
                f"{info['name']} is connected with {len(info.get('accounts', []))} account(s)."
                if info["connected"]
                else f"{info['name']} is not connected."
            ),
        }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "accounts": [],
            "message": str(e),
        }


@action(
    name="disconnect_integration",
    description=(
        "Disconnect an external app integration. Use this when the user wants to "
        "remove or disconnect a connected app like WhatsApp, Telegram, Slack, etc. "
        "Optionally specify a specific account to disconnect if multiple are connected."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "integration_id": {
            "type": "string",
            "description": "The integration to disconnect.",
            "example": "slack",
        },
        "account_id": {
            "type": "string",
            "description": "Optional specific account ID to disconnect (if multiple accounts are connected).",
            "example": "",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
        },
        "message": {
            "type": "string",
            "description": "Human-readable result message.",
        },
    },
    test_payload={
        "integration_id": "slack",
        "simulated_mode": True,
    },
)
def disconnect_integration(input_data: dict) -> dict:
    import asyncio

    if input_data.get("simulated_mode"):
        return {"status": "success", "message": "Simulated mode"}

    integration_id = input_data.get("integration_id", "").strip().lower()
    account_id = input_data.get("account_id", "").strip() or None

    if not integration_id:
        return {"status": "error", "message": "integration_id is required."}

    try:
        from craftos_integrations import disconnect as _disconnect

        loop = asyncio.new_event_loop()
        try:
            success, message = loop.run_until_complete(
                _disconnect(integration_id, account_id)
            )
        finally:
            loop.close()

        return {
            "status": "success" if success else "error",
            "message": message,
        }
    except Exception as e:
        return {"status": "error", "message": f"Disconnect failed: {str(e)}"}
