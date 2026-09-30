"""Pending chat-started setups: setup interviews the user has not finished.

When the agent runs ``agent_app_scaffold`` from a chat and the wizard has
questions, no project exists yet; the user answers in the Create Custom
wizard and finalize creates the project. Until then the setup lives here, so
closing the popup, reloading the page or connecting a new tab never loses it
(issue #448, docs/plans/agent-app-setup-resume-plan.md).

Lifecycle::

    opened ──► (hidden ⇄ shown)* ──► finalized  (project created; record removed)
                                   └► cancelled  (record removed; origin agent told)

Hiding and showing the popup are browser-only; the record is created by the
scaffold action and removed by finalize, cancel, or deletion of the chat that
started it.

This module owns persistence only. It knows nothing about browsers, triggers
or the agent: the UI layer turns the surrounding messages into resource
invalidations, and ``origin_notices`` tells the agent. The setup is Agent App
state, which is why it is not stored as a chat message.

Only the chat path persists setups. The "+" modal's Create Custom flow is
opened by the user, so closing it is a cancel and nothing is kept.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover - loguru is always present in-app
    import logging

    logger = logging.getLogger(__name__)


def _name_key(name: str) -> str:
    """Case- and whitespace-insensitive app-name key used for dedup."""
    return " ".join(str(name or "").split()).casefold()


@dataclass(frozen=True)
class PendingSetup:
    """A chat-started setup interview the user has not finished yet."""

    wizard_id: str
    origin_session_id: str
    name: str
    config: Dict[str, Any]
    questions: List[Dict[str, Any]]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Wire shape: the same fields ``agent_app_wizard_open`` carries."""
        return {
            "wizardId": self.wizard_id,
            "originSessionId": self.origin_session_id,
            "name": self.name,
            "config": self.config,
            "questions": self.questions,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingSetup":
        return cls(
            wizard_id=str(d["wizardId"]),
            origin_session_id=str(d.get("originSessionId") or ""),
            name=str(d.get("name") or ""),
            config=dict(d.get("config") or {}),
            questions=list(d.get("questions") or []),
            created_at=float(d.get("createdAt") or time.time()),
        )


class PendingSetupRegistry:
    """Persisted pending chat setups, keyed by wizard id. Thread-safe."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._by_id: Dict[str, PendingSetup] = {}
        self._load()

    def add(self, setup: PendingSetup) -> None:
        with self._lock:
            self._by_id[setup.wizard_id] = setup
            self._save()

    def get(self, wizard_id: str) -> Optional[PendingSetup]:
        with self._lock:
            return self._by_id.get(wizard_id)

    def find(self, origin_session_id: str, name: str) -> Optional[PendingSetup]:
        """The pending setup this session already opened for an app of this
        name, so a repeated scaffold reopens it instead of re-interviewing."""
        key = _name_key(name)
        with self._lock:
            for setup in self._by_id.values():
                if (
                    setup.origin_session_id == origin_session_id
                    and _name_key(setup.name) == key
                ):
                    return setup
        return None

    def remove(self, wizard_id: str) -> Optional[PendingSetup]:
        """Drop a setup; returns it, or None when it was already gone."""
        with self._lock:
            setup = self._by_id.pop(wizard_id, None)
            if setup is not None:
                self._save()
            return setup

    def remove_for_session(self, session_id: str) -> List[PendingSetup]:
        """Drop every setup started from ``session_id`` (the chat was deleted)."""
        with self._lock:
            removed = [
                s for s in self._by_id.values() if s.origin_session_id == session_id
            ]
            for setup in removed:
                del self._by_id[setup.wizard_id]
            if removed:
                self._save()
            return removed

    def list(self) -> List[PendingSetup]:
        """All pending setups, oldest first."""
        with self._lock:
            return sorted(self._by_id.values(), key=lambda s: s.created_at)

    # ── persistence ─────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as e:
            logger.warning(f"[PENDING_SETUPS] unreadable registry, starting empty: {e}")
            return
        for d in raw.get("setups", []):
            try:
                setup = PendingSetup.from_dict(d)
            except Exception as e:
                logger.warning(f"[PENDING_SETUPS] skipping malformed record: {e}")
                continue
            self._by_id[setup.wizard_id] = setup

    def _save(self) -> None:
        # Write-then-replace so a crash mid-write never truncates the file.
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"setups": [s.to_dict() for s in self._by_id.values()]}
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception as e:
            logger.error(f"[PENDING_SETUPS] could not persist registry: {e}")


def get_pending_setups() -> Optional[PendingSetupRegistry]:
    """The process-wide registry owned by the Agent App manager, or None
    before the manager exists (early boot, headless)."""
    from app.agent_app import get_agent_app_manager

    mgr = get_agent_app_manager()
    return getattr(mgr, "pending_setups", None) if mgr is not None else None


__all__ = ["PendingSetup", "PendingSetupRegistry", "get_pending_setups"]
