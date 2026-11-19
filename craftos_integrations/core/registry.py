"""Provider registry + per-account client instance cache.

Cache keys are ``(provider_id, resolved_identity)`` — resolution happens
BEFORE the cache (in IntegrationSystem), so alias spellings share one
client, bad hints never pollute the cache, and cache size is bounded by
real accounts.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts import Provider
from ..logger import get_logger

logger = get_logger(__name__)


class IntegrationRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, Provider] = {}
        self._clients: Dict[Tuple[str, str], Any] = {}
        # Clients are built in worker threads while invalidations run on the
        # event loop. The lock guards only the cache itself (never a credential
        # read or a build); the generation tells a builder that an
        # invalidation landed while it was building.
        self._clients_lock = threading.Lock()
        self._generation = 0

    # ── providers ────────────────────────────────────────────────────────

    def register(self, provider: Provider) -> None:
        if provider.id in self._providers:
            raise ValueError(f"Provider '{provider.id}' registered twice")
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Optional[Provider]:
        return self._providers.get(provider_id)

    def all_providers(self) -> List[Provider]:
        return list(self._providers.values())

    def family_members(self, provider_id: str) -> Sequence[str]:
        """Every provider id sharing this provider's alias family,
        including itself. Providers with family=None are their own family."""
        provider = self._providers.get(provider_id)
        if provider is None or not provider.family:
            return (provider_id,)
        return tuple(
            pid for pid, p in self._providers.items() if p.family == provider.family
        )

    # ── client instance cache ────────────────────────────────────────────

    def get_cached_client(self, provider_id: str, identity: str) -> Optional[Any]:
        return self._clients.get((provider_id, identity))

    def cached_client(
        self, provider_id: str, identity: str
    ) -> Tuple[Optional[Any], int]:
        """(cached client or None, cache generation), read together."""
        with self._clients_lock:
            return self._clients.get((provider_id, identity)), self._generation

    def cache_client(self, provider_id: str, identity: str, client: Any) -> None:
        with self._clients_lock:
            self._clients[(provider_id, identity)] = client

    def cache_built_client(
        self, provider_id: str, identity: str, client: Any, generation: int
    ) -> Optional[Any]:
        """Cache a client built from a credential read at ``generation``, and
        return the client to use: a client another builder cached first wins,
        so an account has one client. None when the cache was invalidated
        since ``generation``: the credential may have changed, so the caller
        builds again."""
        with self._clients_lock:
            if self._generation != generation:
                return None
            existing = self._clients.get((provider_id, identity))
            if existing is not None:
                return existing
            self._clients[(provider_id, identity)] = client
            return client

    def invalidate(self, provider_id: str, identity: Optional[str] = None) -> None:
        """Drop cached clients so the next use rebuilds from disk. With no
        identity, drops every account's client for the provider. Alias and
        primary changes re-point routing, so their cached resolutions must
        die immediately (issue #314 class)."""
        with self._clients_lock:
            self._generation += 1
            if identity is not None:
                self._clients.pop((provider_id, identity), None)
                return
            for key in [k for k in self._clients if k[0] == provider_id]:
                self._clients.pop(key, None)

    def reset(self) -> None:
        """Testing: drop all providers and cached clients."""
        self._providers.clear()
        with self._clients_lock:
            self._generation += 1
            self._clients.clear()
