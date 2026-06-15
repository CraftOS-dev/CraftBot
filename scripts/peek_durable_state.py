# -*- coding: utf-8 -*-
"""Dev helper: print the durable-execution state (triggers + activity ledger).

Usage (from repo root, app can be running — WAL allows concurrent reads):
    python scripts/peek_durable_state.py            # both tables
    python scripts/peek_durable_state.py triggers   # one table
    python scripts/peek_durable_state.py activity
"""

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "app" / "data" / ".usage" / "sessions.db"


def show(title: str, query: str) -> None:
    print(f"\n=== {title} ===")
    try:
        with sqlite3.connect(DB) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError as e:
        print(f"({e} — start the app once so the table is created)")
        return
    if not rows:
        print("(empty)")
        return
    for r in rows:
        print(" | ".join(f"{k}={r[k]}" for k in r.keys()))


which = sys.argv[1] if len(sys.argv) > 1 else "all"

if which in ("all", "triggers"):
    show(
        f"triggers (newest 20) — {DB}",
        """
        SELECT id, source, session_id, status, resolution, attempts,
               dedup_key, substr(description, 1, 50) AS description
        FROM triggers ORDER BY id DESC LIMIT 20
        """,
    )
    show(
        "triggers by status",
        "SELECT status, COUNT(*) AS count FROM triggers GROUP BY status",
    )

if which in ("all", "activity"):
    show(
        "activity_log (newest 10)",
        """
        SELECT substr(idem_key, 1, 40) AS idem_key, action, status,
               provider_ref, updated_at
        FROM activity_log ORDER BY updated_at DESC LIMIT 10
        """,
    )
