# -*- coding: utf-8 -*-
"""
Hard onboarding step definitions and implementations.

Each step represents one screen/phase in the hard onboarding wizard.
Steps are UI-agnostic - they define the data and validation logic,
not the presentation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class StepOption:
    """An option that can be selected in a step."""

    value: str  # Internal value (e.g., "openai")
    label: str  # Display label (e.g., "OpenAI")
    description: str = ""  # Optional description
    default: bool = False  # Whether this is the default selection
    icon: str = ""  # Lucide icon name (e.g., "Folder", "Search")
    requires_setup: bool = (
        False  # Whether this option requires additional setup (API key, etc.)
    )


@dataclass
class FormField:
    """A field in a multi-field form step (e.g., User Profile)."""

    name: str  # Field key (e.g., "user_name")
    label: str  # Display label
    field_type: str  # "text", "select", "multi_checkbox"
    options: List["StepOption"] = field(
        default_factory=list
    )  # For select/checkbox types
    default: Any = ""  # Default value
    placeholder: str = ""  # Hint text


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


class IntroStep:
    """Welcome screen. The agent introduces itself before setup begins.

    Collects nothing; the only action is to advance. The browser wizard renders
    it as a message beside the mascot with a single "Get started" button (no
    input).
    """

    name = "intro"
    title = "Nice to meet you, I'm CraftBot!"
    description = (
        "Nice to meet you, I am CraftBot! I am here to help you with work or "
        "life. Now before we begin, there are some baseline settings we need "
        "to configure."
    )
    required = True

    def get_options(self) -> List[StepOption]:
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        return True, None

    def get_default(self) -> str:
        return ""


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
        ("minimax", "MiniMax", "MiniMax models"),
        ("moonshot", "Moonshot", "Moonshot models"),
        ("grok", "Grok (xAI)", "Grok models"),
        ("glm", "Z.ai (GLM)", "GLM models"),
        ("fugu", "Sakana (Fugu)", "Fugu models"),
        ("remote", "Ollama (Local)", "Self-hosted models"),
    ]

    def get_options(self) -> List[StepOption]:
        return [
            StepOption(
                value=provider_id,
                label=label,
                description=desc,
                default=(provider_id == "openai"),
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
    """API key input step, or Ollama connection setup for the remote provider."""

    name = "api_key"
    required = True

    # Maps provider to environment variable name
    PROVIDER_ENV_VARS = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "byteplus": "BYTEPLUS_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "grok": "XAI_API_KEY",
        "glm": "ZAI_API_KEY",
        "fugu": "SAKANA_API_KEY",
        "remote": None,  # Ollama uses a base URL, not an API key
    }

    def __init__(self, provider: str = "openai"):
        self.provider = provider

    # Providers that may be geo-restricted; support both direct and OpenRouter paths.
    OPENROUTER_PROXIED = {"moonshot", "minimax"}
    OPENROUTER_PROXIED_DISPLAY = {"moonshot": "Moonshot (Kimi)", "minimax": "MiniMax"}

    @staticmethod
    def _provider_info(provider: str) -> Dict[str, Any]:
        """Look up a provider's PROVIDER_INFO entry (single source of truth
        for subscription-OAuth capability, shared with the Settings page)."""
        try:
            from app.ui_layer.settings.model_settings import PROVIDER_INFO

            return PROVIDER_INFO.get(provider, {}) or {}
        except Exception:
            return {}

    def supports_subscription_oauth(self) -> bool:
        """True when this provider offers a subscription sign-in (ChatGPT
        Plus/Pro, SuperGrok) as an alternative to an API key."""
        return bool(
            self._provider_info(self.provider).get("supports_subscription_oauth")
        )

    def subscription_label(self) -> str:
        """Button label for the subscription sign-in (e.g. 'Sign in with ChatGPT')."""
        return self._provider_info(self.provider).get("subscription_label") or ""

    def _subscription_connected(self) -> bool:
        """True when an OAuth subscription credential is already stored for
        this provider, in which case an API key is optional."""
        if not self.supports_subscription_oauth():
            return False
        try:
            from app.ui_layer.settings.provider_settings import get_subscription_status

            return bool(get_subscription_status(self.provider).get("connected"))
        except Exception:
            return False

    @property
    def title(self) -> str:
        if self.provider == "remote":
            return "Connect Ollama"
        if self.provider in self.OPENROUTER_PROXIED:
            display = self.OPENROUTER_PROXIED_DISPLAY.get(self.provider, self.provider)
            return f"Enter {display} API Key"
        return "Enter API Key"

    @property
    def description(self) -> str:
        if self.provider == "remote":
            return (
                "Connect to your local Ollama instance.\n"
                "If Ollama isn't installed yet, we'll help you set it up."
            )
        if self.provider in self.OPENROUTER_PROXIED:
            display = self.OPENROUTER_PROXIED_DISPLAY.get(self.provider, self.provider)
            return (
                f"Enter your {display} API key. If your region doesn't have direct access, "
                f"you can use OpenRouter as a fallback instead."
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

        # Proxied providers submit {api_key, via, or_model?} dict
        if self.provider in self.OPENROUTER_PROXIED and isinstance(value, dict):
            api_key = value.get("api_key", "")
            if not api_key or len(str(api_key).strip()) < 10:
                return False, "API key is required"
            return True, None

        # A connected subscription (ChatGPT Plus/Pro, SuperGrok) authorizes the
        # provider via an OAuth bearer, so the API key is optional. Accept an
        # empty submission in that case; a typed key still validates below.
        is_empty = not value or (isinstance(value, str) and not value.strip())
        if is_empty and self._subscription_connected():
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
    """Agent name configuration step (name only, no avatar)."""

    name = "agent_name"
    title = "Name your agent"
    description = "Give your agent a name."
    required = False

    def get_form_fields(self) -> List[FormField]:
        return [
            FormField(
                name="agent_name",
                label="Agent Name",
                field_type="text",
                default="CraftBot",
                placeholder="Enter a name",
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
            return True, None
        return False, "Invalid agent name submission"

    def get_default(self) -> Dict[str, Any]:
        return {"agent_name": "CraftBot"}


class UserProfileStep:
    """User step: collects only the user's name.

    Location is inferred from the user's IP and the communication language from
    the OS locale; the remaining preferences (tone, proactivity, approval,
    notification platform) use sensible defaults rather than being asked. See
    :meth:`enrich`, which fills those in at completion time.
    """

    name = "user_profile"
    title = "Your Name"
    description = "What should your agent call you?"
    required = False

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
    def _default_language() -> str:
        """Two-letter communication language derived from the OS locale."""
        try:
            import locale as _locale

            os_locale = _locale.getdefaultlocale()[0] or "en_US"
            return os_locale.split("_")[0] or "en"
        except Exception:
            return "en"

    def get_form_fields(self) -> List[FormField]:
        """Only the user's name is collected in the UI."""
        return [
            FormField(
                name="user_name",
                label="Your Name",
                field_type="text",
                placeholder="Your name",
                default="",
            ),
        ]

    def enrich(self, submitted: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge the name the user typed with values derived silently.

        Location comes from the IP geolocation, language from the OS locale,
        and the preference fields no longer shown in the UI fall back to
        defaults, so ``write_profile_to_user_md`` still receives a full
        profile dict.
        """
        data: Dict[str, Any] = dict(submitted or {})
        if not data.get("location"):
            try:
                data["location"] = self.fetch_geolocation()
            except Exception:
                data["location"] = ""
        if not data.get("language"):
            data["language"] = self._default_language()
        data.setdefault("tone", "casual")
        data.setdefault("proactivity", "medium")
        data.setdefault("approval", [])
        data.setdefault("messaging_platform", "tui")
        return data

    def get_options(self) -> List[StepOption]:
        # Not a single-select step; form fields are used instead
        return []

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        """Validate the form data dict. The name is optional."""
        if not isinstance(value, dict):
            return False, "Expected a dictionary of form values"
        user_name = value.get("user_name")
        if user_name and len(str(user_name)) > 20:
            return False, "Name must be 20 characters or fewer"
        return True, None

    def get_default(self) -> Dict[str, Any]:
        """Return defaults for the visible fields."""
        return {f.name: f.default for f in self.get_form_fields()}


# Ordered list of the active hard-onboarding steps.
ALL_STEPS = [
    IntroStep,
    ProviderStep,
    ApiKeyStep,
    UserProfileStep,
    AgentNameStep,
]
