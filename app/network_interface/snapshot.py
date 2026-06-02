# -*- coding: utf-8 -*-
"""
app.network_interface.snapshot

Read-only assemblers for the dashboard. Two responsibilities:

  - derive_agent_state(task_manager) — collapse the TaskManager's view of the
    world into the dashboard's coarse vocabulary
    ("idle" | "thinking" | "working" | "waiting" | "error").
  - process_uptime_seconds() — how long this agent process has been alive,
    used by the heartbeat.

Slice 3 will extend this module with snapshot builders for /state, /events,
and /tasks — keeping all dashboard-facing read paths next to each other.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Dict, List, Optional


# Agent state vocabulary mirrors the AgentState type the dashboard exports
# (apps/web/lib/types.ts). Keep them in sync — if the agent adds a state, the
# dashboard accepts it verbatim (rendered capitalised) without a release.
AGENT_STATE_IDLE = "idle"
AGENT_STATE_THINKING = "thinking"
AGENT_STATE_WORKING = "working"
AGENT_STATE_WAITING = "waiting"
AGENT_STATE_ERROR = "error"


# Recorded the first time process_uptime_seconds() is called, so a heartbeat
# can report a monotonic uptime regardless of wall-clock skew.
_started_monotonic: Optional[float] = None


def process_uptime_seconds() -> int:
    """Whole seconds since the agent process started (first call to this fn).

    Uses time.monotonic so it's immune to wall-clock jumps (NTP, suspend).
    The dashboard treats this as advisory — it's not persisted, just shown
    on the instance detail page.
    """
    global _started_monotonic
    if _started_monotonic is None:
        _started_monotonic = time.monotonic()
        return 0
    return int(time.monotonic() - _started_monotonic)


def derive_agent_state(task_manager: Any) -> str:
    """Map TaskManager state to the dashboard's coarse agent_state.

    Precedence (highest first):
      error   — last terminal task ended with status="error" recently
      waiting — a running task is flagged waiting_for_user_reply
      working — any task is in status "running"
      idle    — nothing else applies (default)

    "thinking" is reserved for finer-grained signals (e.g. mid-LLM-call) that
    the agent_base will eventually push as transient overrides. For now we
    collapse everything-LLM-busy into "working" since the task_manager doesn't
    distinguish.

    Defensive against a missing or partially-initialised task_manager — the
    heartbeat loop must not crash the agent if startup ordering changes.
    """
    if task_manager is None:
        return AGENT_STATE_IDLE

    tasks_attr = getattr(task_manager, "tasks", None)
    if not tasks_attr:
        return AGENT_STATE_IDLE

    # `tasks` is a dict[task_id -> Task] on the upstream TaskManager.
    try:
        all_tasks = list(tasks_attr.values()) if hasattr(tasks_attr, "values") else list(tasks_attr)
    except Exception:
        return AGENT_STATE_IDLE

    if not all_tasks:
        return AGENT_STATE_IDLE

    # Waiting beats working — a task that's blocked on the user is not actively
    # consuming LLM time even though its status is still "running".
    for t in all_tasks:
        if getattr(t, "status", None) == "running" and getattr(t, "waiting_for_user_reply", False):
            return AGENT_STATE_WAITING

    for t in all_tasks:
        if getattr(t, "status", None) == "running":
            return AGENT_STATE_WORKING

    # No running tasks. Surface "error" if the most recently ended task errored
    # within the last ~5 minutes; older errors are stale.
    recent_error = _has_recent_error(all_tasks, window_seconds=300)
    if recent_error:
        return AGENT_STATE_ERROR

    return AGENT_STATE_IDLE


def _has_recent_error(tasks: list, *, window_seconds: int) -> bool:
    """True iff any task ended with status="error" within the window.

    Best-effort — tolerates Task objects that don't carry ended_at, in which
    case we can't tell freshness and conservatively return False.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    for t in tasks:
        if getattr(t, "status", None) != "error":
            continue
        ended_at = getattr(t, "ended_at", None)
        if not ended_at:
            continue
        try:
            ts = _dt.datetime.fromisoformat(str(ended_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_dt.timezone.utc)
            if (now - ts).total_seconds() <= window_seconds:
                return True
        except Exception:
            continue
    return False


# ───────────────────────────────────────────────────────────────────────────
# Dashboard pull endpoints — assemblers for GET /__cb/state and /__cb/events.
# ───────────────────────────────────────────────────────────────────────────


def _current_task_brief(task_manager: Any) -> Optional[Dict[str, Any]]:
    """The running task's id + name, or None when nothing is running. Returned
    as a small dict because the dashboard only needs to label the screen, not
    render the full task object."""
    if task_manager is None:
        return None
    tasks_attr = getattr(task_manager, "tasks", None)
    if not tasks_attr:
        return None
    try:
        all_tasks = list(tasks_attr.values()) if hasattr(tasks_attr, "values") else list(tasks_attr)
    except Exception:
        return None
    for t in all_tasks:
        if getattr(t, "status", None) == "running":
            return {
                "id": getattr(t, "id", None),
                "name": getattr(t, "name", None),
            }
    return None


def _read_system_metrics() -> Dict[str, Any]:
    """CPU / memory / disk percentages from the existing metrics collector.
    Returns zeros when psutil is unavailable so the dashboard can render
    placeholder bars without special-casing missing data."""
    try:
        import psutil  # type: ignore
    except Exception:
        return {"cpuPct": 0.0, "memPct": 0.0, "diskPct": 0.0, "diskUsedGb": 0.0, "diskTotalGb": 0.0}

    # interval=None makes cpu_percent non-blocking; the first call after import
    # returns 0.0, subsequent calls return the delta since the previous call.
    # That's fine — the dashboard polls every few seconds, so it warms quickly.
    try:
        cpu_pct = float(psutil.cpu_percent(interval=None))
    except Exception:
        cpu_pct = 0.0
    try:
        mem = psutil.virtual_memory()
        mem_pct = float(mem.percent)
    except Exception:
        mem_pct = 0.0
    try:
        disk = psutil.disk_usage("/")
        disk_pct = float(disk.percent)
        disk_used_gb = round(disk.used / (1024**3), 2)
        disk_total_gb = round(disk.total / (1024**3), 2)
    except Exception:
        disk_pct = 0.0
        disk_used_gb = 0.0
        disk_total_gb = 0.0

    return {
        "cpuPct": cpu_pct,
        "memPct": mem_pct,
        "diskPct": disk_pct,
        "diskUsedGb": disk_used_gb,
        "diskTotalGb": disk_total_gb,
    }


def build_state_snapshot(task_manager: Any) -> Dict[str, Any]:
    """Body for `GET /__cb/state`. Cheap to compute — meant to be polled at
    a few-second cadence."""
    return {
        "agentState": derive_agent_state(task_manager),
        "currentTask": _current_task_brief(task_manager),
        "uptimeSeconds": process_uptime_seconds(),
        "system": _read_system_metrics(),
    }


def _serialise_event(rec: Any) -> Optional[Dict[str, Any]]:
    """Map an EventRecord to the dashboard's event JSON shape.

    The dashboard renders a compact activity feed: one row per record, with
    `displayMessage` preferred over `message` when present. We pass the full
    `message` too so the user can hover/inspect.

    Returns None for malformed records — the caller filters them out rather
    than crash the whole response on one bad event.
    """
    try:
        ev = getattr(rec, "event", None)
        if ev is None:
            return None
        ts = getattr(rec, "ts", None) or getattr(ev, "ts", None)
        if ts is None:
            return None
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        return {
            "kind": getattr(ev, "kind", ""),
            "message": getattr(ev, "message", ""),
            "displayMessage": getattr(ev, "display_message", None),
            "severity": getattr(ev, "severity", "INFO"),
            "ts": ts_iso,
            "repeatCount": int(getattr(rec, "repeat_count", 1) or 1),
        }
    except Exception:
        return None


def build_events_snapshot(
    event_stream_manager: Any,
    *,
    since_iso: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Body for `GET /__cb/events`. Returns up to `limit` events across all
    task streams, newest last (so the dashboard can render top-down and let
    the latest event float to the top of the list).

    `since_iso` lets the dashboard ask for "everything after the last event
    I saw" — saves bandwidth on poll, and avoids the dashboard having to
    de-dupe by ts/kind/message on the client.
    """
    if event_stream_manager is None:
        return {"events": []}

    # Best-effort timestamp parse; bad inputs are treated as "no filter".
    since_ts: Optional[_dt.datetime] = None
    if since_iso:
        try:
            since_ts = _dt.datetime.fromisoformat(since_iso)
            if since_ts.tzinfo is None:
                since_ts = since_ts.replace(tzinfo=_dt.timezone.utc)
        except Exception:
            since_ts = None

    # Pull tail_events from every task stream the manager knows about. We can't
    # assume a single canonical stream — multi-tasking agents have one per task.
    streams_attr = getattr(event_stream_manager, "_task_streams", None)
    if not streams_attr:
        return {"events": []}
    try:
        streams = list(streams_attr.values()) if hasattr(streams_attr, "values") else list(streams_attr)
    except Exception:
        return {"events": []}

    collected: List[Dict[str, Any]] = []
    for s in streams:
        tail = getattr(s, "tail_events", None)
        if not tail:
            continue
        for rec in tail:
            item = _serialise_event(rec)
            if item is None:
                continue
            if since_ts is not None:
                try:
                    rec_ts = _dt.datetime.fromisoformat(item["ts"])
                    if rec_ts.tzinfo is None:
                        rec_ts = rec_ts.replace(tzinfo=_dt.timezone.utc)
                    if rec_ts <= since_ts:
                        continue
                except Exception:
                    pass
            collected.append(item)

    # Sort by ts ascending, then trim to the most recent `limit` so the cap
    # is on the *newest* events. Clamp `limit` to a sane upper bound.
    collected.sort(key=lambda e: e.get("ts", ""))
    effective_limit = max(1, min(int(limit or 50), 500))
    if len(collected) > effective_limit:
        collected = collected[-effective_limit:]

    return {"events": collected}
