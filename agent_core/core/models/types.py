# -*- coding: utf-8 -*-
"""
Model type definitions.

This module contains enums and types used for model interface selection.
"""

from enum import Enum


class InterfaceType(str, Enum):
    """
    Type of model interface.

    Used to specify which type of model interface to create:
    - LLM: Language model for text generation
    - VLM: Vision-language model for image understanding
    - EMBEDDING: Embedding model for vector representations
    """

    LLM = "llm"
    VLM = "vlm"
    EMBEDDING = "embedding"
