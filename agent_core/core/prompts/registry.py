# -*- coding: utf-8 -*-
"""
Prompt registry for agent_core.

This module provides a registry pattern for prompts that allows runtimes
to override specific prompts with their own versions.
"""

from typing import Dict, Optional
import threading


class PromptRegistry:
    """Registry for prompt overrides.

    This allows runtimes (CraftBot, CraftBot) to override specific
    prompts while using the shared defaults from agent_core.

    Usage:
        # In CraftBot startup:
        from agent_core.core.prompts import prompt_registry, ROUTE_TO_SESSION_PROMPT_WCA
        prompt_registry.register("ROUTE_TO_SESSION_PROMPT", ROUTE_TO_SESSION_PROMPT_WCA)

        # When accessing prompts:
        from agent_core.core.prompts import get_prompt
        prompt = get_prompt("ROUTE_TO_SESSION_PROMPT")  # Returns override if registered
    """

    _instance: Optional["PromptRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "PromptRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._overrides: Dict[str, str] = {}
        return cls._instance

    def register(self, name: str, prompt: str) -> None:
        """Register a prompt override.

        Args:
            name: The prompt name (e.g., "ROUTE_TO_SESSION_PROMPT")
            prompt: The prompt string to use instead of the default
        """
        self._overrides[name] = prompt

    def get(self, name: str, default: str) -> str:
        """Get a prompt, returning override if registered, otherwise default.

        Args:
            name: The prompt name
            default: The default prompt to return if no override exists

        Returns:
            The override prompt if registered, otherwise the default
        """
        return self._overrides.get(name, default)

    def has_override(self, name: str) -> bool:
        """Check if a prompt has an override registered.

        Args:
            name: The prompt name

        Returns:
            True if an override is registered
        """
        return name in self._overrides

    def clear(self) -> None:
        """Clear all registered overrides. Useful for testing."""
        self._overrides.clear()


# Global singleton instance
prompt_registry = PromptRegistry()


def get_prompt(name: str, default: str) -> str:
    """Convenience function to get a prompt from the registry.

    Args:
        name: The prompt name
        default: The default prompt if no override exists

    Returns:
        The prompt string
    """
    return prompt_registry.get(name, default)


def register_prompt(name: str, prompt: str) -> None:
    """Convenience function to register a prompt override.

    Args:
        name: The prompt name
        prompt: The prompt string
    """
    prompt_registry.register(name, prompt)


__all__ = [
    "PromptRegistry",
    "prompt_registry",
    "get_prompt",
    "register_prompt",
]
