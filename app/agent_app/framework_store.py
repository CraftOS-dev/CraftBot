"""CraftBot presentation/job receipts only. App state stays in Agent-App."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.paths import STATE_ROOT


class HostStore:
    def __init__(self, path: Path | None = None):
        self.path = path or STATE_ROOT / "agent-app-host.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipts (kind TEXT, key TEXT, value TEXT NOT NULL, PRIMARY KEY(kind,key))"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, kind: str, key: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM receipts WHERE kind=? AND key=?", (kind, key)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind: str, key: str, value: dict):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO receipts VALUES (?,?,?)",
                (kind, key, json.dumps(value)),
            )

    def insert(self, kind: str, key: str, value: dict) -> bool:
        with self.connect() as db:
            return (
                db.execute(
                    "INSERT OR IGNORE INTO receipts VALUES (?,?,?)",
                    (kind, key, json.dumps(value)),
                ).rowcount
                == 1
            )

    def delete(self, kind: str, key: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM receipts WHERE kind=? AND key=?", (kind, key))

    def all(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT value FROM receipts WHERE kind=? ORDER BY rowid", (kind,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


def app_key(home: Path, path: str, app_id: str) -> str:
    # The profile and path disambiguate independent copies of the same app ID.
    from app.agent_app.framework_connections import is_connection
    return json.dumps([str(home.resolve()), path if is_connection(path) else str(Path(path).resolve()), app_id])
