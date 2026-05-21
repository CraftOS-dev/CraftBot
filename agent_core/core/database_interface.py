# -*- coding: utf-8 -*-
"""app.database_interface

A filesystem backed storage layer so the rest of the codebase never
talks to persistence details directly.
"""

from __future__ import annotations

import datetime
import json
import re

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.utils.logger import logger
from agent_core.core.action_framework.registry import registry_instance
from agent_core.core.action_framework.loader import load_actions_from_directories


class DatabaseInterface:
    """All persistence operations for the agent live here."""

    def __init__(
        self,
        *,
        data_dir: str = "app/data",
        chroma_path: str = "./chroma_db",
    ) -> None:
        """
        Initialize storage directories for agent data.

        The constructor sets up filesystem paths for actions, task
        documents, and agent info. Actions are loaded from directories into
        the in-memory registry.

        Args:
            data_dir: Base directory used to persist JSON artifacts.
            chroma_path: Unused (kept for backward compatibility).
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.actions_dir = self.data_dir / "action"
        self.task_docs_dir = self.data_dir / "task_document"
        self.agent_info_path = self.data_dir / "agent_info.json"

        self.actions_dir.mkdir(parents=True, exist_ok=True)
        self.task_docs_dir.mkdir(parents=True, exist_ok=True)
        if not self.agent_info_path.exists():
            self.agent_info_path.write_text("{}", encoding="utf-8")

        # Load actions from directories into registry (no ChromaDB sync - deprecated)
        load_actions_from_directories(paths_to_scan=[str(self.actions_dir)])

        # Log action count
        actions = registry_instance.list_all_actions_as_json()
        action_names = [a.get("name") for a in actions if a.get("name")]
        logger.info(
            f"Action registry loaded. {len(action_names)} actions available: [{', '.join(sorted(action_names))}]"
        )

    # ------------------------------------------------------------------
    # Action definitions (filesystem + Chroma)
    # ------------------------------------------------------------------
    def _sanitize_action_filename(self, name: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", name).strip("_") or "action"
        return f"{sanitized}.json"

    def _load_actions_from_disk(self) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        for path in self.actions_dir.glob("*.json"):
            try:
                actions.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning(f"[ACTION LOAD] Failed to read {path}: {exc}")
        return actions

    def store_action(self, action_dict: Dict[str, Any]) -> None:
        """
        Persist an action definition to disk.

        Args:
            action_dict: Action payload to store, expected to include a ``name``
                field used for the filename.
        """
        action_dict["updatedAt"] = datetime.datetime.utcnow().isoformat()
        file_name = self._sanitize_action_filename(action_dict["name"])
        path = self.actions_dir / file_name
        path.write_text(
            json.dumps(action_dict, indent=2, default=str), encoding="utf-8"
        )

    def list_actions(
        self,
        *,
        default: bool | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Return stored actions optionally filtered by the ``default`` flag.

        Args:
            default: When provided, only return actions whose ``default`` field
                matches the boolean value.

        Returns:
            List of action dictionaries stored on disk that satisfy the filter.
        """
        actions = registry_instance.list_all_actions_as_json()

        if default is not None:
            actions = [action for action in actions if action.get("default") == default]

        return actions

    def get_action(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a stored action by case-insensitive name match.

        Args:
            name: The human-readable name used to identify the action.

        Returns:
            The action dictionary when found, otherwise ``None``.
        """
        action = registry_instance.find_action_by_name(action_name=name)
        return action

    def delete_action(self, name: str) -> None:
        """
        Remove an action definition from disk.

        Args:
            name: Name of the action to delete.
        """
        for path in self.actions_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("name") == name:
                path.unlink(missing_ok=True)
                break

    # ------------------------------------------------------------------
    # Agent configuration
    # ------------------------------------------------------------------
    def set_agent_info(self, info: Dict[str, Any], key: str = "singleton") -> None:
        """
        Persist arbitrary agent configuration under the provided key.

        Args:
            info: Mapping of configuration fields to store.
            key: Logical namespace under which the configuration is saved.
        """
        try:
            existing = json.loads(self.agent_info_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        existing[key] = {**existing.get(key, {}), **info}
        self.agent_info_path.write_text(
            json.dumps(existing, indent=2), encoding="utf-8"
        )

    def get_agent_info(self, key: str = "singleton") -> Optional[Dict[str, Any]]:
        """
        Load persisted agent configuration for the given key.

        Args:
            key: Namespace key used when persisting the configuration.

        Returns:
            A configuration dictionary when present, otherwise ``None``.
        """
        try:
            info = json.loads(self.agent_info_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return info.get(key)

    # ------------------------------------------------------------------
    # Task documents (filesystem + Chroma)
    # ------------------------------------------------------------------
    def _extract_task_document_metadata(
        self, raw_text: str, fallback_name: str
    ) -> tuple[str, str]:
        name: Optional[str] = None
        description: Optional[str] = None
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.startswith("name:") and not name:
                name = stripped.split(":", 1)[1].strip() or None
            elif lowered.startswith("description:") and not description:
                description = stripped.split(":", 1)[1].strip() or None
            if name and description:
                break

        if not name:
            name = fallback_name
        if not description:
            first_para = next(
                (blk.strip() for blk in raw_text.split("\n\n") if blk.strip()), ""
            )
            description = first_para[:400]
        return name, description

    def _load_task_documents_from_disk(self) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        for path in sorted(self.task_docs_dir.glob("*.txt")):
            try:
                raw_text = path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning(f"[TASKDOC LOAD] Failed to read {path}: {exc}")
                continue

            name, description = self._extract_task_document_metadata(
                raw_text, path.stem
            )
            docs.append(
                {
                    "task_id": path.stem,
                    "name": name,
                    "description": description,
                    "raw_text": raw_text,
                    "source_path": str(path),
                }
            )
        return docs
