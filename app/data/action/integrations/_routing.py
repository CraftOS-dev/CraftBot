"""Host-side routing: which integration actions to expose to the agent's
conversation-mode loop, given which integrations currently have credentials.

This is a host concern — the package (``craftos_integrations``) only tells us
which platforms are connected. The choice of which @action-decorated function
names to surface for each platform is curation that lives here, alongside the
action files themselves.

If you add a new integration with new conversation-mode actions, add the
mapping below.
"""

from __future__ import annotations

from typing import Dict, List

from craftos_integrations import list_connected


# Per-platform list of action names to expose when the integration is connected.
# Keys are platform_ids (the same string handlers expose as ``handler.spec.platform_id``).
PLATFORM_CONVERSATION_ACTIONS: Dict[str, List[str]] = {
    "discord": ["send_discord_message", "send_discord_dm"],
    "lark": ["send_lark_message"],
    "slack": ["send_slack_message"],
    "telegram_bot": ["send_telegram_bot_message"],
    "telegram_user": ["send_telegram_user_message"],
    "whatsapp_business": ["send_whatsapp_web_text_message"],
    "whatsapp_web": ["send_whatsapp_web_text_message"],
}


def get_messaging_actions_for_connected() -> List[str]:
    """Action names to expose given current credential state. Deduped, order-preserving."""
    seen = set()
    out: List[str] = []
    for platform_id in list_connected():
        for name in PLATFORM_CONVERSATION_ACTIONS.get(platform_id, []):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out
