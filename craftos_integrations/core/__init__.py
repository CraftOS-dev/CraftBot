"""Integrations core — host-agnostic account/storage/registry machinery.

Public surface:

    from craftos_integrations.core import (
        AccountManager, FileCredentialStore, IntegrationRegistry, IntegrationSystem,
    )
"""

from .accounts import AccountManager, AccountRecord, AccountSet
from .listeners import FileCursorStore, ListenerManager
from .registry import IntegrationRegistry
from .storage import FileCredentialStore
from .system import IntegrationSystem

__all__ = [
    "AccountManager",
    "AccountRecord",
    "AccountSet",
    "FileCredentialStore",
    "FileCursorStore",
    "IntegrationRegistry",
    "IntegrationSystem",
    "ListenerManager",
]
