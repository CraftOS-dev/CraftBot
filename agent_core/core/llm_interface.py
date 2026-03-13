# -*- coding: utf-8 -*-
"""
LLM (Large Language Model) interface.

This module re-exports LLMInterface from the impl module for backward compatibility.
The implementation in agent_core.core.impl.llm supports hook-based customization
for state access and usage reporting.

For most uses, prefer importing from the impl module directly or using the
runtime-specific wrappers (CraftBot/app/llm/interface.py or
CraftBot/app/llm/interface.py) which configure the appropriate hooks.
"""

from agent_core.core.impl.llm import LLMInterface, LLMCallType

__all__ = ["LLMInterface", "LLMCallType"]
