"""craftos_integrations — plug-and-play external integrations.

Quick start:

    import asyncio
    from craftos_integrations import configure, initialize_manager, get_handler

    async def on_message(payload):
        print(f"[{payload['source']}] {payload['contactName']}: {payload['messageBody']}")

    async def main():
        configure(
            project_root=".",
            oauth={"GITHUB_CLIENT_ID": "...", ...},
        )
        manager = await initialize_manager(on_message=on_message)
        # auth flows go through handlers:
        ok, msg = await get_handler("github").handle("login", ["<pat>"])
        print(msg)

    asyncio.run(main())

Adding a new integration: create a folder under
craftos_integrations/integrations/ with an ``__init__.py`` (handler +
client) and an optional ``INTEGRATION.md``. It is auto-loaded at startup.
See integrations/github/ for the canonical shape.
"""

from __future__ import annotations

# Apply runtime compatibility shim before any submodule that uses asyncio.timeout
# imports it (websockets, aiohttp, etc.). See _runtime_compat.py for details.
from ._runtime_compat import apply_asyncio_timeout_shim as _apply_timeout_shim

_apply_timeout_shim()

from .base import (
    BasePlatformClient,
    IntegrationHandler,
    MessageCallback,
    PlatformMessage,
)
from .config import ConfigStore, configure
from .credentials_store import (
    has_config,
    has_credential,
    load_config,
    load_credential,
    remove_config,
    remove_credential,
    save_config,
    save_credential,
)
from .manager import (
    ExternalCommsManager,
    get_external_comms_manager,
    initialize_manager,
)
from .oauth_flow import OAuthFlow, REDIRECT_URI, REDIRECT_URI_HTTPS
from .registry import (
    autoload_integrations,
    get_all_clients,
    get_all_handlers,
    get_client,
    get_handler,
    get_registered_handler_names,
    get_registered_platforms,
    register_client,
    register_handler,
)
from .service import (
    connect_interactive,
    connect_oauth,
    connect_token,
    disconnect,
    get_config,
    get_config_schema,
    get_integration_accounts,
    get_integration_auth_type,
    get_integration_fields,
    get_integration_info,
    get_integration_info_sync,
    get_metadata,
    integration_registry,
    is_connected,
    list_all,
    list_connected,
    list_integrations,
    list_integrations_sync,
    list_metadata,
    parse_status_accounts,
    send_message,
    status,
    update_config,
)
from .spec import IntegrationSpec

__all__ = [
    # Setup
    "configure",
    "ConfigStore",
    "initialize_manager",
    "get_external_comms_manager",
    "ExternalCommsManager",
    # Base classes / types
    "BasePlatformClient",
    "IntegrationHandler",
    "PlatformMessage",
    "MessageCallback",
    "IntegrationSpec",
    # Registry
    "register_client",
    "register_handler",
    "get_client",
    "get_handler",
    "get_all_clients",
    "get_all_handlers",
    "get_registered_platforms",
    "get_registered_handler_names",
    "autoload_integrations",
    # Credentials
    "save_credential",
    "load_credential",
    "has_credential",
    "remove_credential",
    # Per-integration runtime config
    "save_config",
    "load_config",
    "has_config",
    "remove_config",
    "get_config",
    "update_config",
    "get_config_schema",
    # OAuth helper
    "OAuthFlow",
    "REDIRECT_URI",
    "REDIRECT_URI_HTTPS",
    # Common-ops facade
    "send_message",
    "is_connected",
    "list_connected",
    "list_all",
    "disconnect",
    "status",
    # Metadata + connect dispatchers
    "get_metadata",
    "list_metadata",
    "get_integration_info",
    "list_integrations",
    "parse_status_accounts",
    "connect_token",
    "connect_oauth",
    "connect_interactive",
    # Sync wrappers + helpers (for TUI / synchronous callers)
    "list_integrations_sync",
    "get_integration_info_sync",
    "get_integration_accounts",
    "get_integration_auth_type",
    "get_integration_fields",
    "integration_registry",
]
