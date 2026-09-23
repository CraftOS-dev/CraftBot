"""Agent App port allocation and running-instance registry.

This module is the single source of truth for Agent App ports and running
server processes. It replaces three older, uncoordinated mechanisms:

  * the manager's live-port bookkeeping (`_used_ports`, `_allocate_port`,
    `_release_port`, the dead `_next_port`),
  * the shadow provisioner's untracked `_free_port` bind-probe, and
  * the per-project `.factory/host.json` "staging" record that stood in for
    "a shadow exists".

The design rule that motivates it: **identity is an instance id, never a
port.** Every running PocketBase (live OR shadow) is an `Instance` with a
stable `instance_id`. Ports are a pure allocation detail. Routing, probing,
liveness and teardown all resolve an `Instance` first and then act on that
instance's own port/pid. Two projects landing on the same port number (which
happens by construction, because both pools hand out the lowest free port)
is therefore harmless: nothing decides anything from the bare number.

Two disjoint pools are kept, as before, so the reaper can reason about ranges:
  * LIVE   3100-3199  (the app's stable, user-facing address; persisted)
  * SHADOW 3900-3999  (a hidden dev boot; ephemeral, one per project at a time)

Both pools are governed by ONE `PortAllocator` with ONE lock and a single
reservation set, so a port is reserved before it is handed back and no two
allocations (across pools, across projects, across threads) can collide.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover - loguru is always present in-app
    import logging

    logger = logging.getLogger(__name__)

# The two pools. Kept disjoint on purpose (the startup reconciler scans both
# ranges), but governed by one allocator so reservations never race.
LIVE_RANGE = (3100, 3199)
SHADOW_RANGE = (3900, 3999)

ROLE_LIVE = "live"
ROLE_SHADOW = "shadow"


class PortPoolExhausted(RuntimeError):
    """No free port remains in the requested pool."""

    def __init__(self, role: str, lo: int, hi: int) -> None:
        super().__init__(f"no free {role} port in range {lo}-{hi}")
        self.role = role


def _range_for(role: str) -> tuple:
    if role == ROLE_LIVE:
        return LIVE_RANGE
    if role == ROLE_SHADOW:
        return SHADOW_RANGE
    raise ValueError(f"unknown instance role: {role!r}")


# ── ports ───────────────────────────────────────────────────────────────────


class PortAllocator:
    """Hands out unique, actually-bindable ports from the two pools.

    A port is added to the reservation set BEFORE it is returned, so a caller
    that has not yet bound its server still owns the number and a concurrent
    allocation cannot be handed the same one (the TOCTOU gap the old shadow
    `_free_port` had). One lock covers both pools.
    """

    def __init__(self) -> None:
        self._reserved: set = set()
        self._lock = threading.RLock()

    def reserve(self, role: str) -> int:
        """Reserve and return the lowest free, bindable port in `role`'s pool."""
        lo, hi = _range_for(role)
        with self._lock:
            for port in range(lo, hi + 1):
                if port in self._reserved:
                    continue
                if not self._bindable(port):
                    continue
                self._reserved.add(port)
                return port
        raise PortPoolExhausted(role, lo, hi)

    def reserve_known(self, port: Optional[int]) -> None:
        """Mark an already-decided port as reserved (project load, live boot).

        Idempotent. Used for the sticky live port, whose lifetime is the
        project's, not a single boot's.
        """
        if port:
            with self._lock:
                self._reserved.add(int(port))

    def release(self, port: Optional[int]) -> None:
        """Return a port to the pool. Idempotent."""
        if port:
            with self._lock:
                self._reserved.discard(int(port))

    def clear(self) -> None:
        """Drop every reservation (used when the whole project set is wiped,
        e.g. a profile-bundle overwrite import)."""
        with self._lock:
            self._reserved.clear()

    def is_reserved(self, port: int) -> bool:
        with self._lock:
            return int(port) in self._reserved

    @staticmethod
    def _bindable(port: int) -> bool:
        """True when no one is listening on `port` AND we can bind it now.

        Two probes, deliberately: `connect_ex` only sees an established
        listener; a fresh bind rejects a port held in TIME_WAIT or grabbed by
        a foreign process between the two checks. No SO_REUSEADDR on the bind
        probe — a weakened bind test is exactly how the old code let two
        shadows think 3900 was free.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return False  # someone is listening
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


# ── instances ─────────────────────────────────────────────────────────────


@dataclass
class Instance:
    """One running (or booting) Agent App server process.

    `instance_id` is THE identity. `port` and `pid` are attributes of the
    instance, never lookup keys for identity decisions. `token` is the bridge
    token the process authenticates with (a shadow inherits the live
    project's token, so bridge traffic still resolves to the right project).
    """

    instance_id: str
    project_id: str
    role: str  # ROLE_LIVE | ROLE_SHADOW
    port: int
    pid: Optional[int] = None
    token: str = ""
    boot_id: str = ""
    dir: str = ""  # per-boot state dir (shadow); project dir (live)
    public_dir: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def data_dir(self) -> Path:
        return Path(self.dir) / "pb_data"

    @property
    def log_dir(self) -> Path:
        return Path(self.dir) / "logs"

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Instance":
        known = {f: d.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        known["instance_id"] = d["instance_id"]
        known["project_id"] = d["project_id"]
        known["role"] = d["role"]
        known["port"] = int(d["port"])
        return cls(**known)


class InstanceRegistry:
    """Authoritative set of running Agent App instances.

    Persisted to one JSON file so startup reconciliation is a single pass. At
    most one live instance and one shadow instance exist per project at a
    time; `create_*` enforces that by evicting the previous one.
    """

    def __init__(self, path: Path, allocator: PortAllocator) -> None:
        self._path = Path(path)
        self._ports = allocator
        self._by_id: Dict[str, Instance] = {}
        self._lock = threading.RLock()
        self._load()

    # ── construction / eviction ────────────────────────────────────────────
    def create_shadow(
        self,
        project_id: str,
        *,
        token: str,
        boot_id: str,
        dir: str,
        public_dir: str = "",
    ) -> Instance:
        """Reserve a shadow port and register a fresh shadow instance.

        Any existing shadow instance for the project is evicted first (its
        port released) — a project has one shadow at a time.
        """
        with self._lock:
            self._evict(project_id, ROLE_SHADOW)
            port = self._ports.reserve(ROLE_SHADOW)
            inst = Instance(
                instance_id=self._new_id(ROLE_SHADOW, project_id),
                project_id=project_id,
                role=ROLE_SHADOW,
                port=port,
                token=token,
                boot_id=boot_id,
                dir=str(dir),
                public_dir=str(public_dir),
            )
            self._by_id[inst.instance_id] = inst
            self._save()
            return inst

    def register_live(
        self,
        project_id: str,
        port: int,
        *,
        pid: Optional[int] = None,
        token: str = "",
        dir: str = "",
    ) -> Instance:
        """Register (or replace) the live instance for a project.

        The live port is sticky — owned for the project's lifetime, not a
        single boot — so it is reserved via `reserve_known` and is NOT
        released when the instance is later removed (only on project delete).
        """
        with self._lock:
            self._evict(project_id, ROLE_LIVE, release_port=False)
            self._ports.reserve_known(port)
            inst = Instance(
                instance_id=self._new_id(ROLE_LIVE, project_id),
                project_id=project_id,
                role=ROLE_LIVE,
                port=int(port),
                pid=pid,
                token=token,
                dir=str(dir),
            )
            self._by_id[inst.instance_id] = inst
            self._save()
            return inst

    def adopt_pid(self, instance_id: str, pid: int) -> None:
        with self._lock:
            inst = self._by_id.get(instance_id)
            if inst is not None:
                inst.pid = int(pid)
                self._save()

    def set_public_dir(self, instance_id: str, public_dir: str) -> None:
        with self._lock:
            inst = self._by_id.get(instance_id)
            if inst is not None:
                inst.public_dir = str(public_dir)
                self._save()

    def remove(self, instance_id: str) -> Optional[Instance]:
        """Remove an instance. Shadow ports are released; the sticky live port
        is retained (released by the manager on project delete)."""
        with self._lock:
            inst = self._by_id.pop(instance_id, None)
            if inst is not None:
                if inst.role == ROLE_SHADOW:
                    self._ports.release(inst.port)
                self._save()
            return inst

    def clear_project(self, project_id: str) -> List[Instance]:
        """Remove every instance for a project (used on stop/delete). Returns
        the removed instances so the caller can kill their processes."""
        with self._lock:
            removed = [i for i in self._by_id.values() if i.project_id == project_id]
            for inst in removed:
                self._by_id.pop(inst.instance_id, None)
                if inst.role == ROLE_SHADOW:
                    self._ports.release(inst.port)
            if removed:
                self._save()
            return removed

    # ── lookup (by identity/role, never by a bare port) ────────────────────
    def get(self, instance_id: str) -> Optional[Instance]:
        with self._lock:
            return self._by_id.get(instance_id)

    def live(self, project_id: str) -> Optional[Instance]:
        return self._one(project_id, ROLE_LIVE)

    def shadow(self, project_id: str) -> Optional[Instance]:
        return self._one(project_id, ROLE_SHADOW)

    def route(self, project_id: str) -> Optional[Instance]:
        """Where agent/CLI/HTTP traffic for a project goes right now: the
        shadow if one is up, else the live instance."""
        return self.shadow(project_id) or self.live(project_id)

    def for_project(self, project_id: str) -> List[Instance]:
        with self._lock:
            return [i for i in self._by_id.values() if i.project_id == project_id]

    def all(self) -> List[Instance]:
        with self._lock:
            return list(self._by_id.values())

    # ── startup reconciliation ──────────────────────────────────────────────
    def reset(self) -> List[Instance]:
        """Drop every instance and release every shadow port. Returns the
        prior instances so the reconciler can verify-and-kill their processes.
        Live ports are re-reserved from the persisted project list separately.
        """
        with self._lock:
            prior = list(self._by_id.values())
            for inst in prior:
                if inst.role == ROLE_SHADOW:
                    self._ports.release(inst.port)
            self._by_id.clear()
            self._save()
            return prior

    # ── internals ───────────────────────────────────────────────────────────
    def _one(self, project_id: str, role: str) -> Optional[Instance]:
        with self._lock:
            for inst in self._by_id.values():
                if inst.project_id == project_id and inst.role == role:
                    return inst
            return None

    def _evict(self, project_id: str, role: str, release_port: bool = True) -> None:
        existing = self._one(project_id, role)
        if existing is not None:
            self._by_id.pop(existing.instance_id, None)
            if release_port and existing.role == ROLE_SHADOW:
                self._ports.release(existing.port)

    @staticmethod
    def _new_id(role: str, project_id: str) -> str:
        # Readable for logs, unique by the random suffix (no time/counter, so
        # it is collision-free even for two boots in the same millisecond).
        return f"{role}-{project_id}-{secrets.token_hex(4)}"

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for d in raw.get("instances", []):
            try:
                inst = Instance.from_dict(d)
            except Exception as e:
                logger.warning(f"[INSTANCES] skipping malformed record: {e}")
                continue
            self._by_id[inst.instance_id] = inst

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"instances": [i.to_dict() for i in self._by_id.values()]}
            self._path.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"[INSTANCES] could not persist registry: {e}")


def get_instance_registry() -> Optional["InstanceRegistry"]:
    """The process-wide registry owned by the Agent App manager, or None when
    the manager is not yet constructed (early boot). Callers that run only
    while a project exists (actions, bridge, verifier) always get a registry;
    the None branch is an explicit guard, not a fallback code path."""
    from app.agent_app import get_agent_app_manager

    mgr = get_agent_app_manager()
    return getattr(mgr, "instances", None) if mgr is not None else None


__all__ = [
    "LIVE_RANGE",
    "SHADOW_RANGE",
    "ROLE_LIVE",
    "ROLE_SHADOW",
    "PortPoolExhausted",
    "PortAllocator",
    "Instance",
    "InstanceRegistry",
    "get_instance_registry",
]
