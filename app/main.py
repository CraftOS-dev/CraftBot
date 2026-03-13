# -*- coding: utf-8 -*-
"""
app.main

Main driver code that starts the **vanilla BaseAgent**.
Environment variables let you tweak connection details without code
changes, making this usable inside Docker containers.

Run this before the app directory, using 'python -m app.main'
"""

# ============================================================================
# CRITICAL: Suppress console logging and terminal escape sequences BEFORE imports
# This prevents log messages from corrupting the Textual TUI display.
# Must be done before any module calls logging.basicConfig()
# ============================================================================
import os as _os
import warnings as _warnings
import sys as _sys

# Suppress Kitty graphics protocol detection (prevents garbage output like "Gi=...")
# This tells Textual not to query for Kitty graphics support
_os.environ.setdefault("KITTEN_NO_GRAPHICS", "1")
_os.environ.setdefault("TEXTUAL_SCREENSHOT", "0")

# Suppress all Python warnings during startup (DeprecationWarning, RuntimeWarning, etc.)
_warnings.filterwarnings('ignore')

# Suppress library-specific warnings
_os.environ.setdefault("PYTHONWARNINGS", "ignore")

import logging

def _suppress_console_logging_early() -> None:
    """
    Pre-configure the root logger to prevent console output.

    Called at module load time BEFORE other imports to ensure
    logging.basicConfig() calls in other modules don't add StreamHandlers.
    """
    root_logger = logging.getLogger()
    # Add a NullHandler to prevent basicConfig from being auto-called
    # when the first log message is emitted
    if not root_logger.handlers:
        root_logger.addHandler(logging.NullHandler())
    # Set a high level to minimize processing
    root_logger.setLevel(logging.CRITICAL)
    
    # Also suppress warnings from specific noisy libraries
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    logging.getLogger("websockets").setLevel(logging.CRITICAL)

_suppress_console_logging_early()
# ============================================================================

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Register agent_core state provider and config before importing AgentBase
# This ensures shared code can access state via get_state()
from agent_core import StateRegistry, ConfigRegistry
from app.state.agent_state import STATE

# CraftBot uses global STATE singleton - always available
StateRegistry.register(lambda: STATE)
ConfigRegistry.register_workspace_root(".")

from app.agent_base import AgentBase


def _parse_cli_args() -> dict:
    """Parse CLI-specific arguments.

    Returns:
        Dictionary with parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="CraftBot Agent",
        add_help=False,  # Don't conflict with other parsers
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode instead of TUI",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Run with browser interface (WebSocket server)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["openai", "gemini", "byteplus", "anthropic", "remote"],
        help="LLM provider to use",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for the provider",
    )

    # Parse known args only, ignore unknown ones
    args, _ = parser.parse_known_args()
    return vars(args)


def _initial_settings() -> tuple[str, str, bool]:
    """Determine initial provider and API key settings.

    Returns:
        Tuple of (provider, api_key, has_valid_key) where has_valid_key
        indicates if a working API key was found.
    """
    # If LLM_PROVIDER is explicitly set, use it
    explicit_provider = os.getenv("LLM_PROVIDER")
    if explicit_provider:
        key_lookup = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "byteplus": "BYTEPLUS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        key_name = key_lookup.get(explicit_provider, "")
        api_key = os.getenv(key_name, "") if key_name else ""
        # Remote (Ollama) doesn't require API key
        has_key = bool(api_key) or explicit_provider == "remote"
        return explicit_provider, api_key, has_key

    # Default to BytePlus if its API key is available
    byteplus_key = os.getenv("BYTEPLUS_API_KEY", "")
    if byteplus_key:
        return "byteplus", byteplus_key, True

    # Auto-detect provider based on which API key is set
    fallback_providers = [
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GOOGLE_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ]
    for provider, key_name in fallback_providers:
        api_key = os.getenv(key_name, "")
        if api_key:
            return provider, api_key, True

    # No API keys found - default to openai but flag as not configured
    # This allows the TUI to start so user can configure settings
    return "openai", "", False


def _apply_api_key(provider: str, api_key: str) -> None:
    """Apply provider and API key to environment variables."""
    key_lookup = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "byteplus": "BYTEPLUS_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    key_name = key_lookup.get(provider)
    if key_name and api_key:
        os.environ[key_name] = api_key
    os.environ["LLM_PROVIDER"] = provider


async def main_async() -> None:
    # Parse CLI arguments
    cli_args = _parse_cli_args()
    cli_mode = cli_args.get("cli", False)
    browser_mode = cli_args.get("browser", False)

    # CLI args override environment variables if provided
    if cli_args.get("provider"):
        os.environ["LLM_PROVIDER"] = cli_args["provider"]
    if cli_args.get("api_key"):
        # Apply to appropriate env var based on provider
        arg_provider = cli_args.get("provider") or os.getenv("LLM_PROVIDER", "openai")
        key_lookup = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "byteplus": "BYTEPLUS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        key_name = key_lookup.get(arg_provider)
        if key_name:
            os.environ[key_name] = cli_args["api_key"]

    provider, api_key, has_valid_key = _initial_settings()
    _apply_api_key(provider, api_key)

    # Use deferred initialization if no valid API key is configured yet
    # This allows the TUI/CLI to start so first-time users can configure settings
    agent = AgentBase(
        data_dir=os.getenv("DATA_DIR", "app/data"),
        chroma_path=os.getenv("CHROMA_PATH", "./chroma_db"),
        llm_provider=provider,
        deferred_init=not has_valid_key,
    )

    # Initialize onboarding manager with agent reference
    from app.onboarding import onboarding_manager
    onboarding_manager.set_agent(agent)

    # Determine interface mode: browser > cli > tui (default)
    if browser_mode:
        interface_mode = "browser"
    elif cli_mode:
        interface_mode = "cli"
    else:
        interface_mode = "tui"

    await agent.run(provider=provider, api_key=api_key, interface_mode=interface_mode)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
