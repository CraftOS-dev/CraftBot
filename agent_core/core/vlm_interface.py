# -*- coding: utf-8 -*-
"""
VLM (Vision Language Model) interface.

This module re-exports VLMInterface from the impl module for backward compatibility.
The implementation in agent_core.core.impl.vlm supports hook-based customization
for state access and usage reporting.

For most uses, prefer importing from the impl module directly or using the
runtime-specific wrappers (CraftBot/core/vlm_interface.py or
CraftBot/core/vlm_interface.py) which configure the appropriate hooks.
"""

from agent_core.core.impl.vlm import VLMInterface

__all__ = ["VLMInterface"]
