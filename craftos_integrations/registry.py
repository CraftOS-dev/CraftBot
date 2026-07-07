"""Registry for platform clients and integration handlers.

Two parallel registries (clients and handlers) keep the runtime and auth
lifecycles separate. Both are populated by decorators (@register_client,
@register_handler) and resolved as singletons.

autoload_integrations() walks the integrations/ subpackage and imports
every module — that triggers the decorators. Adding a new integration
is one file drop with no edits here.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Optional, Tuple, Type

from .base import BasePlatformClient, IntegrationHandler
from .logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════
# Platform clients (runtime side)
# ════════════════════════════════════════════════════════════════════════

_client_classes: Dict[str, Type[BasePlatformClient]] = {}
# Keyed by (platform_id, account_key). account_key is "" for the primary/
# single-account case, so existing single-arg get_client(pid) callers land on
# the same instance they always did.
_client_instances: Dict[Tuple[str, str], BasePlatformClient] = {}


def register_client(cls: Type[BasePlatformClient]) -> Type[BasePlatformClient]:
    pid = cls.PLATFORM_ID
    if not pid:
        raise ValueError(f"{cls.__name__} has no PLATFORM_ID set")
    _client_classes[pid] = cls
    return cls


def get_client(
    platform_id: str, account: Optional[str] = None
) -> Optional[BasePlatformClient]:
    """Get (or build) the client singleton for ``platform_id``.

    ``account`` selects which connected account this client instance talks to
    (an email or unique fragment — see ``_google_common.resolve_account``).
    ``None``/omitted means the primary account, cached under key ``""`` —
    identical behavior to before multi-account support existed.
    """
    key = (platform_id, account or "")
    if key in _client_instances:
        return _client_instances[key]
    cls = _client_classes.get(platform_id)
    if cls is None:
        return None
    instance = cls()
    instance._account = account
    _client_instances[key] = instance
    return instance


def get_all_clients() -> Dict[str, BasePlatformClient]:
    """One (primary-account) client per registered platform."""
    for pid in _client_classes:
        key = (pid, "")
        if key not in _client_instances:
            _client_instances[key] = _client_classes[pid]()
    return {pid: _client_instances[(pid, "")] for pid in _client_classes}


def invalidate_client(platform_id: str) -> None:
    """Drop every cached client instance for ``platform_id`` (all accounts).

    Client instances cache the account credential in memory (e.g. the Google
    mixin's ``_cred``). When an account is connected/disconnected at runtime the
    credential file on disk changes, but the live instance keeps serving the old
    account — so integration actions hit the wrong account until the agent is
    restarted. Dropping every cached instance for this platform forces a fresh
    build (and a fresh credential read from disk) on next use, mirroring what a
    restart does. See issue #314.
    """
    for key in [k for k in _client_instances if k[0] == platform_id]:
        _client_instances.pop(key, None)


def get_registered_platforms() -> List[str]:
    return list(_client_classes.keys())


# ════════════════════════════════════════════════════════════════════════
# Integration handlers (auth side)
# ════════════════════════════════════════════════════════════════════════

_handler_classes: Dict[str, Type[IntegrationHandler]] = {}
_handler_instances: Dict[str, IntegrationHandler] = {}


def register_handler(name: str):
    """Decorator: @register_handler("slack")."""

    def deco(cls: Type[IntegrationHandler]) -> Type[IntegrationHandler]:
        _handler_classes[name] = cls
        return cls

    return deco


def get_handler(name: str) -> Optional[IntegrationHandler]:
    if name in _handler_instances:
        return _handler_instances[name]
    cls = _handler_classes.get(name)
    if cls is None:
        return None
    instance = cls()
    _handler_instances[name] = instance
    return instance


def get_all_handlers() -> Dict[str, IntegrationHandler]:
    for name in _handler_classes:
        if name not in _handler_instances:
            _handler_instances[name] = _handler_classes[name]()
    return dict(_handler_instances)


def get_registered_handler_names() -> List[str]:
    return list(_handler_classes.keys())


# ════════════════════════════════════════════════════════════════════════
# Autoloader
# ════════════════════════════════════════════════════════════════════════

_autoloaded = False


def autoload_integrations(force: bool = False) -> None:
    """Import every module under craftos_integrations.integrations.

    Triggers @register_client and @register_handler decorators on import.
    Idempotent unless force=True.

    The ``integrations`` subpackage is **optional**: if a host has deleted
    the folder (or the package is being used framework-only), the autoloader
    logs a single info line and returns. The registry stays empty and every
    ``get_client``/``get_handler`` call returns ``None`` — callers handle
    that gracefully via ``{"error": "Unknown integration ..."}`` envelopes.
    """
    global _autoloaded
    if _autoloaded and not force:
        return

    try:
        from . import integrations as pkg
    except ImportError:
        logger.info(
            "[REGISTRY] No integrations/ subpackage found — registry stays empty."
        )
        _autoloaded = True
        return

    pkg_path = getattr(pkg, "__path__", None)
    if not pkg_path:
        logger.info(
            "[REGISTRY] integrations/ subpackage has no __path__ — registry stays empty."
        )
        _autoloaded = True
        return

    for _, modname, _ in pkgutil.iter_modules(pkg_path):
        if modname.startswith("_"):
            continue
        full = f"{pkg.__name__}.{modname}"
        try:
            importlib.import_module(full)
        except Exception as e:
            logger.warning(f"[REGISTRY] Failed to autoload {full}: {e}")

    _autoloaded = True


def reset() -> None:
    """Clear all instances (for testing)."""
    global _autoloaded
    _client_instances.clear()
    _handler_instances.clear()
    _autoloaded = False
