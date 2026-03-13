# -*- coding: utf-8 -*-
"""
app.external_comms.integration_discovery

Dynamic discovery of connected messaging integrations for action availability.
Used by the ActionRouter to dynamically expose messaging actions based on
which platforms have valid credentials.
"""

from typing import List, Dict

from agent_core.utils.logger import logger


# Maps platform client IDs to their messaging action sets
PLATFORM_TO_ACTION_SET: Dict[str, str] = {
    "telegram_bot": "telegram_bot",
    "telegram_user": "telegram_user",
    "whatsapp_web": "whatsapp",
    "whatsapp_business": "whatsapp",
    "discord": "discord",
    "slack": "slack",
}

# Maps action sets to their primary send actions for conversation mode
# These are the basic send message actions for each platform
ACTION_SET_SEND_ACTIONS: Dict[str, List[str]] = {
    "telegram_bot": ["send_telegram_bot_message"],
    "telegram_user": ["send_telegram_user_message"],
    "whatsapp": ["send_whatsapp_web_text_message"],
    "discord": ["send_discord_message", "send_discord_dm"],
    "slack": ["send_slack_message"],
}


def get_connected_messaging_platforms() -> List[str]:
    """
    Return list of platform IDs that have valid credentials.

    Dynamically discovers which messaging platforms are connected by checking
    credentials for each registered platform client.

    Returns:
        List of platform IDs (e.g., ["telegram_bot", "whatsapp_web", "discord"])
    """
    try:
        from app.external_comms.registry import get_all_clients

        connected = []
        all_clients = get_all_clients()

        for platform_id, client in all_clients.items():
            # Only include messaging platforms (those in our mapping)
            if platform_id in PLATFORM_TO_ACTION_SET:
                try:
                    if client.has_credentials():
                        connected.append(platform_id)
                        logger.debug(f"[DISCOVERY] Platform {platform_id} has credentials")
                except Exception as e:
                    logger.debug(f"[DISCOVERY] Error checking credentials for {platform_id}: {e}")

        return connected
    except Exception as e:
        logger.warning(f"[DISCOVERY] Failed to discover connected platforms: {e}")
        return []


def get_messaging_actions_for_platforms(platforms: List[str]) -> List[str]:
    """
    Return send_* action names for the specified connected platforms.

    Maps platform IDs to their corresponding action sets and returns
    the send message actions that should be available.

    Args:
        platforms: List of connected platform IDs

    Returns:
        List of action names (e.g., ["send_telegram_bot_message", "send_discord_message"])
    """
    # Get unique action sets from connected platforms
    action_sets = set()
    for platform_id in platforms:
        if platform_id in PLATFORM_TO_ACTION_SET:
            action_sets.add(PLATFORM_TO_ACTION_SET[platform_id])

    # Collect send actions from each action set
    actions = []
    for action_set in action_sets:
        if action_set in ACTION_SET_SEND_ACTIONS:
            actions.extend(ACTION_SET_SEND_ACTIONS[action_set])

    return actions


def get_connected_platforms_summary() -> str:
    """
    Get a human-readable summary of connected messaging platforms.

    Useful for inclusion in prompts to inform the agent which platforms
    are available for messaging.

    Returns:
        Formatted string listing connected platforms and their actions.
    """
    platforms = get_connected_messaging_platforms()
    if not platforms:
        return "No external messaging platforms connected."

    actions = get_messaging_actions_for_platforms(platforms)

    # Group by action set for cleaner display
    lines = ["Connected messaging platforms:"]

    action_sets_found = set()
    for platform_id in platforms:
        action_set = PLATFORM_TO_ACTION_SET.get(platform_id, platform_id)
        action_sets_found.add(action_set)

    for action_set in sorted(action_sets_found):
        set_actions = ACTION_SET_SEND_ACTIONS.get(action_set, [])
        available = [a for a in set_actions if a in actions]
        if available:
            lines.append(f"- {action_set}: {', '.join(available)}")

    return "\n".join(lines)
