"""
Living UI Backend Health Checker

Background thread that periodically verifies the backend is healthy.
Checks both the HTTP health endpoint and database connectivity.
Writes status to logs/health_status.json for the manager watchdog to read.
Self-terminates if too many consecutive failures occur.
"""

import json
import logging
import os
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent / "logs"

_checker_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Number of consecutive failures before self-terminating
MAX_CONSECUTIVE_FAILURES = 5
CHECK_INTERVAL_SECONDS = 60
HEALTH_STATUS_FILE = LOG_DIR / "health_status.json"


def _write_status(
    health_ok: bool,
    db_ok: bool,
    consecutive_failures: int,
    error: str | None = None,
):
    """Write current health status to JSON file for external monitoring."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    status = {
        "last_check": datetime.now().isoformat(),
        "health_endpoint": "ok" if health_ok else "fail",
        "db_connectivity": "ok" if db_ok else "fail",
        "consecutive_failures": consecutive_failures,
        "error": error,
    }
    try:
        HEALTH_STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[HealthChecker] Failed to write status file: {e}")


def _check_health_endpoint(port: int) -> bool:
    """Hit the local /health endpoint."""
    try:
        url = f"http://localhost:{port}/health"
        resp = urllib.request.urlopen(url, timeout=5)
        return resp.status == 200
    except Exception:
        return False


def _check_db() -> bool:
    """Verify database connectivity with a simple query."""
    try:
        from sqlalchemy import text
        from database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _run_checker(port: int):
    """Main checker loop running in a background thread."""
    consecutive_failures = 0

    # Wait a bit before first check to let the server fully start
    if _stop_event.wait(timeout=15):
        return

    logger.info(
        f"[HealthChecker] Started - checking every {CHECK_INTERVAL_SECONDS}s "
        f"(max {MAX_CONSECUTIVE_FAILURES} consecutive failures before exit)"
    )

    while not _stop_event.is_set():
        health_ok = _check_health_endpoint(port)
        db_ok = _check_db()

        if health_ok and db_ok:
            if consecutive_failures > 0:
                logger.info(
                    f"[HealthChecker] Recovered after {consecutive_failures} failure(s)"
                )
            consecutive_failures = 0
            _write_status(health_ok, db_ok, consecutive_failures)
        else:
            consecutive_failures += 1
            error_parts = []
            if not health_ok:
                error_parts.append("health endpoint not responding")
            if not db_ok:
                error_parts.append("database connectivity failed")
            error_msg = "; ".join(error_parts)

            logger.warning(
                f"[HealthChecker] Check failed ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {error_msg}"
            )
            _write_status(health_ok, db_ok, consecutive_failures, error=error_msg)

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.critical(
                    f"[HealthChecker] {MAX_CONSECUTIVE_FAILURES} consecutive failures - "
                    f"self-terminating. Last error: {error_msg}"
                )
                _write_status(
                    health_ok,
                    db_ok,
                    consecutive_failures,
                    error=f"SELF-TERMINATED: {error_msg}",
                )
                # Hard exit so the manager watchdog detects the crash and can restart
                os._exit(1)

        _stop_event.wait(timeout=CHECK_INTERVAL_SECONDS)


def start_health_checker(port: int):
    """Start the background health checker thread."""
    global _checker_thread

    if _checker_thread is not None and _checker_thread.is_alive():
        logger.warning("[HealthChecker] Already running")
        return

    _stop_event.clear()
    _checker_thread = threading.Thread(
        target=_run_checker, args=(port,), daemon=True, name="health-checker"
    )
    _checker_thread.start()
    logger.info(f"[HealthChecker] Starting for port {port}")


def stop_health_checker():
    """Stop the background health checker thread."""
    global _checker_thread

    if _checker_thread is None:
        return

    _stop_event.set()
    _checker_thread.join(timeout=5)
    _checker_thread = None
    logger.info("[HealthChecker] Stopped")
