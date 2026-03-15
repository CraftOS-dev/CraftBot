# -*- coding: utf-8 -*-
"""
app.main

Main driver code that starts the **vanilla BaseAgent**.
All configuration is read from settings.json (not .env files).

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
import sys

# Register agent_core state provider and config before importing AgentBase
# This ensures shared code can access state via get_state()
from agent_core import StateRegistry, ConfigRegistry
from app.state.agent_state import STATE

# CraftBot uses global STATE singleton - always available
StateRegistry.register(lambda: STATE)
ConfigRegistry.register_workspace_root(".")

# Import settings reader (reads directly from settings.json)
from app.config import get_llm_provider, get_api_key, get_base_url
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


def _initial_settings() -> tuple[str, str, str, bool]:
    """Determine initial provider, API key, and base URL from settings.json.

    Returns:
        Tuple of (provider, api_key, base_url, has_valid_key) where has_valid_key
        indicates if a working API key was found.
    """
    # Read directly from settings.json
    provider = get_llm_provider()
    api_key = get_api_key(provider)
    base_url = get_base_url(provider)

    # Remote (Ollama) doesn't require API key
    has_key = bool(api_key) or provider == "remote"

    return provider, api_key, base_url, has_key


async def main_async() -> None:
    # Parse CLI arguments
    cli_args = _parse_cli_args()
    cli_mode = cli_args.get("cli", False)
    browser_mode = cli_args.get("browser", False)

    # Get settings from settings.json
    provider, api_key, base_url, has_valid_key = _initial_settings()

    # CLI args override settings.json if provided
    if cli_args.get("provider"):
        provider = cli_args["provider"]
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)
        has_valid_key = bool(api_key) or provider == "remote"

    if cli_args.get("api_key"):
        api_key = cli_args["api_key"]
        has_valid_key = True

    # Use deferred initialization if no valid API key is configured yet
    # This allows the TUI/CLI to start so first-time users can configure settings
    agent = AgentBase(
        data_dir="app/data",
        chroma_path="./chroma_db",
        llm_provider=provider,
        llm_api_key=api_key,
        llm_base_url=base_url,
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

    await agent.run(provider=provider, api_key=api_key, base_url=base_url, interface_mode=interface_mode)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
