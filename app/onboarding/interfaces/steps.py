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
class FormField:
    """A field in a multi-field form step (e.g., User Profile)."""
    name: str                                                   # Field key (e.g., "user_name")
    label: str                                                  # Display label
    field_type: str                                             # "text", "select", "multi_checkbox"
    options: List["StepOption"] = field(default_factory=list)   # For select/checkbox types
    default: Any = ""                                           # Default value
    placeholder: str = ""                                       # Hint text


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
        ("deepseek", "DeepSeek", "DeepSeek models"),
        ("grok", "Grok (xAI)", "Grok models"),
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
        # Check settings.json for existing provider
        from app.config import get_llm_provider
        current_provider = get_llm_provider().lower()
        if current_provider and current_provider in [p[0] for p in self.PROVIDERS]:
            return current_provider
        return "openai"


class ApiKeyStep:
    """API key input step — or Ollama connection setup for the remote provider."""

    name = "api_key"
    required = True

    # Maps provider to environment variable name
    PROVIDER_ENV_VARS = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "byteplus": "BYTEPLUS_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "grok": "XAI_API_KEY",
        "remote": None,  # Ollama uses a base URL, not an API key
    }

    def __init__(self, provider: str = "openai"):
        self.provider = provider

    @property
    def title(self) -> str:
        if self.provider == "remote":
            return "Connect Ollama"
        return "Enter API Key"

    @property
    def description(self) -> str:
        if self.provider == "remote":
            return (
                "Connect to your local Ollama instance.\n"
                "If Ollama isn't installed yet, we'll help you set it up."
            )
        return "Enter your API key for the selected provider."

    def get_options(self) -> List[StepOption]:
        # Free-form input, no options
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        if self.provider == "remote":
            # Value is the Ollama base URL
            if not value or not isinstance(value, str):
                return True, None  # Empty = use default URL
            v = value.strip()
            if not (v.startswith("http://") or v.startswith("https://")):
                return False, "Please enter a valid URL (e.g. http://localhost:11434)"
            return True, None

        if not value or not isinstance(value, str):
            return False, "API key is required"

        if len(value.strip()) < 10:
            return False, "API key seems too short"

        return True, None

    def get_default(self) -> str:
        if self.provider == "remote":
            return "http://localhost:11434"
        # Check settings.json for existing key
        from app.config import get_api_key
        return get_api_key(self.provider)

    def get_env_var_name(self) -> Optional[str]:
        """Get the environment variable name for the current provider."""
        return self.PROVIDER_ENV_VARS.get(self.provider)


class AgentNameStep:
    """Agent name + profile picture configuration step."""

    name = "agent_name"
    title = "Agent Identity"
    description = "Give your agent a name and an optional avatar."
    required = False

    ALLOWED_PICTURE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

    def get_form_fields(self) -> List[FormField]:
        return [
            FormField(
                name="agent_name",
                label="Agent Name",
                field_type="text",
                default="CraftBot",
                placeholder="Enter a name",
            ),
            FormField(
                name="agent_profile_picture",
                label="Avatar",
                field_type="image_upload",
                default="",
                placeholder="",
            ),
        ]

    def get_options(self) -> List[StepOption]:
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        # Accept legacy string submissions (plain text name) for backward compat.
        if isinstance(value, str):
            if len(value) > 20:
                return False, "Agent name must be 20 characters or fewer"
            return True, None
        if isinstance(value, dict):
            agent_name = value.get("agent_name")
            if agent_name and len(str(agent_name)) > 20:
                return False, "Agent name must be 20 characters or fewer"
            picture = value.get("agent_profile_picture")
            if picture not in (None, ""):
                if not isinstance(picture, str) or picture.lower() not in self.ALLOWED_PICTURE_EXTS:
                    return False, "Unsupported avatar format"
            return True, None
        return False, "Invalid agent identity submission"

    def get_default(self) -> Dict[str, Any]:
        return {
            "agent_name": "CraftBot",
            "agent_profile_picture": "",
        }


class UserProfileStep:
    """User profile form step — collects identity and preferences in a compact form."""

    name = "user_profile"
    title = "User Profile"
    description = "Tell us about yourself to personalize your experience."
    required = False

    TONE_OPTIONS = [
        ("casual", "Casual"),
        ("formal", "Formal"),
        ("friendly", "Friendly"),
        ("professional", "Professional"),
    ]

    PROACTIVITY_OPTIONS = [
        ("low", "Low", "Wait for instructions"),
        ("medium", "Medium", "Suggest when relevant"),
        ("high", "High", "Proactively suggest things"),
    ]

    APPROVAL_OPTIONS = [
        ("messages", "Messages", "Sending messages on your behalf"),
        ("scheduling", "Scheduling", "Creating/modifying schedules"),
        ("file_changes", "File Changes", "Modifying files on your system"),
        ("purchases", "Purchases", "Making purchases or payments"),
        ("all", "All Actions", "Ask approval for everything"),
    ]

    PLATFORM_OPTIONS = [
        ("telegram", "Telegram"),
        ("whatsapp", "WhatsApp"),
        ("discord", "Discord"),
        ("slack", "Slack"),
        ("tui", "CraftBot Interface"),
    ]

    @staticmethod
    def fetch_geolocation() -> str:
        """Fetch user's location from IP. Returns 'City, Country' or '' on failure."""
        try:
            import requests
            resp = requests.get("http://ip-api.com/json", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                city = data.get("city", "")
                country = data.get("country", "")
                if city and country:
                    return f"{city}, {country}"
                return country or city or ""
        except Exception:
            pass
        return ""

    @staticmethod
    def get_language_options() -> List[StepOption]:
        """Get a dynamic list of languages using babel. Pre-select based on OS locale."""
        try:
            from babel import Locale
            import locale as _locale

            # Get OS locale for pre-selection
            try:
                os_locale = _locale.getdefaultlocale()[0] or "en_US"
                os_lang = os_locale.split("_")[0]
            except Exception:
                os_lang = "en"

            # Get all language display names from babel (in English)
            lang_names = Locale("en").languages

            # Filter to commonly-used languages (those with 2-letter ISO codes)
            # and sort by display name
            seen = set()
            options = []
            for code, display_name in sorted(lang_names.items(), key=lambda x: x[1]):
                # Only include 2-letter codes (ISO 639-1) to keep list manageable
                if len(code) == 2 and code not in seen:
                    seen.add(code)
                    options.append(StepOption(
                        value=code,
                        label=display_name,
                        description=code,
                        default=(code == os_lang),
                    ))
            return options
        except ImportError:
            # Fallback if babel not installed — return a minimal list
            return [
                StepOption(value="en", label="English", description="en", default=True),
                StepOption(value="zh", label="Chinese", description="zh"),
                StepOption(value="es", label="Spanish", description="es"),
                StepOption(value="fr", label="French", description="fr"),
                StepOption(value="de", label="German", description="de"),
                StepOption(value="ja", label="Japanese", description="ja"),
                StepOption(value="ko", label="Korean", description="ko"),
                StepOption(value="pt", label="Portuguese", description="pt"),
                StepOption(value="ru", label="Russian", description="ru"),
                StepOption(value="ar", label="Arabic", description="ar"),
            ]

    def get_form_fields(self) -> List[FormField]:
        """Return all form fields for the user profile step."""
        # Fetch defaults
        try:
            location_default = self.fetch_geolocation()
        except Exception:
            location_default = ""

        language_options = self.get_language_options()

        # Find pre-selected language
        lang_default = "en"
        for opt in language_options:
            if opt.default:
                lang_default = opt.value
                break

        return [
            FormField(
                name="user_name",
                label="Your Name",
                field_type="text",
                placeholder="What should we call you?",
                default="",
            ),
            FormField(
                name="location",
                label="Location",
                field_type="text",
                placeholder="City, Country",
                default=location_default,
            ),
            FormField(
                name="language",
                label="CraftBot's Language",
                field_type="select",
                options=language_options,
                default=lang_default,
                placeholder="The language CraftBot will communicate in (not the interface language)",
            ),
            FormField(
                name="tone",
                label="Communication Tone",
                field_type="select",
                options=[
                    StepOption(value=val, label=label, default=(val == "casual"))
                    for val, label in self.TONE_OPTIONS
                ],
                default="casual",
            ),
            FormField(
                name="proactivity",
                label="Proactive Level",
                field_type="select",
                options=[
                    StepOption(value=val, label=label, description=desc, default=(val == "medium"))
                    for val, label, desc in self.PROACTIVITY_OPTIONS
                ],
                default="medium",
            ),
            FormField(
                name="approval",
                label="Require Approval For",
                field_type="multi_checkbox",
                options=[
                    StepOption(value=val, label=label, description=desc)
                    for val, label, desc in self.APPROVAL_OPTIONS
                ],
                default=[],
            ),
            FormField(
                name="messaging_platform",
                label="Preferred Notification Platform",
                field_type="select",
                options=[
                    StepOption(value=val, label=label, default=(val == "tui"))
                    for val, label in self.PLATFORM_OPTIONS
                ],
                default="tui",
            ),
        ]

    def get_options(self) -> List[StepOption]:
        # Not a single-select step — form fields are used instead
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
      """Validate the form data dict. All fields are optional."""
      if not isinstance(value, dict):
          return False, "Expected a dictionary of form values"
      user_name = value.get("user_name")
      if user_name and len(str(user_name)) > 20:
          return False, "Name must be 20 characters or fewer"
      # Validate approval is a list if present
      approval = value.get("approval")
      if approval is not None and not isinstance(approval, list):
          return False, "Approval settings must be a list"
      return True, None

    def get_default(self) -> Dict[str, Any]:
        """Return defaults for all fields."""
        fields = self.get_form_fields()
        return {f.name: f.default for f in fields}


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
    UserProfileStep,
    MCPStep,
    SkillsStep,
]
