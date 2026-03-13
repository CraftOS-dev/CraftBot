"""Credential TUI command functions. Returns tuple[bool, str] like mcp_settings.py."""
from __future__ import annotations
from typing import Tuple

from app.credentials.handlers import INTEGRATION_HANDLERS, LOCAL_USER_ID


def list_all_credentials() -> Tuple[bool, str]:
    """List all stored credentials across integrations."""
    lines = ["Stored Credentials:", ""]
    found = False
    for name, handler in INTEGRATION_HANDLERS.items():
        try:
            _, msg = __import__("asyncio").get_event_loop().run_until_complete(handler.status())
            first_line = msg.split("\n")[0]
            if "Not connected" not in first_line and "No " not in first_line:
                found = True
                lines.append(f"  {msg}")
        except Exception:
            pass
    if not found:
        return True, "No credentials stored. Use /<integration> login to connect."
    return True, "\n".join(lines)


def list_integrations() -> Tuple[bool, str]:
    """List available integration types."""
    lines = ["Available Integrations:", ""]
    for name in INTEGRATION_HANDLERS:
        lines.append(f"  /{name}")
    lines.append("\nUse '/<name> login' to connect, '/<name> status' to check.")
    return True, "\n".join(lines)
