# -*- coding: utf-8 -*-
"""
Context engine for CraftBot.

Re-exports ContextEngine from agent_core. CraftBot doesn't use the
WCA-specific conversation hooks (get_conversation_history, get_chat_target_info,
get_user_info), so they return empty strings by default.
"""

from agent_core.core.impl.context import ContextEngine

__all__ = ["ContextEngine"]
