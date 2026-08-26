"""Registry for platform clients and integration handlers.

Two parallel registries (clients and handlers) keep the runtime and auth
lifecycles separate. Both are populated by decorators (@register_client,
@register_client) and resolved as singletons.

autoload_integrations() walks the integrations/ subpackage and imports
every module — that triggers the decorators. Adding a new integration
is one file drop with no edits here.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Optional, Type

from .base import BasePlatformClient
from .logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════
# Platform clients (runtime side)
# ════════════════════════════════════════════════════════════════════════

_client_classes: Dict[str, Type[BasePlatformClient]] = {}
_client_instances: Dict[str, BasePlatformClient] = {}


def register_client(cls: Type[BasePlatformClient]) -> Type[BasePlatformClient]:
    pid = cls.PLATFORM_ID
    if not pid:
        raise ValueError(f"{cls.__name__} has no PLATFORM_ID set")
    _client_classes[pid] = cls
    return cls


def get_client(platform_id: str) -> Optional[BasePlatformClient]:
    if platform_id in _client_instances:
        return _client_instances[platform_id]
    cls = _client_classes.get(platform_id)
    if cls is None:
        return None
    instance = cls()
    _client_instances[platform_id] = instance
    return instance


def get_all_clients() -> Dict[str, BasePlatformClient]:
    for pid in _client_classes:
        if pid not in _client_instances:
            _client_instances[pid] = _client_classes[pid]()
    return dict(_client_instances)


def get_registered_platforms() -> List[str]:
    return list(_client_classes.keys())


# ════════════════════════════════════════════════════════════════════════
# Integration handlers (auth side)
# ════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════
# Autoloader
# ════════════════════════════════════════════════════════════════════════

_autoloaded = False


def autoload_integrations(force: bool = False) -> None:
    """Import every provider's ``client`` module.

    Triggers the @register_client decorators. Idempotent unless force=True.

    ``providers`` is **optional**: if a host has deleted the folder (or the
    package is being used framework-only), this logs a single info line and
    returns. The registry stays empty and every ``get_client`` call returns
    ``None`` — callers handle that via ``{"error": "Unknown integration ..."}``
    envelopes.
    """
    global _autoloaded
    if _autoloaded and not force:
        return

    try:
        from . import providers as pkg
    except ImportError:
        logger.info("[REGISTRY] No providers/ subpackage found — registry stays empty.")
        _autoloaded = True
        return

    pkg_path = getattr(pkg, "__path__", None)
    if not pkg_path:
        logger.info(
            "[REGISTRY] providers/ subpackage has no __path__ — registry stays empty."
        )
        _autoloaded = True
        return

    for _, modname, ispkg in pkgutil.iter_modules(pkg_path):
        if modname.startswith("_") or not ispkg:
            continue
        full = f"{pkg.__name__}.{modname}.client"
        try:
            importlib.import_module(full)
        except Exception as e:
            logger.warning(f"[REGISTRY] Failed to autoload {full}: {e}")

    _autoloaded = True


def reset() -> None:
    """Clear all instances (for testing)."""
    global _autoloaded
    _client_instances.clear()
    _autoloaded = False
