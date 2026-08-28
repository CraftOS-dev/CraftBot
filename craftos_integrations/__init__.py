"""craftos_integrations — plug-and-play external integrations.

Quick start:

    import asyncio
    from craftos_integrations import configure, list_metadata

    async def main():
        configure(
            project_root=".",
            oauth={"GITHUB_CLIENT_ID": "...", ...},
        )
        for meta in list_metadata():
            print(meta["id"], meta["name"], meta["auth_type"])
        client = system.client_for("github", identity)
        issues = client.list_issues("owner/repo")

    asyncio.run(main())

Connect / disconnect / listening are the IntegrationSystem's job — see
``craftos_integrations.core.system`` and the host wiring in
``app/integrations.py``.

Adding a new integration: create a folder under
craftos_integrations/providers/ with an ``__init__.py`` (handler +
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
from .oauth_flow import OAuthFlow, REDIRECT_URI, REDIRECT_URI_HTTPS
from .registry import (
    autoload_integrations,
    get_all_clients,
    get_client,
    get_registered_platforms,
    register_client,
)
from .service import (
    get_config,
    get_config_schema,
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
    list_metadata,
    status,
    update_config,
)
from .spec import IntegrationSpec

__all__ = [
    # Setup
    "configure",
    "ConfigStore",
    # Base classes / types
    "BasePlatformClient",
    "PlatformMessage",
    "MessageCallback",
    "IntegrationSpec",
    # Registry
    "register_client",
    "get_client",
    "get_all_clients",
    "get_registered_platforms",
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
    "is_connected",
    "list_connected",
    "list_all",
    "status",
    # Metadata + connect dispatchers
    "get_metadata",
    "list_metadata",
    "get_integration_info",
    "list_integrations",
    # Sync wrappers + helpers (for synchronous callers)
    "get_integration_info_sync",
    "get_integration_auth_type",
    "get_integration_fields",
    "integration_registry",
]
