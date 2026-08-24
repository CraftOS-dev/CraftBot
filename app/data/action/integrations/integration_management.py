"""
Actions for managing external app integrations (connect, disconnect, list, status).

These actions allow the agent to help users connect to external apps like
WhatsApp, Telegram, Slack, Discord, etc. directly through conversation,
without requiring the user to navigate to settings in browser or terminal.
"""

from agent_core import action


# NOTE: integration alias/umbrella constants live in
# app.data.action.integrations._helpers and are imported INSIDE each handler.
# Action handlers run via exec() on their own extracted source, so module-level
# names defined here would NOT be in scope at runtime (NameError).


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
        # multi-account providers (gmail, slack, notion, ...) source connection state +
        # accounts from the multi-account IntegrationSystem; everything else
        # keeps the legacy handler.status() path. Metadata (name, icon,
        # auth_type, description) still comes from the legacy handlers.
        from app.data.action.integrations._helpers import list_integrations_merged

        integrations = list_integrations_merged()
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
                "The integration to connect, using its exact id. Valid values: slack, "
                "discord, telegram, whatsapp, whatsapp_business, notion, linkedin, and "
                "the Google Workspace apps as SEPARATE ids — gmail, google_drive, "
                "google_docs, google_calendar, google_youtube (there is no single "
                "'google' integration). Call list_available_integrations if unsure."
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

    from app.data.action.integrations._helpers import normalize_integration_id

    integration_id = input_data.get("integration_id", "").strip().lower()
    integration_id = normalize_integration_id(integration_id)
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

            # multi-account providers: validate the token the same way the legacy
            # handler login does, then store through the integration system
            # (multi-account store), never the legacy single-account save.
            from app.data.action.integrations._helpers import (
                system_connect_token,
                system_for,
            )

            v2_system = system_for(integration_id)
            if v2_system is not None:
                success, message = system_connect_token(
                    v2_system, integration_id, credentials
                )
                return {
                    "status": "success" if success else "error",
                    "message": message,
                    "auth_type": "token",
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

            # multi-account providers: real multi-account OAuth via the
            # IntegrationSystem (account chooser, identity capture,
            # listener reconcile) instead of the legacy handler flow.
            from app.data.action.integrations._helpers import system_for

            v2_system = system_for(integration_id)
            if v2_system is not None:
                loop = asyncio.new_event_loop()
                try:
                    success, message, _accounts = loop.run_until_complete(
                        v2_system.add_account(integration_id)
                    )
                finally:
                    loop.close()
                return {
                    "status": "success" if success else "error",
                    "message": message,
                    "auth_type": "oauth",
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
        from app.errors import make_error

        info = make_error("CONNECTION_FAILED", target=integration_id, detail=str(e))
        return {
            "status": "error",
            "message": info.message,
            "error_category": info.category.value,
            "error_code": info.code,
        }


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
            "description": (
                "The integration to check status for, using its exact id. Google "
                "Workspace apps are SEPARATE integrations — use 'gmail', "
                "'google_drive', 'google_docs', 'google_calendar', or "
                "'google_youtube', NOT 'google'. Call list_available_integrations "
                "if unsure of the exact id."
            ),
            "example": "gmail",
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

    from app.data.action.integrations._helpers import (
        GOOGLE_FAMILY,
        GOOGLE_UMBRELLA,
        normalize_integration_id,
    )

    integration_id = input_data.get("integration_id", "").strip().lower()
    session_id = input_data.get("session_id", "").strip()

    if not integration_id:
        return {"status": "error", "message": "integration_id is required."}

    # Normalize common aliases (e.g. 'gdrive' → 'google_drive').
    integration_id = normalize_integration_id(integration_id)

    # 'google' / 'google workspace' is not a single integration — the Workspace
    # apps are tracked separately. Guide the caller to the specific app instead
    # of failing with a bare "unknown integration".
    if integration_id in GOOGLE_UMBRELLA:
        return {
            "status": "error",
            "connected": False,
            "accounts": [],
            "message": (
                "'google' is not a single integration — Google Workspace apps are "
                "tracked separately. Check the specific app instead: "
                + ", ".join(GOOGLE_FAMILY)
                + "."
            ),
        }

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

            # On connect, store the account into the AccountSet — the QR
            # flow itself can't (craftos_integrations never imports the
            # host). Idempotent: repeated polls upsert the same identity.
            if result.get("connected") and result.get("credential"):
                try:
                    from app.integrations import get_system

                    system = get_system()
                    system.store_credential(
                        "whatsapp_web",
                        result.get("identity"),
                        result["credential"],
                    )
                    system.reconcile_listeners()
                except Exception as e:
                    return {
                        "status": "error",
                        "connected": False,
                        "accounts": [],
                        "message": f"WhatsApp connected but storing the account failed: {e}",
                    }

            return {
                "status": result.get("status", "error"),
                "connected": result.get("connected", False),
                "accounts": [],
                "message": result.get("message", ""),
            }

        # multi-account providers: connection state + accounts come from the
        # multi-account IntegrationSystem (never the legacy credential
        # files). Status text uses the shared plan-§6 line format; the
        # structured accounts array carries {identity, alias, isPrimary,
        # listen}.
        from app.data.action.integrations._helpers import (
            account_lines,
            accounts_payload,
            v2_display_name,
            system_for,
        )

        v2_system = system_for(integration_id)
        if v2_system is not None:
            infos = v2_system.list_accounts(integration_id)
            accounts = accounts_payload(infos, integration_id)
            name = v2_display_name(v2_system, integration_id)
            if accounts:
                lines = "\n".join(account_lines(infos))
                message = (
                    f"{name} is connected with {len(accounts)} account(s):\n{lines}"
                )
            else:
                message = f"{name} is not connected."
            return {
                "status": "success",
                "connected": bool(accounts),
                "accounts": accounts,
                "message": message,
            }

        # Otherwise check general integration status
        from craftos_integrations import (
            get_integration_info_sync as get_integration_info,
        )

        info = get_integration_info(integration_id)
        if not info:
            # List the valid ids so the agent can self-correct instead of
            # repeating an invalid guess.
            try:
                from craftos_integrations import list_all

                valid = ", ".join(sorted(list_all()))
            except Exception:
                valid = ""
            message = f"Unknown integration: '{integration_id}'."
            if valid:
                message += f" Valid integrations: {valid}."
            return {
                "status": "error",
                "connected": False,
                "accounts": [],
                "message": message,
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

    from app.data.action.integrations._helpers import normalize_integration_id

    integration_id = input_data.get("integration_id", "").strip().lower()
    integration_id = normalize_integration_id(integration_id)
    account_id = input_data.get("account_id", "").strip() or None

    if not integration_id:
        return {"status": "error", "message": "integration_id is required."}

    try:
        # multi-account providers: remove accounts through the multi-account
        # IntegrationSystem (with account_id: just that account; without:
        # all of them, plus a best-effort legacy-file double-cleanup).
        from app.data.action.integrations._helpers import system_disconnect, system_for

        v2_system = system_for(integration_id)
        if v2_system is not None:
            success, message = system_disconnect(v2_system, integration_id, account_id)
            return {
                "status": "success" if success else "error",
                "message": message,
            }

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


@action(
    name="manage_integration_account",
    description=(
        "Manage a connected integration account: set it as the primary "
        "(default) account, give it a nickname/alias, or turn inbound "
        "listening on/off for it. Use when the user says things like 'make "
        "my work Gmail the default', 'call this account job-search', or "
        "'stop listening on my second Slack'."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "integration_id": {
            "type": "string",
            "description": "The integration the account belongs to.",
            "example": "gmail",
        },
        "account": {
            "type": "string",
            "description": (
                "Which account: an identity (email/id), the user's alias for "
                "it, or any unique fragment of either."
            ),
            "example": "work",
        },
        "operation": {
            "type": "string",
            "description": "One of: set_primary | set_alias | set_listening",
            "example": "set_primary",
        },
        "value": {
            "type": "string",
            "description": (
                "For set_alias: the new alias (empty clears it). For "
                "set_listening: 'true' or 'false'. Ignored for set_primary."
            ),
            "example": "",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "message": {"type": "string", "description": "Human-readable result."},
        "accounts": {
            "type": "array",
            "description": "The integration's accounts after the change.",
        },
    },
    test_payload={
        "integration_id": "gmail",
        "account": "work",
        "operation": "set_primary",
        "simulated_mode": True,
    },
)
def manage_integration_account(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "message": "Simulated mode"}

    from app.data.action.integrations._helpers import (
        accounts_payload,
        normalize_integration_id,
        system_for,
    )

    integration_id = normalize_integration_id(
        (input_data.get("integration_id") or "").strip().lower()
    )
    account = (input_data.get("account") or "").strip() or None
    operation = (input_data.get("operation") or "").strip().lower()
    value = (input_data.get("value") or "").strip()

    if not integration_id:
        return {"status": "error", "message": "integration_id is required."}
    if operation not in ("set_primary", "set_alias", "set_listening"):
        return {
            "status": "error",
            "message": (
                f"Unknown operation {operation!r}. Use set_primary, "
                f"set_alias, or set_listening."
            ),
        }

    system = system_for(integration_id)
    if system is None:
        return {
            "status": "error",
            "message": f"Unknown integration: {integration_id}",
        }

    try:
        if operation == "set_primary":
            identity = system.set_primary(integration_id, account)
            message = f"'{identity}' is now the primary {integration_id} account."
        elif operation == "set_alias":
            identity = system.set_alias(integration_id, account, value or None)
            message = (
                f"Alias for '{identity}' set to '{value}'."
                if value
                else f"Alias for '{identity}' cleared."
            )
        else:  # set_listening
            if value.lower() not in ("true", "false"):
                return {
                    "status": "error",
                    "message": "set_listening needs value 'true' or 'false'.",
                }
            on = value.lower() == "true"
            identity = system.set_listening(integration_id, account, on)
            message = (
                f"Listening {'enabled' if on else 'disabled'} for "
                f"'{identity}' on {integration_id}."
            )
        return {
            "status": "success",
            "message": message,
            "accounts": accounts_payload(system.list_accounts(integration_id)),
        }
    except Exception as e:
        # AccountResolutionError messages already enumerate the valid
        # accounts, so the model can self-correct on a bad hint.
        return {"status": "error", "message": str(e)}
