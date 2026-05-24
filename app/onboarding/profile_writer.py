# -*- coding: utf-8 -*-
"""
Shared utility to write user profile data to USER.md.

Used by all onboarding completion handlers (CLI, Browser controller)
to populate USER.md with data collected during hard onboarding.
"""

import re
from typing import Any, Dict
import shutil

from app.logger import logger


def write_profile_to_user_md(profile_data: Dict[str, Any]) -> bool:
    """
    Write user profile data collected during hard onboarding to USER.md.

    Updates Identity, Communication Preferences, and Agent Interaction
    sections. Infers timezone from location using tzlocal.

    Args:
        profile_data: Dict with keys: user_name, location, language,
                      tone, proactivity, approval, messaging_platform

    Returns:
        True if successfully written, False otherwise.
    """
    if not profile_data:
        return False

    try:
        from app.config import AGENT_FILE_SYSTEM_PATH, AGENT_FILE_SYSTEM_TEMPLATE_PATH

        filename: str = "USER.md"
        user_md_path = AGENT_FILE_SYSTEM_PATH / filename
        if not user_md_path.exists():
            # Try to copy from template
            template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / filename
            if template_path.exists():
                shutil.copy(template_path, user_md_path)
            else:
                logger.warning("[PROFILE] USER.md not found, skipping profile write")
                return False

        content = user_md_path.read_text(encoding="utf-8")

        user_name = profile_data.get("user_name", "").strip()
        location = profile_data.get("location", "").strip()
        language = profile_data.get("language", "").strip()
        tone = profile_data.get("tone", "").strip()
        proactivity = profile_data.get("proactivity", "").strip()
        approval = profile_data.get("approval", [])
        messaging_platform = profile_data.get("messaging_platform", "").strip()

        # Infer timezone from system
        timezone_str = _infer_timezone()

        # --- Identity section ---
        if user_name:
            content = _replace_field(content, "Full Name", user_name)
            content = _replace_field(content, "Preferred Name", user_name)

        if location:
            content = _replace_field(content, "Location", location)

        if timezone_str:
            content = _replace_field(content, "Timezone", timezone_str)

        # --- Communication Preferences section ---
        if language:
            content = _replace_field(content, "Language", language)

        if tone:
            content = _replace_field(content, "Preferred Tone", tone)

        if messaging_platform:
            content = _replace_field(
                content, "Preferred Messaging Platform", messaging_platform
            )

        # --- Agent Interaction section ---
        if proactivity:
            content = _replace_field(
                content, "Prefer Proactive Assistance", proactivity
            )

        if isinstance(approval, list) and approval:
            approval_str = _format_approval(approval)
            content = _replace_field(content, "Approval Required For", approval_str)

        user_md_path.write_text(content, encoding="utf-8")
        logger.info("[PROFILE] Successfully wrote user profile to USER.md")
        return True

    except Exception as e:
        logger.error(f"[PROFILE] Failed to write profile to USER.md: {e}")
        return False


def _replace_field(content: str, field_name: str, value: str) -> str:
    """Replace a markdown bold field value in USER.md.

    Matches patterns like: - **Field Name:** <anything until end of line>
    """
    pattern = rf"(\*\*{re.escape(field_name)}:\*\*\s*).*"
    replacement = rf"\1{value}"
    return re.sub(pattern, replacement, content)


APPROVAL_DESCRIPTIONS = {
    "messages": "Ask before sending messages or notifications on user's behalf",
    "scheduling": "Ask before creating, modifying, or deleting schedules and calendar events",
    "file_changes": "Ask before creating, modifying, or deleting files on the user's system",
    "purchases": "Ask before making any purchases, payments, or financial transactions",
    "all": "Ask for explicit approval before taking any action",
}


def _format_approval(approval: list) -> str:
    """Convert approval keys to descriptive sentences for the agent."""
    if "all" in approval:
        return APPROVAL_DESCRIPTIONS["all"]
    descriptions = [APPROVAL_DESCRIPTIONS.get(key, key) for key in approval]
    return "; ".join(descriptions)


def _infer_timezone() -> str:
    """Infer timezone from system using tzlocal."""
    try:
        from tzlocal import get_localzone

        tz = get_localzone()
        return str(tz)
    except Exception:
        return ""


# Mirrors PLATFORM_OPTIONS in app/onboarding/interfaces/steps.py — the value
# written to USER.md is the stored key (e.g. "craftbot"); callers need the
# runtime display string (e.g. "CraftBot Interface").
DEFAULT_PREFERRED_PLATFORM = "CraftBot Interface"
_PLATFORM_NORMALIZATION = {
    "craftbot": "CraftBot Interface",
    "craftbot interface": "CraftBot Interface",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "discord": "Discord",
    "slack": "Slack",
}


def read_preferred_messaging_platform() -> str:
    """Return the user's Preferred Messaging Platform from USER.md.

    Defaults to "CraftBot Interface" when the field is missing, empty, or still
    holds the placeholder text — so callers can rely on a usable value.
    """
    try:
        from app.config import AGENT_FILE_SYSTEM_PATH

        user_md_path = AGENT_FILE_SYSTEM_PATH / "USER.md"
        if not user_md_path.exists():
            return DEFAULT_PREFERRED_PLATFORM

        content = user_md_path.read_text(encoding="utf-8")
        match = re.search(r"\*\*Preferred Messaging Platform:\*\*\s*(.*)", content)
        if not match:
            return DEFAULT_PREFERRED_PLATFORM

        value = match.group(1).strip()
        if not value or value.startswith("(Ask the users"):
            return DEFAULT_PREFERRED_PLATFORM

        return _PLATFORM_NORMALIZATION.get(value.lower(), value)
    except Exception as e:
        logger.warning(f"[PROFILE] Failed to read preferred platform from USER.md: {e}")
        return DEFAULT_PREFERRED_PLATFORM
