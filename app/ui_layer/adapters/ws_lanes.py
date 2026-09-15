# -*- coding: utf-8 -*-
"""
Concurrency lanes for messages from one browser connection.

Messages used to be handled strictly one after another per connection, so a
single slow request (a model connection test, an update check, an app launch)
held up everything else from that tab. Each message now runs as its own task,
and only messages in the same lane wait for each other, in arrival order.

Lanes follow what handlers change: messages about the same chat session, the
same Agent App project or the same settings domain stay serialized, so their
read-modify-write handling never interleaves; unrelated domains run
concurrently. Unknown message types share one "general" lane, which keeps the
previous one-at-a-time behaviour for anything not classified here.
"""

from __future__ import annotations

from typing import Any, Mapping

# Messages about one chat session: serialized per session.
_SESSION_TYPES = frozenset(
    {
        "message",
        "command",
        "session_delete",
        "session_rename",
        "session_clear",
        "chat_history",
        "chat_attachment_upload",
        "option_click",
        "question_response",
    }
)

# Types with a lane of their own.
_TYPE_LANES = {
    # A stop must never wait behind other work for the same session.
    "session_stop": "session_stop",
    "session_list": "sessions",
    "enhance_prompt": "enhance",
    "check_update": "update",
    "do_update": "update",
    "playbook_list": "playbooks",
    "open_file": "os",
    "open_folder": "os",
    "command_list": "skills",
    "create_skill_from_session": "skills",
    "reset": "reset",
}

# Message-type prefix → lane; first match wins.
_PREFIX_LANES = (
    ("agent_app_", "agent_app"),
    ("file_", "workspace"),
    ("memory_", "memory"),
    ("skill_", "skills"),
    ("mcp_", "mcp"),
    ("integration_", "integrations"),
    ("whatsapp_", "integrations"),
    ("proactive_", "proactive"),
    ("scheduler_", "proactive"),
    ("model_", "model"),
    ("provider_", "model"),
    ("ollama_", "model"),
    ("openrouter_", "model"),
    ("slow_mode_", "model"),
    ("local_llm_", "local_llm"),
    ("onboarding_", "onboarding"),
    ("settings_", "settings"),
    ("agent_file_", "settings"),
    ("agent_profile_picture_", "settings"),
    ("dashboard_", "dashboard"),
    ("subscribe_dashboard_", "dashboard"),
    ("unsubscribe_dashboard_", "dashboard"),
)

GENERAL_LANE = "general"


def message_lane(message: Mapping[str, Any]) -> str:
    """The lane a browser message runs in (see module docstring)."""
    msg_type = str(message.get("type") or "")
    if msg_type in _SESSION_TYPES:
        return f"session:{message.get('sessionId') or 'main'}"
    if msg_type in _TYPE_LANES:
        return _TYPE_LANES[msg_type]
    for prefix, lane in _PREFIX_LANES:
        if msg_type.startswith(prefix):
            project_id = message.get("projectId")
            if lane == "agent_app" and project_id:
                return f"agent_app:{project_id}"
            return lane
    return GENERAL_LANE
