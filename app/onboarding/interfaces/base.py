# -*- coding: utf-8 -*-
"""
Abstract base interface for onboarding implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class OnboardingInterface(ABC):
    """
    Abstract interface for onboarding implementations.

    Any UI (TUI, browser, future interfaces) can implement this
    to provide their own onboarding experience while using the
    shared onboarding logic.

    Example implementation:
        class TUIOnboarding(OnboardingInterface):
            async def run_hard_onboarding(self) -> Dict[str, Any]:
                # Show Textual wizard screens
                ...

            async def trigger_soft_onboarding(self) -> str:
                # Create interview task
                ...
    """

    @abstractmethod
    async def run_hard_onboarding(self) -> Dict[str, Any]:
        """
        Execute the hard onboarding flow (UI-driven wizard).

        This should present a multi-step wizard to collect:
        - LLM provider selection
        - API key input
        - User name (optional)
        - Agent name (optional)
        - MCP servers to enable (optional)
        - Skills to enable (optional)

        Returns:
            Dictionary containing all collected configuration:
            {
                "provider": str,        # LLM provider name (openai, gemini, etc.)
                "api_key": str,         # API key for the provider
                "user_name": str,       # User's preferred name
                "agent_name": str,      # Agent's given name
                "mcp_servers": list,    # List of enabled MCP server names
                "skills": list,         # List of enabled skill names
                "completed": bool,      # Whether onboarding completed (not cancelled)
            }
        """
        pass

    @abstractmethod
    async def trigger_soft_onboarding(self) -> Optional[str]:
        """
        Trigger soft onboarding (creates conversational interview task).

        This should create a task that will conduct a Q&A interview
        with the user to gather personality, preferences, and other
        information for USER.md and AGENT.md.

        Returns:
            Task ID of the created interview task, or None if creation failed.
        """
        pass

    @abstractmethod
    def is_hard_onboarding_complete(self) -> bool:
        """
        Check if hard onboarding has been completed.

        Returns:
            True if hard onboarding is complete, False otherwise.
        """
        pass

    @abstractmethod
    def is_soft_onboarding_complete(self) -> bool:
        """
        Check if soft onboarding has been completed.

        Returns:
            True if soft onboarding is complete, False otherwise.
        """
        pass

    def is_onboarding_complete(self) -> bool:
        """
        Check if all onboarding phases are complete.

        Returns:
            True if both hard and soft onboarding are complete.
        """
        return self.is_hard_onboarding_complete() and self.is_soft_onboarding_complete()
