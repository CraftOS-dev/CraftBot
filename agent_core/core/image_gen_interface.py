# -*- coding: utf-8 -*-
"""
Image generation interface.

Re-exports ImageGenInterface from the impl module for backward compatibility.
Use the runtime-specific wrapper (app/image_gen_interface.py) when running
inside CraftBot — it injects the appropriate state and usage hooks.
"""

from agent_core.core.impl.image_gen import ImageGenInterface

__all__ = ["ImageGenInterface"]
