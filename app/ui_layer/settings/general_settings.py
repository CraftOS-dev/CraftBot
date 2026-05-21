"""General settings management for UI layer.

Provides functions for managing general application settings that can be
used by any interface adapter (Browser, TUI, CLI).
"""

from pathlib import Path
from typing import Dict, Any, Optional
import shutil
import time

from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    APP_DATA_PATH,
)


# ─────────────────────────────────────────────────────────────────────
# Agent Profile Picture
# ─────────────────────────────────────────────────────────────────────

AGENT_PROFILE_DIR = APP_DATA_PATH / "agent_profile"
AGENT_PROFILE_DEFAULT_FILENAME = "default.png"
AGENT_PROFILE_BASENAME = "picture"
ALLOWED_PROFILE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
PROFILE_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}
MAX_PROFILE_PICTURE_BYTES = 5 * 1024 * 1024  # 5 MB


def _user_profile_picture_path(ext: str) -> Path:
    return AGENT_PROFILE_DIR / f"{AGENT_PROFILE_BASENAME}.{ext}"


def _find_existing_user_picture() -> Optional[Path]:
    """Return the path of the currently-stored user picture if any."""
    if not AGENT_PROFILE_DIR.exists():
        return None
    for ext in ALLOWED_PROFILE_EXTS:
        path = _user_profile_picture_path(ext)
        if path.exists():
            return path
    return None


def _remove_all_user_pictures() -> None:
    """Delete every `picture.*` file in the profile directory."""
    if not AGENT_PROFILE_DIR.exists():
        return
    for ext in ALLOWED_PROFILE_EXTS:
        path = _user_profile_picture_path(ext)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def get_agent_profile_picture_info() -> Dict[str, Any]:
    """Get the current profile picture URL and whether it is a custom upload."""
    from app.onboarding import onboarding_manager

    ext = onboarding_manager.state.agent_profile_picture
    path = _user_profile_picture_path(ext) if ext else None
    if path and path.exists():
        mtime = int(path.stat().st_mtime)
        return {
            "url": f"/api/agent-profile-picture?v={mtime}",
            "has_custom": True,
        }
    return {
        "url": "/api/agent-profile-picture?v=default",
        "has_custom": False,
    }


def save_agent_profile_picture(
    ext: str,
    raw_bytes: bytes,
) -> Dict[str, Any]:
    """Persist a user-uploaded agent profile picture.

    Replaces any existing user picture on disk and updates the onboarding
    state so the new extension is known on future restarts.
    """
    from app.onboarding import onboarding_manager

    ext = ext.lower().lstrip(".")
    if ext not in ALLOWED_PROFILE_EXTS:
        return {
            "success": False,
            "error": f"Unsupported image type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_PROFILE_EXTS))}",
        }
    if len(raw_bytes) > MAX_PROFILE_PICTURE_BYTES:
        return {
            "success": False,
            "error": f"Image too large (max {MAX_PROFILE_PICTURE_BYTES // (1024 * 1024)} MB)",
        }
    if not raw_bytes:
        return {"success": False, "error": "Empty image payload"}

    try:
        AGENT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        # Ensure exactly one picture.* exists after the write.
        _remove_all_user_pictures()
        target = _user_profile_picture_path(ext)
        target.write_bytes(raw_bytes)

        onboarding_manager.state.agent_profile_picture = ext
        onboarding_manager.save()

        mtime = int(target.stat().st_mtime)
        return {
            "success": True,
            "url": f"/api/agent-profile-picture?v={mtime}",
            "has_custom": True,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to save profile picture: {str(e)}",
        }


def remove_agent_profile_picture() -> Dict[str, Any]:
    """Delete any custom profile picture and revert to the bundled default."""
    from app.onboarding import onboarding_manager

    try:
        _remove_all_user_pictures()
        onboarding_manager.state.agent_profile_picture = None
        onboarding_manager.save()
        return {
            "success": True,
            "url": f"/api/agent-profile-picture?v=default&t={int(time.time())}",
            "has_custom": False,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to remove profile picture: {str(e)}",
        }


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
    allowed_files = {
        "USER.md",
        "AGENT.md",
        "SOUL.md",
        "MEMORY.md",
        "PROACTIVE.md",
        "GLOBAL_LIVING_UI.md",
    }
    if filename not in allowed_files:
        return {
            "success": False,
            "error": f"Invalid filename. Allowed files: {', '.join(allowed_files)}",
        }

    file_path = AGENT_FILE_SYSTEM_PATH / filename

    try:
        if not file_path.exists():
            # Try to copy from template
            template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / filename
            if template_path.exists():
                shutil.copy(template_path, file_path)
            else:
                return {"success": False, "error": f"File not found: {filename}"}

        content = file_path.read_text(encoding="utf-8")
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": f"Failed to read {filename}: {str(e)}"}


def write_agent_file(filename: str, content: str) -> Dict[str, Any]:
    """Write content to an agent file.

    Args:
        filename: The filename to write (e.g., "USER.md", "AGENT.md")
        content: The content to write

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    # Validate filename to prevent directory traversal
    allowed_files = {"USER.md", "AGENT.md", "SOUL.md", "GLOBAL_LIVING_UI.md"}
    if filename not in allowed_files:
        return {
            "success": False,
            "error": f"Invalid filename for writing. Allowed files: {', '.join(allowed_files)}",
        }

    file_path = AGENT_FILE_SYSTEM_PATH / filename

    try:
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding="utf-8")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"Failed to write {filename}: {str(e)}"}


def restore_agent_file(filename: str) -> Dict[str, Any]:
    """Restore an agent file from its template.

    Args:
        filename: The filename to restore (e.g., "USER.md", "AGENT.md")

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    # Validate filename
    allowed_files = {
        "USER.md",
        "AGENT.md",
        "SOUL.md",
        "PROACTIVE.md",
        "GLOBAL_LIVING_UI.md",
    }
    if filename not in allowed_files:
        return {
            "success": False,
            "error": f"Invalid filename for restore. Allowed files: {', '.join(allowed_files)}",
        }

    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / filename
    target_path = AGENT_FILE_SYSTEM_PATH / filename

    try:
        if not template_path.exists():
            return {"success": False, "error": f"Template not found for: {filename}"}

        # Copy template to target
        shutil.copy(template_path, target_path)

        # Read and return the restored content
        content = target_path.read_text(encoding="utf-8")
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": f"Failed to restore {filename}: {str(e)}"}


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

        return {"success": True, "message": "Agent state has been reset."}
    except Exception as e:
        return {"success": False, "error": f"Failed to reset agent state: {str(e)}"}


# ─────────────────────────────────────────────────────────────────────
# Settings Persistence
# ─────────────────────────────────────────────────────────────────────


def get_general_settings() -> Dict[str, Any]:
    """Get general application settings.

    Returns:
        Dict containing current settings
    """
    from app.onboarding import onboarding_manager

    picture_info = get_agent_profile_picture_info()

    return {
        "agent_name": onboarding_manager.state.agent_name or "Agent",
        "agent_profile_picture_url": picture_info["url"],
        "agent_profile_picture_has_custom": picture_info["has_custom"],
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
        return {"success": False, "error": f"Failed to update settings: {str(e)}"}
