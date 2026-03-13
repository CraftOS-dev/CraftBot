"""Integration settings management — shared by browser and TUI frontends."""
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
        "auth_type": "token_with_interactive",
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


PLATFORM_MAP = {
    "whatsapp": ["whatsapp_web"],
    "telegram": ["telegram_bot", "telegram_user"],
    "google": ["google_workspace"],
}


async def _start_platform_listener(integration_id: str) -> None:
    """Start the external comms listener for a newly connected platform."""
    try:
        from app.external_comms.manager import get_external_comms_manager
        manager = get_external_comms_manager()
        if manager:
            platform_ids = PLATFORM_MAP.get(integration_id, [integration_id])
            for platform_id in platform_ids:
                await manager.start_platform(platform_id)
    except Exception as e:
        logger.warning(f"Failed to start listener for {integration_id}: {e}")


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
        success, message = await handler.login(args)
        if success:
            await _start_platform_listener(integration_id)
        return success, message
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
            success, message = await handler.invite([])
        else:
            success, message = await handler.login([])
        if success:
            await _start_platform_listener(integration_id)
        return success, message
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
            success, message = await handler.handle(sub, [])
        else:
            success, message = await handler.login([])
        if success:
            await _start_platform_listener(integration_id)
        return success, message
    except Exception as e:
        logger.error(f"Interactive login failed for {integration_id}: {e}")
        return False, f"Connection failed: {str(e)}"


def get_integration_auth_type(integration_id: str) -> str:
    """Get the auth type for an integration."""
    return INTEGRATION_REGISTRY.get(integration_id, {}).get("auth_type", "token")


def get_integration_fields(integration_id: str) -> List[Dict[str, Any]]:
    """Get the input fields for token-based auth."""
    return INTEGRATION_REGISTRY.get(integration_id, {}).get("fields", [])


# =====================
# WhatsApp QR Code Flow
# =====================

# Store active WhatsApp bridge sessions for QR code flow
_whatsapp_sessions: Dict[str, Any] = {}


async def start_whatsapp_qr_session() -> Dict[str, Any]:
    """Start the WhatsApp bridge and return QR code data.

    Uses the whatsapp-web.js Node bridge so that the QR scan authenticates
    the same session used for message listening.

    Returns dict with:
    - success: bool
    - session_id: str (if success)
    - qr_code: str (base64 image data, if available)
    - status: str (qr_ready, connected, error, etc.)
    - message: str (error or status message)
    """
    global _whatsapp_sessions

    try:
        from app.external_comms.platforms.whatsapp_bridge.client import get_whatsapp_bridge
    except ImportError:
        return {
            "success": False,
            "status": "error",
            "message": "WhatsApp bridge not available. Ensure Node.js >= 18 is installed.",
        }

    try:
        bridge = get_whatsapp_bridge()

        # Start bridge if not already running
        if not bridge.is_running:
            await bridge.start()

        # Wait for either QR code or ready (already authenticated)
        event_type, event_data = await bridge.wait_for_qr_or_ready(timeout=60.0)

        if event_type == "ready":
            # Already authenticated — save credential and report connected
            from app.external_comms.platforms.whatsapp_web import WhatsAppWebCredential, CREDENTIAL_FILE
            from app.external_comms.credentials import save_credential

            owner_phone = bridge.owner_phone or ""
            owner_name = bridge.owner_name or ""
            save_credential(CREDENTIAL_FILE, WhatsAppWebCredential(
                session_id="bridge",
                owner_phone=owner_phone,
                owner_name=owner_name,
            ))
            await bridge.stop()

            display = owner_phone or owner_name or "connected"
            return {
                "success": True,
                "session_id": "bridge",
                "qr_code": "",
                "status": "connected",
                "message": f"WhatsApp already connected: +{display}",
            }

        if event_type == "qr":
            # Generate QR code image from the QR string
            qr_data = (event_data or {}).get("qr_data_url", "")

            # If bridge didn't provide a data URL, generate one from the QR string
            if not qr_data:
                qr_string = (event_data or {}).get("qr_string", "")
                if qr_string:
                    try:
                        import qrcode
                        import io
                        import base64
                        qr = qrcode.QRCode(border=1)
                        qr.add_data(qr_string)
                        qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white")
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        qr_data = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
                    except Exception as e:
                        logger.warning(f"Failed to generate QR image: {e}")

            if not qr_data:
                await bridge.stop()
                return {
                    "success": False,
                    "status": "error",
                    "message": "Failed to generate QR code.",
                }

            # Ensure it's a proper data URL
            if qr_data and not qr_data.startswith("data:"):
                qr_data = f"data:image/png;base64,{qr_data}"

            # Store bridge reference for status polling
            session_id = "bridge"
            _whatsapp_sessions[session_id] = bridge

            return {
                "success": True,
                "session_id": session_id,
                "qr_code": qr_data,
                "status": "qr_ready",
                "message": "Scan the QR code with your WhatsApp mobile app",
            }

        # Timeout
        await bridge.stop()
        return {
            "success": False,
            "status": "error",
            "message": "Timed out waiting for WhatsApp bridge.",
        }

    except Exception as e:
        logger.error(f"Failed to start WhatsApp session: {e}")
        return {
            "success": False,
            "status": "error",
            "message": f"Failed to start session: {str(e)}",
        }


async def check_whatsapp_session_status(session_id: str) -> Dict[str, Any]:
    """Check the status of a WhatsApp bridge QR session.

    Returns dict with:
    - success: bool
    - status: str (qr_ready, connected, error, disconnected)
    - connected: bool
    - message: str
    """
    global _whatsapp_sessions

    bridge = _whatsapp_sessions.get(session_id)
    if bridge is None:
        return {
            "success": False,
            "status": "error",
            "connected": False,
            "message": "Session not found. Please start a new session.",
        }

    try:
        if bridge.is_ready:
            # Bridge authenticated — save credential, stop bridge, start listener
            try:
                from app.external_comms.platforms.whatsapp_web import WhatsAppWebCredential, CREDENTIAL_FILE
                from app.external_comms.credentials import save_credential

                owner_phone = bridge.owner_phone or ""
                owner_name = bridge.owner_name or ""
                save_credential(CREDENTIAL_FILE, WhatsAppWebCredential(
                    session_id="bridge",
                    owner_phone=owner_phone,
                    owner_name=owner_name,
                ))

                # Clean up stored session and stop bridge
                # (start_platform will restart it on the main event loop)
                del _whatsapp_sessions[session_id]
                await bridge.stop()

                # Start the WhatsApp listener
                await _start_platform_listener("whatsapp")

                display = owner_phone or owner_name or "connected"
                return {
                    "success": True,
                    "status": "connected",
                    "connected": True,
                    "message": f"WhatsApp connected: +{display}",
                }
            except Exception as e:
                logger.error(f"Failed to store WhatsApp credential: {e}")
                return {
                    "success": False,
                    "status": "error",
                    "connected": False,
                    "message": f"Connected but failed to save: {str(e)}",
                }

        elif not bridge.is_running:
            # Bridge crashed or stopped
            if session_id in _whatsapp_sessions:
                del _whatsapp_sessions[session_id]
            return {
                "success": False,
                "status": "error",
                "connected": False,
                "message": "WhatsApp bridge stopped unexpectedly. Please try again.",
            }

        else:
            # Still waiting for QR scan
            return {
                "success": True,
                "status": "qr_ready",
                "connected": False,
                "message": "Waiting for QR code scan...",
            }

    except Exception as e:
        logger.error(f"Failed to check WhatsApp session status: {e}")
        return {
            "success": False,
            "status": "error",
            "connected": False,
            "message": f"Status check failed: {str(e)}",
        }


def cancel_whatsapp_session(session_id: str) -> Dict[str, Any]:
    """Cancel a WhatsApp QR session and stop the bridge.

    Returns dict with:
    - success: bool
    - message: str
    """
    global _whatsapp_sessions

    bridge = _whatsapp_sessions.pop(session_id, None)
    if bridge is not None:
        # Stop the bridge in the background
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(bridge.stop())
            else:
                loop.run_until_complete(bridge.stop())
        except Exception:
            pass
        return {
            "success": True,
            "message": "Session cancelled.",
        }

    return {
        "success": True,
        "message": "Session not found or already cancelled.",
    }
