"""General settings management for UI layer.

Provides functions for managing general application settings that can be
used by any interface adapter (Browser, TUI, CLI).
"""

from pathlib import Path
from typing import Dict, Any, Optional
import shutil

from app.config import AGENT_FILE_SYSTEM_PATH, AGENT_FILE_SYSTEM_TEMPLATE_PATH


# ─────────────────────────────────────────────────────────────────────
# Agent File Operations
# ─────────────────────────────────────────────────────────────────────

def read_agent_file(filename: str) -> Dict[str, Any]:
    """Read an agent file (USER.md, AGENT.md, etc.).

    Args:
        filename: The filename to read (e.g., "USER.md", "AGENT.md")

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    # Validate filename to prevent directory traversal
    allowed_files = {"USER.md", "AGENT.md", "MEMORY.md", "PROACTIVE.md"}
    if filename not in allowed_files:
        return {
            "success": False,
            "error": f"Invalid filename. Allowed files: {', '.join(allowed_files)}"
        }

    file_path = AGENT_FILE_SYSTEM_PATH / filename

    try:
        if not file_path.exists():
            # Try to copy from template
            template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / filename
            if template_path.exists():
                shutil.copy(template_path, file_path)
            else:
                return {
                    "success": False,
                    "error": f"File not found: {filename}"
                }

        content = file_path.read_text(encoding="utf-8")
        return {
            "success": True,
            "content": content
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read {filename}: {str(e)}"
        }


def write_agent_file(filename: str, content: str) -> Dict[str, Any]:
    """Write content to an agent file.

    Args:
        filename: The filename to write (e.g., "USER.md", "AGENT.md")
        content: The content to write

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    # Validate filename to prevent directory traversal
    allowed_files = {"USER.md", "AGENT.md"}
    if filename not in allowed_files:
        return {
            "success": False,
            "error": f"Invalid filename for writing. Allowed files: {', '.join(allowed_files)}"
        }

    file_path = AGENT_FILE_SYSTEM_PATH / filename

    try:
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding="utf-8")
        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write {filename}: {str(e)}"
        }


def restore_agent_file(filename: str) -> Dict[str, Any]:
    """Restore an agent file from its template.

    Args:
        filename: The filename to restore (e.g., "USER.md", "AGENT.md")

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    # Validate filename
    allowed_files = {"USER.md", "AGENT.md", "PROACTIVE.md"}
    if filename not in allowed_files:
        return {
            "success": False,
            "error": f"Invalid filename for restore. Allowed files: {', '.join(allowed_files)}"
        }

    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / filename
    target_path = AGENT_FILE_SYSTEM_PATH / filename

    try:
        if not template_path.exists():
            return {
                "success": False,
                "error": f"Template not found for: {filename}"
            }

        # Copy template to target
        shutil.copy(template_path, target_path)

        # Read and return the restored content
        content = target_path.read_text(encoding="utf-8")
        return {
            "success": True,
            "content": content
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to restore {filename}: {str(e)}"
        }


# ─────────────────────────────────────────────────────────────────────
# Reset Operations
# ─────────────────────────────────────────────────────────────────────

async def reset_agent_state(controller) -> Dict[str, Any]:
    """Reset the agent state.

    This is equivalent to the /reset command.

    Args:
        controller: The UIController instance

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    try:
        # Reset UI state
        controller.state_store.reset()

        # Reset agent state
        await controller.agent.reset_agent_state()

        return {
            "success": True,
            "message": "Agent state has been reset."
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to reset agent state: {str(e)}"
        }


# ─────────────────────────────────────────────────────────────────────
# Settings Persistence
# ─────────────────────────────────────────────────────────────────────

def get_general_settings() -> Dict[str, Any]:
    """Get general application settings.

    Returns:
        Dict containing current settings
    """
    from app.onboarding import onboarding_manager

    return {
        "agent_name": onboarding_manager.state.agent_name or "Agent",
        # Theme is handled client-side (stored in localStorage)
        # Add more settings here as needed
    }


def update_general_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Update general application settings.

    Args:
        settings: Dict of settings to update

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    from app.onboarding import onboarding_manager

    try:
        if "agent_name" in settings:
            onboarding_manager.state.agent_name = settings["agent_name"]
            onboarding_manager.save()

        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update settings: {str(e)}"
        }
