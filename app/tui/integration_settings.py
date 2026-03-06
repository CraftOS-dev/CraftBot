"""Integration settings management for the TUI."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Integration metadata registry with auth types and field definitions
INTEGRATION_REGISTRY: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google Workspace",
        "description": "Gmail, Calendar, Drive",
        "auth_type": "oauth",
        "fields": [],
    },
    "slack": {
        "name": "Slack",
        "description": "Team messaging",
        "auth_type": "both",  # Has both OAuth (invite) and token (login)
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "placeholder": "xoxb-...", "password": True},
            {"key": "workspace_name", "label": "Workspace Name (optional)", "placeholder": "My Workspace", "password": False},
        ],
    },
    "notion": {
        "name": "Notion",
        "description": "Notes and databases",
        "auth_type": "both",
        "fields": [
            {"key": "token", "label": "Integration Token", "placeholder": "secret_...", "password": True},
        ],
    },
    "linkedin": {
        "name": "LinkedIn",
        "description": "Professional network",
        "auth_type": "oauth",
        "fields": [],
    },
"discord": {
        "name": "Discord",
        "description": "Community chat",
        "auth_type": "token",
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "placeholder": "Enter bot token", "password": True},
        ],
    },
    "telegram": {
        "name": "Telegram",
        "description": "Messaging platform",
        "auth_type": "token_with_interactive",  # Bot token AND QR code user login
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "placeholder": "From @BotFather", "password": True},
        ],
    },
    "whatsapp": {
        "name": "WhatsApp",
        "description": "Messaging via Web",
        "auth_type": "interactive",  # Requires QR code scan
        "fields": [],
    },
"whatsapp_business": {
        "name": "WhatsApp Business",
        "description": "WhatsApp Cloud API",
        "auth_type": "token",
        "fields": [
            {"key": "access_token", "label": "Access Token", "placeholder": "Enter access token", "password": True},
            {"key": "phone_number_id", "label": "Phone Number ID", "placeholder": "Enter phone number ID", "password": False},
        ],
    },
}


def _get_handler(integration_id: str):
    """Get the integration handler for the given ID."""
    from app.credentials.handlers import INTEGRATION_HANDLERS
    return INTEGRATION_HANDLERS.get(integration_id)


def _parse_status_accounts(status_message: str) -> List[Dict[str, str]]:
    """Parse account info from status message.

    Status messages are in format:
    "Integration: Connected
      - Account Name (account_id)"
    or
    "  Bots:
        - BotName (bot_id)
      Users:
        - UserName (user_id)"
    """
    accounts = []
    lines = status_message.split("\n")

    for line in lines:
        line = line.strip()
        if line.startswith("- "):
            # Extract account info: "- Name (id)" or "- @username (id)"
            info = line[2:].strip()
            if "(" in info and info.endswith(")"):
                # Has ID in parentheses
                name_part = info[:info.rfind("(")].strip()
                id_part = info[info.rfind("(")+1:-1].strip()
                accounts.append({"display": name_part, "id": id_part})
            else:
                # No ID, just name
                accounts.append({"display": info, "id": info})

    return accounts


def list_integrations() -> List[Dict[str, Any]]:
    """List all integrations with their connection status.

    Returns list of dicts with:
    - id: Integration ID
    - name: Display name
    - description: Short description
    - auth_type: oauth, token, both, interactive, or token_with_interactive
    - connected: bool
    - accounts: list of connected accounts
    - fields: list of input field definitions for token auth
    """
    results = []

    for integration_id, info in INTEGRATION_REGISTRY.items():
        handler = _get_handler(integration_id)
        connected = False
        accounts = []

        if handler:
            try:
                # Run status synchronously
                loop = asyncio.new_event_loop()
                try:
                    success, status_msg = loop.run_until_complete(handler.status())
                finally:
                    loop.close()

                # Check if connected based on status message
                if "Connected" in status_msg and "Not connected" not in status_msg:
                    connected = True
                    accounts = _parse_status_accounts(status_msg)
            except Exception as e:
                logger.warning(f"Failed to get status for {integration_id}: {e}")

        results.append({
            "id": integration_id,
            "name": info["name"],
            "description": info["description"],
            "auth_type": info["auth_type"],
            "connected": connected,
            "accounts": accounts,
            "fields": info.get("fields", []),
        })

    return results


def get_integration_info(integration_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed info about a specific integration."""
    if integration_id not in INTEGRATION_REGISTRY:
        return None

    info = INTEGRATION_REGISTRY[integration_id]
    handler = _get_handler(integration_id)
    connected = False
    accounts = []

    if handler:
        try:
            loop = asyncio.new_event_loop()
            try:
                success, status_msg = loop.run_until_complete(handler.status())
            finally:
                loop.close()

            if "Connected" in status_msg and "Not connected" not in status_msg:
                connected = True
                accounts = _parse_status_accounts(status_msg)
        except Exception as e:
            logger.warning(f"Failed to get status for {integration_id}: {e}")

    return {
        "id": integration_id,
        "name": info["name"],
        "description": info["description"],
        "auth_type": info["auth_type"],
        "connected": connected,
        "accounts": accounts,
        "fields": info.get("fields", []),
    }


def get_integration_accounts(integration_id: str) -> List[Dict[str, str]]:
    """Get list of connected accounts for an integration."""
    info = get_integration_info(integration_id)
    if info:
        return info.get("accounts", [])
    return []


async def connect_integration_token(integration_id: str, credentials: Dict[str, str]) -> Tuple[bool, str]:
    """Connect an integration using provided credentials/tokens.

    Args:
        integration_id: The integration to connect
        credentials: Dict of field key -> value

    Returns:
        (success, message) tuple
    """
    handler = _get_handler(integration_id)
    if not handler:
        return False, f"Unknown integration: {integration_id}"

    # Build args list based on integration type
    args = []

    if integration_id == "slack":
        bot_token = credentials.get("bot_token", "")
        if not bot_token:
            return False, "Bot token is required"
        args = [bot_token]
        workspace_name = credentials.get("workspace_name", "")
        if workspace_name:
            args.append(workspace_name)

    elif integration_id == "notion":
        token = credentials.get("token", "")
        if not token:
            return False, "Integration token is required"
        args = [token]

    elif integration_id == "discord":
        bot_token = credentials.get("bot_token", "")
        if not bot_token:
            return False, "Bot token is required"
        args = [bot_token]

    elif integration_id == "telegram":
        bot_token = credentials.get("bot_token", "")
        if not bot_token:
            return False, "Bot token is required"
        args = [bot_token]

    elif integration_id == "whatsapp_business":
        access_token = credentials.get("access_token", "")
        phone_number_id = credentials.get("phone_number_id", "")
        if not access_token or not phone_number_id:
            return False, "Access token and phone number ID are required"
        args = [access_token, phone_number_id]

    else:
        return False, f"Token-based login not supported for {integration_id}"

    try:
        return await handler.login(args)
    except Exception as e:
        logger.error(f"Failed to connect {integration_id}: {e}")
        return False, f"Connection failed: {str(e)}"


async def connect_integration_oauth(integration_id: str) -> Tuple[bool, str]:
    """Start OAuth flow for an integration.

    Args:
        integration_id: The integration to connect via OAuth

    Returns:
        (success, message) tuple
    """
    handler = _get_handler(integration_id)
    if not handler:
        return False, f"Unknown integration: {integration_id}"

    auth_type = INTEGRATION_REGISTRY.get(integration_id, {}).get("auth_type", "")

    if auth_type not in ("oauth", "both"):
        return False, f"OAuth not supported for {integration_id}"

    try:
        # For integrations with both OAuth and token, OAuth is via invite
        if auth_type == "both" and hasattr(handler, "invite"):
            return await handler.invite([])
        else:
            return await handler.login([])
    except Exception as e:
        logger.error(f"OAuth failed for {integration_id}: {e}")
        return False, f"OAuth failed: {str(e)}"


async def disconnect_integration(integration_id: str, account_id: Optional[str] = None) -> Tuple[bool, str]:
    """Disconnect an integration account.

    Args:
        integration_id: The integration to disconnect
        account_id: Optional specific account to disconnect

    Returns:
        (success, message) tuple
    """
    handler = _get_handler(integration_id)
    if not handler:
        return False, f"Unknown integration: {integration_id}"

    try:
        args = [account_id] if account_id else []
        return await handler.logout(args)
    except Exception as e:
        logger.error(f"Failed to disconnect {integration_id}: {e}")
        return False, f"Disconnect failed: {str(e)}"


async def connect_integration_interactive(integration_id: str) -> Tuple[bool, str]:
    """Start interactive connection flow (e.g. WhatsApp QR code scan).

    Args:
        integration_id: The integration to connect

    Returns:
        (success, message) tuple
    """
    handler = _get_handler(integration_id)
    if not handler:
        return False, f"Unknown integration: {integration_id}"

    auth_type = INTEGRATION_REGISTRY.get(integration_id, {}).get("auth_type", "")

    if auth_type not in ("interactive", "token_with_interactive"):
        return False, f"Interactive login not supported for {integration_id}"

    try:
        if hasattr(handler, "handle"):
            # Prefer "login-qr" for handlers that support it, fall back to "login"
            subs = getattr(handler, "subcommands", [])
            sub = "login-qr" if "login-qr" in subs else "login"
            return await handler.handle(sub, [])
        return await handler.login([])
    except Exception as e:
        logger.error(f"Interactive login failed for {integration_id}: {e}")
        return False, f"Connection failed: {str(e)}"


def get_integration_auth_type(integration_id: str) -> str:
    """Get the auth type for an integration."""
    return INTEGRATION_REGISTRY.get(integration_id, {}).get("auth_type", "token")


def get_integration_fields(integration_id: str) -> List[Dict[str, Any]]:
    """Get the input fields for token-based auth."""
    return INTEGRATION_REGISTRY.get(integration_id, {}).get("fields", [])
