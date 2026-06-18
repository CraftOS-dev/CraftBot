# -*- coding: utf-8 -*-
"""
app.usage.llm_call_storage

SQLite store of full LLM calls (prompt + response + identity + latency) for the
prompt profiler and eval-case harvesting (see docs/design/prompt-optimization.md).

This is the capture substrate: one `llm_calls` row per LLM call holds everything
the profiler aggregates, the eval harness harvests, and the self-improvement loop
compares. It is intentionally separate from `usage.db` (token accounting only) —
this table stores full prompt/response text, so it stays local-only and is
size-capped.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Keep the table bounded — full prompts/responses are large. Oldest rows are
# pruned past this cap on insert.
DEFAULT_MAX_ROWS = 50_000


@dataclass
class LLMCallRow:
    """A persisted LLM call. Mirrors agent_core hooks.LLMCallRecord plus a
    timestamp; kept as its own type so storage doesn't import the hook layer."""

    provider: str
    model: str
    system_prompt: Optional[str]
    user_prompt: str
    response: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0  # served FROM cache (read)
    cache_creation_tokens: int = 0  # WRITTEN to cache
    latency_ms: int = 0
    prompt_name: Optional[str] = None
    prompt_version: Optional[str] = None
    call_type: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}


class LLMCallStorage:
    """SQLite-backed store of full LLM calls."""

    def __init__(self, db_path: Optional[str] = None, max_rows: int = DEFAULT_MAX_ROWS):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "llm_calls.db")

        self._db_path = db_path
        self._max_rows = max_rows
        self._init_db()
        logger.info(f"[LLMCallStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_name TEXT,
                    prompt_version TEXT,
                    call_type TEXT,
                    task_id TEXT,
                    session_id TEXT,
                    system_prompt TEXT,
                    user_prompt TEXT,
                    response TEXT,
                    status TEXT NOT NULL DEFAULT 'success',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT
                )
            """)
            # Migrate older DBs that predate a column.
            existing = {r[1] for r in cursor.execute("PRAGMA table_info(llm_calls)")}
            for col, decl in (("cache_creation_tokens", "INTEGER NOT NULL DEFAULT 0"),):
                if col not in existing:
                    cursor.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {decl}")
            for col in ("timestamp", "prompt_name", "call_type", "task_id", "model"):
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_llm_calls_{col} "
                    f"ON llm_calls({col})"
                )
            conn.commit()

    def insert(self, row: LLMCallRow) -> int:
        """Insert one call. Returns its row id. Prunes oldest rows past the cap."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO llm_calls
                (timestamp, provider, model, prompt_name, prompt_version,
                 call_type, task_id, session_id, system_prompt, user_prompt,
                 response, status, input_tokens, output_tokens, cached_tokens,
                 cache_creation_tokens, latency_ms, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (row.timestamp or datetime.now()).isoformat(),
                    row.provider,
                    row.model,
                    row.prompt_name,
                    row.prompt_version,
                    row.call_type,
                    row.task_id,
                    row.session_id,
                    row.system_prompt,
                    row.user_prompt,
                    row.response,
                    row.status,
                    row.input_tokens,
                    row.output_tokens,
                    row.cached_tokens,
                    row.cache_creation_tokens,
                    row.latency_ms,
                    json.dumps(row.metadata) if row.metadata else None,
                ),
            )
            row_id = cursor.lastrowid
            self._prune(cursor)
            conn.commit()
            return row_id

    def _prune(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("SELECT COUNT(*) FROM llm_calls")
        count = cursor.fetchone()[0]
        if count > self._max_rows:
            cursor.execute(
                """
                DELETE FROM llm_calls WHERE id IN (
                    SELECT id FROM llm_calls ORDER BY id ASC LIMIT ?
                )
                """,
                (count - self._max_rows,),
            )

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent calls as dicts (newest first)."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM llm_calls ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def count(self) -> int:
        with sqlite3.connect(self._db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]


# Global storage instance
_llm_call_storage: Optional[LLMCallStorage] = None


def get_llm_call_storage() -> LLMCallStorage:
    """Get the global LLM call storage instance."""
    global _llm_call_storage
    if _llm_call_storage is None:
        _llm_call_storage = LLMCallStorage()
    return _llm_call_storage
