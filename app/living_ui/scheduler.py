# -*- coding: utf-8 -*-
"""
Scheduled operations for Living UI projects.

An op in config/operations.json may declare a "schedule":

    "daily_digest": {
      "description": "Email me a summary of open tasks every morning.",
      "params": {},
      "executor": {"type": "http", "method": "POST", "path": "/api/digest/send"},
      "mode": "sync",
      "schedule": "daily 09:00"
    }

Supported forms (parsed here, declared by the agent like everything else):
    "every 15m" / "every 2h"   — fixed interval
    "daily HH:MM"              — once per day at local time
    "hourly"                   — shorthand for "every 1h"

The platform runs due ops only while the project is RUNNING (its backend
must be up for http/sql executors to mean anything). Last-run state lives
in <project>/logs/schedule_state.json and results append to
<project>/logs/schedule.log — both visible to the agent for debugging.
Failures are logged, never raised; a broken schedule must not hurt the app.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from . import data_plane, operations

if TYPE_CHECKING:
    from .manager import LivingUIManager, LivingUIProject

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

TICK_SECONDS = 60

_EVERY_RE = re.compile(r"^every\s+(\d+)\s*(m|min|minutes?|h|hours?)$", re.I)
_DAILY_RE = re.compile(r"^daily\s+([01]?\d|2[0-3]):([0-5]\d)$", re.I)


def parse_schedule(spec: Any) -> Optional[Dict[str, Any]]:
    """Parse a schedule string. Returns {"kind": ..., ...} or None."""
    if not isinstance(spec, str) or not spec.strip():
        return None
    text = spec.strip().lower()
    if text == "hourly":
        return {"kind": "every", "seconds": 3600}
    m = _EVERY_RE.match(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)[0]
        seconds = n * (60 if unit == "m" else 3600)
        # Below one tick nothing can fire more often anyway.
        return {"kind": "every", "seconds": max(seconds, TICK_SECONDS)}
    m = _DAILY_RE.match(text)
    if m:
        return {"kind": "daily", "hour": int(m.group(1)), "minute": int(m.group(2))}
    return None


def is_due(
    schedule: Dict[str, Any], last_run: Optional[datetime], now: datetime
) -> bool:
    """Whether a schedule should fire at `now` given its last run."""
    if schedule["kind"] == "every":
        if last_run is None:
            return True
        return (now - last_run).total_seconds() >= schedule["seconds"]
    if schedule["kind"] == "daily":
        target = now.replace(
            hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0
        )
        if now < target:
            return False
        return last_run is None or last_run < target
    return False


def _state_path(project: "LivingUIProject") -> Path:
    return Path(project.path) / "logs" / "schedule_state.json"


def _load_state(project: "LivingUIProject") -> Dict[str, str]:
    try:
        return json.loads(_state_path(project).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(project: "LivingUIProject", state: Dict[str, str]) -> None:
    try:
        path = _state_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError as e:
        logger.warning(f"[LIVING_UI:SCHED] could not save state: {e}")


def _log_result(project: "LivingUIProject", line: str) -> None:
    try:
        log = Path(project.path) / "logs" / "schedule.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {line}\n")
    except OSError:
        pass


def execute_op(
    project: "LivingUIProject", op_name: str, op_def: Dict[str, Any]
) -> Tuple[bool, str]:
    """Run one declared op with its default params (schedules carry no
    per-run params — defaults must satisfy the op). Mirrors the CLI's
    executor dispatch. Returns (ok, summary)."""
    filled = operations.validate_and_fill_params(op_name, op_def, {})
    executor = op_def.get("executor") or {}
    executor_type = str(executor.get("type", "http")).lower()

    if executor_type == "http":
        if not project.backend_port:
            return False, "backend port unknown"
        method = str(executor.get("method", "POST")).upper()
        path, remaining = operations.render_http_path(
            executor.get("path", "/api/action"), filled
        )
        static_body = (
            executor.get("body") if isinstance(executor.get("body"), dict) else {}
        )
        url = f"http://127.0.0.1:{project.backend_port}{path}"
        body = {**static_body, **remaining}
        if method in ("GET", "DELETE"):
            from urllib.parse import urlencode

            if body:
                url += "?" + urlencode(body)
            req = urllib.request.Request(url, method=method)
        else:
            req = urllib.request.Request(
                url,
                method=method,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return True, f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            return False, f"HTTP {e.code}: {detail or e.reason}"
        except Exception as e:
            return False, f"http error: {e}"

    if executor_type == "sql":
        source = data_plane.resolve_db_path(project)
        if not source:
            return False, "no database"
        write = str(executor.get("mode", "read")).lower() == "write"
        try:
            result = data_plane.run_sql(
                source, executor.get("sql", ""), filled, write=write
            )
        except data_plane.DataPlaneError as e:
            return False, f"sql error: {e}"
        return True, (
            f"affected {result.get('affected')}"
            if write
            else f"returned {result.get('returned')} rows"
        )

    if executor_type == "shell":
        try:
            command = operations.render_shell_command(executor.get("cmd", ""), filled)
            cwd = operations.resolve_op_cwd(Path(project.path), executor)
        except operations.OperationError as e:
            return False, str(e)
        extra_env = (
            executor.get("env") if isinstance(executor.get("env"), dict) else None
        )
        timeout = float(executor.get("timeout", 300))
        try:
            result = operations.run_shell_sync(
                command, cwd, timeout=timeout, extra_env=extra_env
            )
        except operations.OperationError as e:
            return False, str(e)
        ok = result["return_code"] == 0
        tail = (result["stderr"] or result["stdout"] or "").strip()[-200:]
        return ok, f"exit {result['return_code']}" + (f" · {tail}" if tail else "")

    return False, f"unsupported executor type '{executor_type}'"


class ScheduleRunner:
    """Fires declared op schedules for running projects. One instance per
    manager; started/stopped alongside the watchdog."""

    def __init__(self, manager: "LivingUIManager"):
        self._manager = manager
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("[LIVING_UI:SCHED] Schedule runner started")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(TICK_SECONDS)
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.warning(f"[LIVING_UI:SCHED] tick failed: {e}")
            await asyncio.sleep(TICK_SECONDS)

    async def _tick(self) -> None:
        now = datetime.now()
        for project in list(self._manager.projects.values()):
            if project.status != "running" or project.project_type != "native":
                continue
            try:
                ops = operations.load_operations(project)
            except operations.OperationError:
                continue
            scheduled = {
                name: (op_def, parse_schedule(op_def.get("schedule")))
                for name, op_def in ops.items()
                if op_def.get("schedule")
            }
            if not scheduled:
                continue
            state = _load_state(project)
            changed = False
            for name, (op_def, schedule) in scheduled.items():
                if schedule is None:
                    _log_result(
                        project,
                        f"{name}: SKIPPED — unsupported schedule "
                        f"'{op_def.get('schedule')}' (use 'every Nm', 'every Nh', "
                        f"'hourly', or 'daily HH:MM')",
                    )
                    continue
                last_raw = state.get(name)
                last_run = None
                if last_raw:
                    try:
                        last_run = datetime.fromisoformat(last_raw)
                    except ValueError:
                        pass
                if not is_due(schedule, last_run, now):
                    continue
                # Record BEFORE running so a hanging op can't fire every tick.
                state[name] = now.isoformat(timespec="seconds")
                changed = True
                try:
                    ok, summary = await asyncio.to_thread(
                        execute_op, project, name, op_def
                    )
                except Exception as e:
                    ok, summary = False, f"executor crashed: {e}"
                _log_result(project, f"{name}: {'OK' if ok else 'FAILED'} — {summary}")
                if not ok:
                    logger.warning(
                        f"[LIVING_UI:SCHED] {project.name} ({project.id}) "
                        f"op '{name}' failed: {summary}"
                    )
            if changed:
                _save_state(project, state)
