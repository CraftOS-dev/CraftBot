"""Data retention (Settings > Security > Secrets and data).

With a retention period set (90 days at Enhanced, 30 at Strict), CraftBot
deletes diagnostic records older than that: log files and the recorded LLM
calls (prompts and responses kept for debugging). Chats, memory and the
security audit log are never deleted by this: they are the user's data or
the record auditors need.

Runs once at startup and then every few hours on a background thread.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from agent_core.utils.logger import logger
from app.security.policy import get_policy

_INTERVAL_S = 6 * 3600
_started = False


def prune(days: int, *, logs_dir: Optional[Path] = None, now: Optional[datetime] = None) -> Dict[str, int]:
    if days <= 0:
        return {}
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    removed = {"log_files": 0, "llm_calls": 0}

    if logs_dir is None:
        from app.config import PROJECT_ROOT

        logs_dir = Path(PROJECT_ROOT) / "logs"
    if logs_dir.is_dir():
        limit = cutoff.timestamp()
        for path in logs_dir.rglob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < limit:
                    path.unlink()
                    removed["log_files"] += 1
            except OSError:
                continue

    try:
        from app.usage.llm_call_storage import get_llm_call_storage

        removed["llm_calls"] = get_llm_call_storage().delete_older_than(cutoff)
    except Exception as exc:
        logger.warning(f"[SECURITY] Retention could not prune LLM calls: {exc}")
    return removed


def _loop() -> None:
    while True:
        try:
            days = get_policy().retention_days
            if days > 0:
                removed = prune(days)
                if any(removed.values()):
                    logger.info(f"[SECURITY] Retention removed {removed}")
                    from app.security import audit

                    audit.record_if_enabled("retention_pruned", days=days, **removed)
        except Exception as exc:
            logger.warning(f"[SECURITY] Retention run failed: {exc}")
        time.sleep(_INTERVAL_S)


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="security-retention", daemon=True).start()
