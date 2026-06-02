# -*- coding: utf-8 -*-
"""
app.network_interface.state

Process-wide cache of the managed-Bedrock quota-lock state. The dashboard is
the source of truth; this module just remembers what we last heard back.

Signal flow:
    /api/instance-callback/usage     → DashboardClient parses response body  ┐
    /api/instance-callback/heartbeat → DashboardClient parses response body  ┴→ set_quota_lock()
                                                                               │
                                                                               ▼
    LLMInterface / VLMInterface, before each Bedrock call: is_quota_locked()
        true  → raise ManagedQuotaExceededError; chat surfaces a QUOTA bubble
        false → call proceeds

Critically: `is_quota_locked()` is a *local* check — no HTTP, no DB, no I/O.
It must never block the LLM hot path. The dashboard's lock state is pulled in
opportunistically when our own outbound calls return, so the cache is always
at most one round-trip stale.

Failure modes:
  - Dashboard unreachable → cache retains last value. Stays locked if it was
    locked; stays unlocked otherwise. Next successful heartbeat resyncs.
  - Agent restart → cache resets to "unlocked". The heartbeat loop's
    immediate-first-send (see app/network_interface/heartbeat.py) repopulates
    it within seconds. Tiny window where one Bedrock call may slip through
    before the first heartbeat lands; acceptable.
  - Lock expires (month rollover) → dashboard returns `usageLockedUntil: null`
    in the next heartbeat response → set_quota_lock(None) clears.
"""

from __future__ import annotations

import datetime as _dt
import threading
from typing import Optional


# Guards the module-level state — set/read from multiple coroutines (heartbeat
# task, LLM call sites). The lock is held only for trivial reads/writes; never
# during HTTP work, so contention is effectively nil.
_lock = threading.Lock()
_quota_locked_until: Optional[_dt.datetime] = None


def _parse_iso(value: Optional[str]) -> Optional[_dt.datetime]:
    """Best-effort ISO-8601 → aware datetime. Returns None on bad input —
    callers treat that as "no lock state change"."""
    if not value:
        return None
    try:
        dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def set_quota_lock(iso_or_none: Optional[str]) -> None:
    """Update the cached lock. None / empty / unparseable → clear the lock.

    Called by the DashboardClient after every successful /heartbeat or /usage
    response. The dashboard always sends the field (null when not locked), so
    receiving the field is the auth signal that the cache should be trusted.
    """
    parsed = _parse_iso(iso_or_none) if iso_or_none else None
    with _lock:
        global _quota_locked_until
        _quota_locked_until = parsed


def is_quota_locked() -> bool:
    """Returns True iff we currently believe a managed-Bedrock lock is in
    effect. Treats locks whose timestamp has already passed as expired (we
    self-clear lazily so a missed heartbeat doesn't leave a stale lock pinned).

    This is the hot-path predicate called before every Bedrock LLM/VLM call —
    pure local check, no I/O.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    with _lock:
        global _quota_locked_until
        if _quota_locked_until is None:
            return False
        if _quota_locked_until <= now:
            _quota_locked_until = None
            return False
        return True


def get_quota_reset() -> Optional[_dt.datetime]:
    """The cached reset timestamp, or None when not locked. Used by the LLM
    error message to tell the user when managed Bedrock will resume."""
    now = _dt.datetime.now(_dt.timezone.utc)
    with _lock:
        global _quota_locked_until
        if _quota_locked_until is None:
            return None
        if _quota_locked_until <= now:
            _quota_locked_until = None
            return None
        return _quota_locked_until


def _reset_for_tests() -> None:
    """Clear the cache. Tests that want a clean slate between cases."""
    with _lock:
        global _quota_locked_until
        _quota_locked_until = None
