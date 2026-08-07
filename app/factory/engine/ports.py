# -*- coding: utf-8 -*-
"""Factory engine ports (FACTORY-PLAN §3.2) — the ONLY doors to a host.

The engine is the generic durable-workflow core ("deterministic
orchestration, free intelligence"). It may import NOTHING from the host or
from a domain pack; hosts hand it implementations of these Protocols.
`check_imports.py` enforces the direction mechanically.

Frozen after Phase 0: additions require a FACTORY-PLAN amendment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ModelPort(Protocol):
    """One raw LLM call. No sessions, no provider semantics — the engine
    composes every prompt fresh (fresh-context per mission is the point)."""

    def complete(
        self,
        messages: List[Dict[str, str]],
        schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.0,
    ) -> str:
        """Return the model's text (JSON text when `schema` is given)."""
        ...


@runtime_checkable
class IntegrationPort(Protocol):
    """OPTIONAL host-managed integrations (Base44-pattern). Absent port ⇒
    apps build with third-party APIs only; briefs must say so honestly."""

    def capabilities(self) -> Dict[str, Any]:
        """{'connected': [...], 'actions': {name: {...schema...}}, 'facts': [...]}"""
        ...

    def call(
        self,
        action: str,
        params: Dict[str, Any],
        confirm: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """{'status': int, 'data'|'error': ...} — mirrors the bridge contract."""
        ...


@runtime_checkable
class NotifyPort(Protocol):
    """The machine composes ALL user-facing status; the host only renders.
    Event kinds (typed by `kind`): phase, defects, ready, stuck, question."""

    def emit(self, event: Dict[str, Any]) -> None: ...


@runtime_checkable
class MissionDispatcher(Protocol):
    """Runs ONE fresh-context mission and reports its outcome back to the
    machine. Phase 1: CraftBot triggers/sessions. Phase 3: the ACI runner."""

    def dispatch(self, mission: Dict[str, Any]) -> str:
        """Start the mission (brief included); return a mission id."""
        ...
