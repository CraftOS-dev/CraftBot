# -*- coding: utf-8 -*-
"""
Configuration abstractions for agent-core.

Provides a registry pattern for configuration values that differ
between CraftBot and CraftBot (e.g., AGENT_WORKSPACE_ROOT).
"""

from typing import Optional, Callable, Protocol, Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    pass

__all__ = [
    "ConfigRegistry",
    "get_workspace_root",
    "get_config",
    "CredentialClientProtocol",
    "get_credential_client",
    "register_credential_client",
]


class CredentialClientProtocol(Protocol):
    """Protocol for credential client implementations."""

    async def request_credential(
        self,
        integration_type: str,
        user_id: str,
        service_account_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Request credentials from the backend."""
        ...


class ConfigRegistry:
    """
    Registry for configuration values.

    Each host project (CraftBot, CraftBot) registers their
    config values at startup.
    """

    _workspace_root: Optional[str] = None
    _workspace_root_factory: Optional[Callable[[], str]] = None
    _config_values: dict = {}

    @classmethod
    def register_workspace_root(cls, path_or_factory) -> None:
        """
        Register the workspace root path or a factory function.

        Args:
            path_or_factory: Either a string path or a callable that returns the path.
        """
        if callable(path_or_factory):
            cls._workspace_root_factory = path_or_factory
            cls._workspace_root = None
        else:
            cls._workspace_root = path_or_factory
            cls._workspace_root_factory = None

    @classmethod
    def get_workspace_root(cls) -> str:
        """
        Get the workspace root path.

        Returns:
            The configured workspace root path.

        Raises:
            RuntimeError: If workspace root is not configured.
        """
        if cls._workspace_root_factory is not None:
            return cls._workspace_root_factory()
        if cls._workspace_root is not None:
            return cls._workspace_root
        raise RuntimeError(
            "ConfigRegistry.workspace_root not configured. "
            "Call ConfigRegistry.register_workspace_root() at startup."
        )

    @classmethod
    def set(cls, key: str, value) -> None:
        """Set a configuration value."""
        cls._config_values[key] = value

    @classmethod
    def get(cls, key: str, default=None):
        """Get a configuration value."""
        return cls._config_values.get(key, default)


def get_workspace_root() -> str:
    """Convenience function to get workspace root."""
    return ConfigRegistry.get_workspace_root()


def get_config(key: str, default=None):
    """Convenience function to get a config value."""
    return ConfigRegistry.get(key, default)


# Credential client registry
_credential_client: Optional[CredentialClientProtocol] = None
_credential_client_factory: Optional[Callable[[], Optional[CredentialClientProtocol]]] = None


def register_credential_client(client_or_factory) -> None:
    """
    Register a credential client or factory function.

    Args:
        client_or_factory: Either a CredentialClientProtocol instance
                          or a callable that returns one.
    """
    global _credential_client, _credential_client_factory
    if callable(client_or_factory) and not hasattr(client_or_factory, 'request_credential'):
        _credential_client_factory = client_or_factory
        _credential_client = None
    else:
        _credential_client = client_or_factory
        _credential_client_factory = None


def get_credential_client() -> Optional[CredentialClientProtocol]:
    """
    Get the registered credential client.

    Returns:
        The credential client instance, or None if not configured.
    """
    global _credential_client
    if _credential_client_factory is not None:
        return _credential_client_factory()
    return _credential_client
