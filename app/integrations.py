"""Host bootstrap for the integrations system.

The single place CraftBot constructs its IntegrationSystem. Everything
host-specific about the system — which storage backend, which providers, where
legacy credential files live — is decided here; the package itself stays
host-blind.

Lazy singleton: construction needs nothing from app config because the
FileCredentialStore resolves ``ConfigStore.project_root`` per call, so
``get_system()`` is safe to call before ``configure_integrations`` has run
(clients are only built at action-execution time, long after startup).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.logger import get_logger

logger = get_logger(__name__)

_system: Optional[IntegrationSystem] = None
_listeners: Optional[Any] = None  # ListenerManager, built lazily in start_listeners()
_listener_task: Optional[asyncio.Task] = None  # holds ListenerManager.start()'s run-loop


def _legacy_filenames() -> Dict[str, str]:
    """Map provider id → the legacy single-account credential filename, read
    from the old handlers' IntegrationSpec so the two can never drift."""
    mapping: Dict[str, str] = {}
    try:
        from craftos_integrations import registry as legacy_registry

        legacy_registry.autoload_integrations()
        for name, handler in legacy_registry.get_all_handlers().items():
            spec = getattr(handler, "spec", None)
            if spec is None:
                continue
            mapping[name] = spec.cred_file
            mapping[spec.platform_id] = spec.cred_file
    except Exception:
        # Fall back to the store's default (<provider_id>.json) per lookup.
        pass
    return mapping


def get_system() -> IntegrationSystem:
    global _system
    if _system is None:
        from craftos_integrations.providers import default_providers

        _system = IntegrationSystem(
            store=FileCredentialStore(legacy_filenames=_legacy_filenames()),
            providers=default_providers(),
        )
    return _system


def reset_system() -> None:
    """Testing hook: drop the singletons so the next get_system() rebuilds."""
    global _system, _listeners
    _system = None
    _listeners = None


# ── listener fan-out (PR 5) ──────────────────────────────────────────────


class CraftBotEventSink:
    """EventSink implementation: listener events → the agent's trigger
    system.

    The ListenerManager emits the same payload-dict shape the legacy
    ``ExternalCommsManager._handle_platform_message`` builds, so events are
    forwarded to the very same host callback (``ConfigStore.on_message``,
    set by ``initialize_manager``) — the agent cannot tell which engine
    delivered a message. Before forwarding, the payload is enriched with
    the account that received it so multi-account routing survives the
    trip: ``payload["account"]`` carries the identity, and the
    human-readable ``source`` gains an ``(alias-or-identity)`` suffix.
    """

    async def on_event(
        self, provider_id: str, identity: str, event: Dict[str, Any]
    ) -> None:
        from craftos_integrations.config import ConfigStore

        on_message = ConfigStore.on_message
        if on_message is None:
            logger.warning(
                f"[LISTENERS] Dropping {provider_id}/{identity} event: "
                "no on_message callback configured"
            )
            return

        payload = dict(event)
        payload["account"] = identity

        alias: Optional[str] = None
        try:
            for info in get_system().accounts.list_accounts(provider_id):
                if info.identity == identity:
                    alias = info.alias
                    break
        except Exception:
            pass  # best-effort: fall back to the bare identity
        payload["source"] = f"{payload.get('source', provider_id)} ({alias or identity})"

        await on_message(payload)


def _log_listener_task_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[LISTENERS] manager run-loop died: {exc!r}")


async def start_listeners() -> None:
    """Build (once) and start the ListenerManager.

    Wires FileCursorStore + CraftBotEventSink and attaches the manager as
    ``system.listeners`` so account mutations can reconcile running
    listeners.

    ``ListenerManager.start()`` is a service run-loop — it reconciles and
    then HOLDS until ``stop()`` — so it must run as a background task;
    awaiting it inline deadlocks the caller (observed live 2026-08-12:
    agent boot froze at step 6/7). Idempotent: the manager is built once
    and a still-running task is left alone.
    """
    global _listeners, _listener_task
    if _listeners is None:
        from craftos_integrations.core.listeners import (
            FileCursorStore,
            ListenerManager,
        )

        system = get_system()
        _listeners = ListenerManager(system, CraftBotEventSink(), FileCursorStore())
        system.listeners = _listeners
    if _listener_task is None or _listener_task.done():
        _listener_task = asyncio.create_task(
            _listeners.start(), name="integrations-listener-manager"
        )
        _listener_task.add_done_callback(_log_listener_task_exit)
        # Yield once so the manager's initial reconcile gets underway
        # before boot continues.
        await asyncio.sleep(0)


async def stop_listeners() -> None:
    """Stop the ListenerManager if it was ever started."""
    global _listener_task
    if _listeners is not None:
        await _listeners.stop()
    if _listener_task is not None:
        if not _listener_task.done():
            try:
                await _listener_task
            except asyncio.CancelledError:
                pass
        _listener_task = None
