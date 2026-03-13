# -*- coding: utf-8 -*-
"""
Hard onboarding step definitions and implementations.

Each step represents one screen/phase in the hard onboarding wizard.
Steps are UI-agnostic - they define the data and validation logic,
not the presentation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
import os


@dataclass
class StepOption:
    """An option that can be selected in a step."""
    value: str          # Internal value (e.g., "openai")
    label: str          # Display label (e.g., "OpenAI")
    description: str = ""  # Optional description
    default: bool = False  # Whether this is the default selection
    icon: str = ""  # Lucide icon name (e.g., "Folder", "Search")
    requires_setup: bool = False  # Whether this option requires additional setup (API key, etc.)


@dataclass
class StepResult:
    """Result of completing an onboarding step."""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    skip_remaining: bool = False  # Skip all remaining steps


@runtime_checkable
class HardOnboardingStep(Protocol):
    """
    Protocol defining the interface for hard onboarding steps.

    Each step must provide:
    - Metadata (name, title, required status)
    - Options to choose from (if applicable)
    - Validation logic
    - Default value
    """

    @property
    def name(self) -> str:
        """Unique identifier for this step."""
        ...

    @property
    def title(self) -> str:
        """Display title for this step."""
        ...

    @property
    def description(self) -> str:
        """Description/instructions for this step."""
        ...

    @property
    def required(self) -> bool:
        """Whether this step must be completed."""
        ...

    def get_options(self) -> List[StepOption]:
        """Get available options for this step (empty if free-form input)."""
        ...

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validate user input for this step.

        Returns:
            Tuple of (is_valid, error_message)
        """
        ...

    def get_default(self) -> Any:
        """Get default value for this step."""
        ...


class ProviderStep:
    """LLM provider selection step."""

    name = "provider"
    title = "Select LLM Provider"
    description = "Choose which AI provider to use for the agent."
    required = True

    # Provider options with their display names
    PROVIDERS = [
        ("openai", "OpenAI", "GPT models"),
        ("gemini", "Google Gemini", "Gemini models"),
        ("byteplus", "BytePlus", "Kimi models"),
        ("anthropic", "Anthropic", "Claude models"),
        ("remote", "Ollama (Local)", "Self-hosted models"),
    ]

    def get_options(self) -> List[StepOption]:
        return [
            StepOption(
                value=provider_id,
                label=label,
                description=desc,
                default=(provider_id == "openai")
            )
            for provider_id, label, desc in self.PROVIDERS
        ]

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        valid_providers = [p[0] for p in self.PROVIDERS]
        if value in valid_providers:
            return True, None
        return False, f"Invalid provider. Choose from: {', '.join(valid_providers)}"

    def get_default(self) -> str:
        # Check environment variable for existing provider
        env_provider = os.environ.get("LLM_PROVIDER", "").lower()
        if env_provider and env_provider in [p[0] for p in self.PROVIDERS]:
            return env_provider
        return "openai"


class ApiKeyStep:
    """API key input step."""

    name = "api_key"
    title = "Enter API Key"
    description = "Enter your API key for the selected provider."
    required = True

    # Maps provider to environment variable name
    PROVIDER_ENV_VARS = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "byteplus": "BYTEPLUS_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "remote": None,  # Ollama doesn't need API key
    }

    def __init__(self, provider: str = "openai"):
        self.provider = provider

    def get_options(self) -> List[StepOption]:
        # Free-form input, no options
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        # Remote (Ollama) doesn't need API key
        if self.provider == "remote":
            return True, None

        if not value or not isinstance(value, str):
            return False, "API key is required"

        if len(value.strip()) < 10:
            return False, "API key seems too short"

        return True, None

    def get_default(self) -> str:
        # Check environment variable for existing key
        env_var = self.PROVIDER_ENV_VARS.get(self.provider)
        if env_var:
            return os.environ.get(env_var, "")
        return ""

    def get_env_var_name(self) -> Optional[str]:
        """Get the environment variable name for the current provider."""
        return self.PROVIDER_ENV_VARS.get(self.provider)


class AgentNameStep:
    """Agent name configuration step."""

    name = "agent_name"
    title = "Agent Name"
    description = "Give your agent a name (optional)"
    required = False

    def get_options(self) -> List[StepOption]:
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        # Optional, any string is valid
        return True, None

    def get_default(self) -> str:
        return "CraftBot"


class MCPStep:
    """MCP server selection step."""

    name = "mcp"
    title = "Recommended MCP Servers"
    description = "MCP servers are your agent's toolbox. Each one adds extra tools that let your agent work with apps like Gmail, Slack, or Notion on your behalf.\nItems marked 'Setup required' need API keys - configure them in Settings after onboarding."
    required = False

    # Top 10 recommended MCP servers for onboarding (most popular/useful)
    # Names must match exactly with names in mcp_config.json
    # Format: {name: (icon, requires_setup)}
    RECOMMENDED_SERVERS = {
        "filesystem": ("Folder", False),           # Local file access - works out of the box
        "brave-search": ("Search", True),          # Web search - needs BRAVE_API_KEY
        "github": ("Github", True),                # Git/GitHub - needs GITHUB_PERSONAL_ACCESS_TOKEN
        "playwright-mcp": ("Globe", False),        # Browser automation - works out of the box
        "notion-mcp": ("FileText", True),          # Note-taking - needs NOTION_API_KEY
        "slack-mcp": ("MessageSquare", True),      # Team communication - needs Slack OAuth
        "gmail-mcp": ("Mail", True),               # Email - needs Google OAuth
        "google-calendar-mcp": ("Calendar", True), # Calendar - needs Google OAuth
        "todoist-mcp": ("CheckSquare", True),      # Task management - needs TODOIST_API_KEY
        "obsidian-mcp": ("Gem", True),             # Knowledge management - needs Obsidian plugin
    }

    def get_options(self) -> List[StepOption]:
        """Get top 10 recommended MCP servers for onboarding."""
        try:
            from app.tui.mcp_settings import list_mcp_servers
            servers = list_mcp_servers()

            # Create a lookup by name
            server_lookup = {s["name"]: s for s in servers}

            # Return only recommended servers that exist in config
            options = []
            for name, (icon, requires_setup) in self.RECOMMENDED_SERVERS.items():
                if name in server_lookup:
                    server = server_lookup[name]
                    label = server["name"].replace("-", " ").replace(" mcp", "").title()
                    options.append(StepOption(
                        value=server["name"],
                        label=label,
                        description=server.get("description", f"MCP server: {server['name']}"),
                        default=server.get("enabled", False),
                        icon=icon,
                        requires_setup=requires_setup
                    ))
            return options
        except ImportError:
            return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        # Value should be a list of server names
        if not isinstance(value, list):
            return False, "Expected a list of server names"
        return True, None

    def get_default(self) -> List[str]:
        return []


class SkillsStep:
    """Skills selection step."""

    name = "skills"
    title = "Recommended Skills"
    description = "Skills teach your agent how to do specific tasks step-by-step. When you ask for help, your agent loads the right skill and follows its instructions to complete the task properly.\nItems marked 'Setup required' need their corresponding MCP server configured first."
    required = False

    # Top 10 recommended skills for onboarding (most popular/useful)
    # Format: {name: icon}
    RECOMMENDED_SKILLS = {
        "research-assistant": "FlaskConical",
        "writing-assistant": "Pencil",
        "task-planner": "ClipboardList",
        "brave-search": "Search",
        "gmail": "Mail",
        "google-drive": "Cloud",
        "notion": "FileText",
        "obsidian": "Gem",
        "github": "Github",
        "google-sheets": "Sheet",
    }

    def get_options(self) -> List[StepOption]:
        """Get top 10 recommended skills for onboarding."""
        try:
            from app.tui.skill_settings import list_skills
            skills = list_skills()

            # Create a lookup by name (only user-invocable skills)
            skill_lookup = {
                s["name"]: s for s in skills
                if s.get("user_invocable", True)
            }

            # Return only recommended skills that exist
            options = []
            for name, icon in self.RECOMMENDED_SKILLS.items():
                if name in skill_lookup:
                    skill = skill_lookup[name]
                    options.append(StepOption(
                        value=skill["name"],
                        label=skill['name'].replace('-', ' ').title(),
                        description=skill.get("description", ""),
                        default=skill.get("enabled", False),
                        icon=icon
                    ))
            return options
        except ImportError:
            return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        # Value should be a list of skill names
        if not isinstance(value, list):
            return False, "Expected a list of skill names"
        return True, None

    def get_default(self) -> List[str]:
        return []


# Ordered list of all step classes
ALL_STEPS = [
    ProviderStep,
    ApiKeyStep,
    AgentNameStep,
    MCPStep,
    SkillsStep,
]
