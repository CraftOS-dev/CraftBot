"""Listener fan-out — one supervised listener per (provider, account).

``ListenerManager`` owns every inbound-event instance centrally
(multi-account-v2-plan §8): providers only implement
``make_listener(client, cursor, emit)``; the manager decides *which*
instances exist by reconciling desired state (AccountSets × ``listen``
flags) against running ones, tags every event with its account via the
emit closure, staggers same-provider pollers, isolates crash-loops, and
persists per-account cursors across restarts.

Host-blind: nothing here imports from a host application. The host wires
``system.listeners = manager`` and the system's mutation paths call
``system.reconcile_listeners()`` so UI changes take effect immediately.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import ConfigStore
from ..logger import get_logger
from .system import IntegrationSystem
from ..contracts import EventSink, Listener, Provider

logger = get_logger(__name__)

PAUSED_STATUS = "listening paused — reconnect to resume"


class FileCursorStore:
    """Per-account listener cursors, ``<credentials dir>/_cursors/<pid>.json``.

    Each file is one JSON object ``{identity: cursor_dict}``. Writes are
    atomic (tmp + os.replace) so a crash can never tear a file; there is
    deliberately no cross-process locking — losing a cursor is harmless
    (a poller re-scans and dedups), so locking heroics would buy nothing.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        """``root`` is the credentials directory; cursors live in its
        ``_cursors/`` subdirectory. Defaults to the same directory the
        default FileCredentialStore uses (resolved lazily — the host sets
        ``ConfigStore.project_root`` at startup)."""
        self._root = root

    def _dir(self) -> Path:
        base = self._root or (ConfigStore.project_root / ".credentials")
        path = base / "_cursors"
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, stat.S_IRWXU)
        except OSError:
            pass
        return path

    def _path(self, provider_id: str) -> Path:
        return self._dir() / f"{provider_id}.json"

    def load_all(self, provider_id: str) -> Dict[str, Dict[str, Any]]:
        path = self._path(provider_id)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            # Cursors are disposable dedup state — a bad file is dropped,
            # never quarantined; the affected pollers just re-scan.
            logger.warning(f"[CURSORS] {path.name} unreadable, ignoring: {e}")
            return {}

    def get(self, provider_id: str, identity: str) -> Optional[Dict[str, Any]]:
        cursor = self.load_all(provider_id).get(identity)
        return cursor if isinstance(cursor, dict) else None

    def set(
        self, provider_id: str, identity: str, cursor: Dict[str, Any]
    ) -> None:
        data = self.load_all(provider_id)
        data[identity] = cursor
        self._write(provider_id, data)

    def remove(self, provider_id: str, identity: str) -> None:
        data = self.load_all(provider_id)
        if identity in data:
            del data[identity]
            self._write(provider_id, data)

    def migrate_legacy(self, provider_id: str, identity: str) -> None:
        """Placeholder for legacy single-account cursor migration (§8.3).

        Pre-multi-account listeners kept their poll state inside the host application
        (CraftBot's trigger runtime), not in this package — there is no
        legacy cursor file here to import, so this is a documented no-op.
        If a host has such state, it can subclass and seed the identity's
        entry here; a missing cursor is harmless either way (the poller
        re-scans and dedups on first cycle).
        """

    def _write(self, provider_id: str, data: Dict[str, Any]) -> None:
        path = self._path(provider_id)
        # Unique tmp per write: concurrent writers sharing one tmp name race
        # on the rename (the loser's os.replace hits ENOENT).
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                if hasattr(os, "fchmod"):  # POSIX only; Windows ACLs don't map
                    os.fchmod(f.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


@dataclass
class _Instance:
    """One supervised listener for one (provider, identity)."""

    provider_id: str
    identity: str
    listener: Listener
    credential: Dict[str, Any]  # deepcopy of what it was built with
    delay: float = 0.0  # stagger delay before first start
    task: Optional[asyncio.Task] = None
    state: str = "starting"  # starting|running|backoff|paused|stopped
    failures: int = 0  # consecutive failures
    detail: str = ""
    stop_requested: bool = False

    @property
    def key(self) -> Tuple[str, str]:
        return (self.provider_id, self.identity)


class ListenerManager:
    """Reconciles, supervises, and isolates per-account listeners.

    ``max_failures`` consecutive crashes disable an instance (state
    ``paused``, detail ``PAUSED_STATUS``); a paused instance is rebuilt
    only when a later reconcile sees its account's credential change
    (re-auth) — plain reconciles leave it paused so a revoked credential
    can't crash-loop forever. The extra keyword knobs exist so tests can
    run in milliseconds; production uses the defaults.
    """

    def __init__(
        self,
        system: IntegrationSystem,
        sink: EventSink,
        cursors: FileCursorStore,
        *,
        max_failures: int = 5,
        backoff_base: float = 1.0,
        backoff_cap: float = 60.0,
        stagger_default: float = 2.0,
    ) -> None:
        self.system = system
        self.sink = sink
        self.cursors = cursors
        self.max_failures = max_failures
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._stagger_default = stagger_default
        self._instances: Dict[Tuple[str, str], _Instance] = {}
        self._lock = asyncio.Lock()
        self._stopped = asyncio.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Reconcile to desired state, then hold until ``stop()``."""
        self.loop = asyncio.get_running_loop()
        self._stopped.clear()
        await self.reconcile()
        await self._stopped.wait()

    async def stop(self) -> None:
        """Stop every instance, persisting each cursor, and release start()."""
        async with self._lock:
            for key in list(self._instances):
                await self._stop_instance(self._instances.pop(key))
        self._stopped.set()

    async def reconcile(self) -> None:
        """Diff desired (provider × listen-true account) vs running.

        Starts exactly the new instances, stops exactly the removed ones,
        and restarts any instance whose account credential differs from
        the one it was built with (re-auth / token rotation)."""
        self.loop = asyncio.get_running_loop()
        async with self._lock:
            desired: Dict[Tuple[str, str], Provider] = {}
            for provider in self.system.providers():
                try:
                    accounts = self.system.accounts.list_accounts(provider.id)
                except Exception as e:
                    logger.warning(
                        f"[LISTEN] listing {provider.id} accounts failed: {e}"
                    )
                    continue
                for account in accounts:
                    if account.listen:
                        desired[(provider.id, account.identity)] = provider

            # Stop instances whose account vanished or stopped listening.
            for key in list(self._instances):
                if key not in desired:
                    await self._stop_instance(self._instances.pop(key))

            # Restart instances whose credential changed underneath them —
            # this is also the only path that revives a paused instance.
            for key, instance in list(self._instances.items()):
                if self._credential_changed(instance):
                    await self._stop_instance(self._instances.pop(key))

            # Build the missing ones, staggered per provider.
            new_by_provider: Dict[str, List[Tuple[str, str]]] = {}
            for key in desired:
                if key not in self._instances:
                    new_by_provider.setdefault(key[0], []).append(key)
            for provider_id, keys in new_by_provider.items():
                started: List[_Instance] = []
                for _, identity in sorted(keys):
                    instance = self._build_instance(
                        desired[(provider_id, identity)], identity
                    )
                    if instance is not None:
                        started.append(instance)
                count = len(started)
                for k, instance in enumerate(started):
                    instance.delay = self._stagger_delay(instance, k, count)
                    self._instances[instance.key] = instance
                    instance.task = asyncio.create_task(
                        self._supervise(instance),
                        name=f"listener:{provider_id}:{instance.identity}",
                    )

    def status(self) -> Dict[str, Dict[str, Any]]:
        """Per-instance state, keyed ``"<provider_id>:<identity>"``."""
        return {
            f"{i.provider_id}:{i.identity}": {
                "state": i.state,
                "failures": i.failures,
                "detail": i.detail,
                "delay": i.delay,
            }
            for i in self._instances.values()
        }

    # ── instance machinery ───────────────────────────────────────────────

    def _credential_changed(self, instance: _Instance) -> bool:
        try:
            current = self.system.accounts.credential_for(
                instance.provider_id, instance.identity
            )
        except Exception:
            return True  # account gone mid-flight; reconcile drops it next
        return current != instance.credential

    def _build_instance(
        self, provider: Provider, identity: str
    ) -> Optional[_Instance]:
        provider_id = provider.id
        try:
            credential = copy.deepcopy(
                self.system.accounts.credential_for(provider_id, identity)
            )
            client = self.system.client_for(provider_id, identity)
            cursor = self.cursors.get(provider_id, identity)
            if cursor is None:
                self.cursors.migrate_legacy(provider_id, identity)
                cursor = self.cursors.get(provider_id, identity)

            async def emit(event: Dict[str, Any]) -> None:
                await self.sink.on_event(provider_id, identity, event)

            listener = provider.make_listener(client, cursor, emit)
            if listener is None:
                return None
            return _Instance(
                provider_id=provider_id,
                identity=identity,
                listener=listener,
                credential=credential,
            )
        except Exception as e:
            logger.warning(
                f"[LISTEN] building {provider_id}/{identity} listener failed: {e}"
            )
            return None

    def _stagger_delay(self, instance: _Instance, k: int, count: int) -> float:
        if k == 0:
            return 0.0
        interval = getattr(instance.listener, "poll_interval", None)
        if isinstance(interval, (int, float)) and interval > 0 and count > 0:
            return k * (float(interval) / count)
        return k * self._stagger_default

    async def _supervise(self, instance: _Instance) -> None:
        """Run listener.start() forever with backoff; pause on crash-loop."""
        try:
            if instance.delay > 0:
                await asyncio.sleep(instance.delay)
            backoff = self._backoff_base
            while not instance.stop_requested:
                instance.state = "running"
                try:
                    await instance.listener.start()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    instance.failures += 1
                    instance.detail = str(e)
                    if instance.failures >= self.max_failures:
                        instance.state = "paused"
                        instance.detail = PAUSED_STATUS
                        logger.warning(
                            f"[LISTEN] {instance.provider_id}/{instance.identity} "
                            f"failed {instance.failures}x; {PAUSED_STATUS}"
                        )
                        return
                    instance.state = "backoff"
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self._backoff_cap)
                    continue
                # Clean return = one successful cycle.
                self._persist_cursor(instance)
                instance.failures = 0
                instance.detail = ""
                backoff = self._backoff_base
                if instance.stop_requested:
                    return
                instance.state = "idle"
                await asyncio.sleep(self._backoff_base)
        except asyncio.CancelledError:
            pass
        finally:
            if instance.stop_requested:
                instance.state = "stopped"

    async def _stop_instance(self, instance: _Instance) -> None:
        instance.stop_requested = True
        try:
            await instance.listener.stop()
        except Exception as e:
            logger.warning(
                f"[LISTEN] stopping {instance.provider_id}/"
                f"{instance.identity} raised: {e}"
            )
        if instance.task is not None and not instance.task.done():
            instance.task.cancel()
            try:
                await instance.task
            except (asyncio.CancelledError, Exception):
                pass
        self._persist_cursor(instance)
        instance.state = "stopped"

    def _persist_cursor(self, instance: _Instance) -> None:
        try:
            cursor = instance.listener.cursor()
            if cursor is not None:
                self.cursors.set(instance.provider_id, instance.identity, cursor)
        except Exception as e:
            logger.warning(
                f"[LISTEN] persisting {instance.provider_id}/"
                f"{instance.identity} cursor failed: {e}"
            )
