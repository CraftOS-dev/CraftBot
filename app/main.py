# -*- coding: utf-8 -*-
"""
app.main

Main driver code that starts the **vanilla BaseAgent**.
All configuration is read from settings.json (not .env files).

Run this before the app directory, using 'python -m app.main'
"""

# ============================================================================
# CRITICAL: SSL bootstrap BEFORE any TLS-using import (aiohttp, openai, etc.)
#
# On Windows, a single malformed certificate in the OS cert store
# ("Trusted Root", "CA", etc.) breaks ssl.create_default_context() with
# "[ASN1: NOT_ENOUGH_DATA]" because the stdlib loads ALL Windows certs in
# one batch via load_verify_locations(cadata=...). One bad cert poisons the
# whole batch.
#
# Workaround: wrap SSLContext._load_windows_store_certs to swallow that
# specific SSLError. Lost Windows-CA-store certs are replaced by certifi's
# Mozilla bundle (set_default_verify_paths still runs), so server cert
# validation still works for PyPI / OpenAI / Anthropic / etc.
import sys as _sys

if _sys.platform == "win32":
    import ssl as _ssl

    _orig_load_win_certs = getattr(_ssl.SSLContext, "_load_windows_store_certs", None)
    if _orig_load_win_certs is not None:

        def _safe_load_windows_store_certs(self, storename, purpose):
            try:
                return _orig_load_win_certs(self, storename, purpose)
            except _ssl.SSLError:
                # Malformed cert in store — skip silently. certifi still loads.
                return None

        _ssl.SSLContext._load_windows_store_certs = _safe_load_windows_store_certs

    # Also try truststore as an extra layer (uses Windows SChannel directly
    # on modern versions); harmless if not installed.
    try:
        import truststore as _truststore

        _truststore.inject_into_ssl()
    except Exception:
        pass
# ============================================================================

# ============================================================================
# CRITICAL: Suppress console logging BEFORE imports
# Must be done before any module calls logging.basicConfig()
# ============================================================================
import os as _os
import warnings as _warnings

# Suppress all Python warnings during startup (DeprecationWarning, RuntimeWarning, etc.)
_warnings.filterwarnings("ignore")

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


# ============================================================================
# CRITICAL: SSL shim for Windows certificate store
# Must run BEFORE any import that pulls in aiohttp/ssl (e.g. app.agent_base).
#
# On some Windows machines the system certificate store contains a malformed
# certificate. The combination of conda's Python 3.10 + bundled OpenSSL in
# this environment can't parse the raw-DER batch that _load_windows_store_certs
# concatenates, and crashes at module import time with:
#   ssl.SSLError: [ASN1: NOT_ENOUGH_DATA] not enough data (_ssl.c:4040)
#
# aiohttp triggers this at import time via _make_ssl_context(True), so we
# can't catch it after the fact. We:
#   1. Point Python's default verify paths at certifi's CA bundle.
#   2. Wrap _load_windows_store_certs to swallow SSLError so a single bad
#      Windows cert no longer kills startup.
# ============================================================================
def _install_ssl_windows_store_shim() -> None:
    if _os.name != "nt":
        return
    try:
        import ssl as _ssl
        import certifi as _certifi
    except Exception:
        return

    _os.environ.setdefault("SSL_CERT_FILE", _certifi.where())
    _os.environ.setdefault("REQUESTS_CA_BUNDLE", _certifi.where())

    _orig = getattr(_ssl.SSLContext, "_load_windows_store_certs", None)
    if _orig is None:
        return

    def _safe_load_windows_store_certs(self, storename, purpose):
        try:
            return _orig(self, storename, purpose)
        except _ssl.SSLError:
            return bytearray()

    _ssl.SSLContext._load_windows_store_certs = _safe_load_windows_store_certs


_install_ssl_windows_store_shim()
# ============================================================================

import argparse
import asyncio

from app.runtime_preflight import ensure_current_runtime_dependencies

ensure_current_runtime_dependencies()

# Register agent_core state provider and config before importing AgentBase
# This ensures shared code can access state via get_state()
from agent_core import StateRegistry, ConfigRegistry
from app.state.agent_state import STATE
from app.config import get_project_root

# CraftBot uses global STATE singleton - always available
StateRegistry.register(lambda: STATE)
ConfigRegistry.register_workspace_root(str(get_project_root()))

# Import settings reader (reads directly from settings.json)
from app.config import (
    get_llm_provider,
    get_vlm_provider,
    get_image_gen_provider,
    get_api_key,
    get_base_url,
    get_llm_model,
    get_vlm_model,
    get_image_gen_model,
)
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
        help="Run in CLI mode (terminal command-line interface)",
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


def _initial_settings() -> tuple:
    """Determine initial provider, API key, and base URL from settings.json.

    Returns:
        Tuple of (provider, api_key, base_url, model, vlm_provider, vlm_model,
        image_gen_provider, image_gen_model, has_valid_key)
        where has_valid_key indicates if a working API key was found.
    """
    # Read directly from settings.json
    provider = get_llm_provider()
    api_key = get_api_key(provider)
    base_url = get_base_url(provider)
    model = get_llm_model()  # None → use registry default for the provider
    vlm_prov = get_vlm_provider()
    vlm_mod = get_vlm_model()
    img_prov = get_image_gen_provider()
    img_mod = get_image_gen_model()

    # Remote (Ollama) doesn't require API key
    has_key = bool(api_key) or provider == "remote"

    return (
        provider,
        api_key,
        base_url,
        model,
        vlm_prov,
        vlm_mod,
        img_prov,
        img_mod,
        has_key,
    )


async def main_async() -> None:
    # Parse CLI arguments
    cli_args = _parse_cli_args()
    browser_mode = cli_args.get("browser", False)

    # Get settings from settings.json
    (
        provider,
        api_key,
        base_url,
        model,
        vlm_prov,
        vlm_mod,
        img_prov,
        img_mod,
        has_valid_key,
    ) = _initial_settings()

    # CLI args override settings.json if provided
    if cli_args.get("provider"):
        provider = cli_args["provider"]
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)
        model = get_llm_model()
        has_valid_key = bool(api_key) or provider == "remote"

    if cli_args.get("api_key"):
        api_key = cli_args["api_key"]
        has_valid_key = True

    # Use deferred initialization if no valid API key is configured yet
    # This allows the CLI to start so first-time users can configure settings
    agent = AgentBase(
        data_dir="app/data",
        chroma_path="./chroma_db",
        llm_provider=provider,
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        vlm_provider=vlm_prov,
        vlm_model=vlm_mod,
        image_gen_provider=img_prov,
        image_gen_model=img_mod,
        deferred_init=not has_valid_key,
    )

    # Initialize onboarding manager with agent reference
    from app.onboarding import onboarding_manager

    onboarding_manager.set_agent(agent)

    # Determine interface mode: browser if requested, otherwise CLI
    if browser_mode:
        interface_mode = "browser"
    else:
        interface_mode = "cli"

    await agent.run(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        interface_mode=interface_mode,
    )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
