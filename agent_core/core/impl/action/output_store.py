# -*- coding: utf-8 -*-
"""
ActionOutputStore — deterministic per-action persistence.

Every action invocation writes exactly one JSON file at a stable, predictable
path. The store is intentionally minimal: write-only ``record(...)`` for the
manager, ``load(...)`` for the ref resolver, no caching, no in-process
manifest, no compaction. Determinism is the point.

Layout:
    agent_file_system/action_outputs/
        {session_id}/
            {action_name}__{short_run_id}.json

Each file:
    {
      "key":          "<action_name>#<short_run_id>",
      "session_id":   "...",
      "action_name":  "...",
      "run_id":       "...",
      "short_run_id": "<6 hex>",
      "started_at":   "...",
      "ended_at":     "...",
      "status":       "success" | "error" | ...,
      "outputs":      <the action's output dict>
    }

Reads happen via ``load(session_id, key)`` — the manager's ref resolver uses
this when an action parameter contains ``{"$ref": "<key>", "path": "..."}``.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from agent_core.utils.logger import logger


_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")
SHORT_RUN_ID_LEN = 6


def _safe_filename(name: str) -> str:
    return _FILENAME_SAFE.sub("_", name)[:120] or "_"


def make_short_run_id(run_id: str) -> str:
    """Stable 6-hex prefix of a UUID-style run id; used in keys and filenames."""
    cleaned = (run_id or "").replace("-", "")
    if cleaned:
        return cleaned[:SHORT_RUN_ID_LEN]
    return uuid.uuid4().hex[:SHORT_RUN_ID_LEN]


def make_key(action_name: str, run_id: str) -> str:
    """Compose the stable reference key used in ``$ref`` and the manifest."""
    return f"{action_name}#{make_short_run_id(run_id)}"


@dataclass(frozen=True)
class ActionOutputRecord:
    """Immutable on-disk record of a single action invocation."""

    key: str
    session_id: str
    action_name: str
    run_id: str
    short_run_id: str
    started_at: str
    ended_at: str
    status: str
    outputs: Dict[str, Any]


class ActionOutputStore:
    """Per-session deterministic archive of action outputs."""

    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        session_id: str,
        action_name: str,
        run_id: str,
        outputs: Dict[str, Any],
        started_at: str,
        ended_at: str,
        status: str,
    ) -> Optional[ActionOutputRecord]:
        """Persist a single action invocation. Returns the record, or ``None``."""
        if not session_id:
            return None

        try:
            short_run_id = make_short_run_id(run_id)
            record = ActionOutputRecord(
                key=f"{action_name}#{short_run_id}",
                session_id=session_id,
                action_name=action_name,
                run_id=run_id,
                short_run_id=short_run_id,
                started_at=started_at,
                ended_at=ended_at,
                status=status,
                outputs=outputs if isinstance(outputs, dict) else {"value": outputs},
            )

            session_dir = self._session_dir(session_id)
            session_dir.mkdir(parents=True, exist_ok=True)

            record_path = session_dir / self._record_filename(action_name, run_id)
            record_path.write_text(
                json.dumps(asdict(record), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            return record
        except Exception as exc:
            logger.warning(
                f"[ActionOutputStore] Failed to record {action_name} "
                f"(run_id={run_id}, session_id={session_id}): {exc}"
            )
            return None

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self, session_id: str, key: str) -> Optional[ActionOutputRecord]:
        """Load a record by its ``{action_name}#{short_run_id}`` key."""
        if not session_id or not key or "#" not in key:
            return None

        action_name, short_run_id = key.rsplit("#", 1)
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return None

        # Filenames are ``{action_name}__{full_run_id}.json``; the key only has
        # the short_run_id, so scan the directory for a matching prefix.
        safe_action = _safe_filename(action_name)
        prefix = f"{safe_action}__"
        match: Optional[Path] = None
        for entry in session_dir.iterdir():
            if not entry.name.startswith(prefix) or not entry.name.endswith(".json"):
                continue
            run_id_part = entry.name[len(prefix) : -len(".json")]
            if make_short_run_id(run_id_part) == short_run_id:
                match = entry
                break
        if match is None:
            return None

        try:
            data = json.loads(match.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[ActionOutputStore] Failed to load {match}: {exc}")
            return None

        try:
            return ActionOutputRecord(
                key=data["key"],
                session_id=data.get("session_id", session_id),
                action_name=data["action_name"],
                run_id=data["run_id"],
                short_run_id=data["short_run_id"],
                started_at=data["started_at"],
                ended_at=data["ended_at"],
                status=data["status"],
                outputs=data.get("outputs", {}),
            )
        except KeyError as exc:
            logger.warning(f"[ActionOutputStore] Record {match} missing field: {exc}")
            return None

    def record_path(self, session_id: str, action_name: str, run_id: str) -> Path:
        """Return the on-disk path a record would be (or was) written to."""
        return self._session_dir(session_id) / self._record_filename(
            action_name, run_id
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        return self.root / _safe_filename(session_id)

    @staticmethod
    def _record_filename(action_name: str, run_id: str) -> str:
        return f"{_safe_filename(action_name)}__{run_id}.json"
