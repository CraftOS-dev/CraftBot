# -*- coding: utf-8 -*-
"""app.database_interface

A filesystem backed storage layer so the rest of the codebase never
talks to persistence details directly.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agent_core.utils.logger import logger
from agent_core.core.task.task import Task
from agent_core.core.action_framework.registry import registry_instance
from agent_core.core.action_framework.loader import load_actions_from_directories


class DatabaseInterface:
    """All persistence operations for the agent live here."""

    def __init__(
        self,
        *,
        data_dir: str = "app/data",
        chroma_path: str = "./chroma_db",
        log_file: Optional[str] = None,
    ) -> None:
        """
        Initialize storage directories for agent data.

        The constructor sets up filesystem paths for logs, actions, task
        documents, and agent info. Actions are loaded from directories into
        the in-memory registry.

        Args:
            data_dir: Base directory used to persist logs and JSON artifacts.
            chroma_path: Unused (kept for backward compatibility).
            log_file: Optional explicit log file path; defaults to
                ``<data_dir>/agent_logs.txt`` when omitted.
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.log_file_path = Path(log_file) if log_file else self.data_dir / "agent_logs.txt"
        self.actions_dir = self.data_dir / "action"
        self.task_docs_dir = self.data_dir / "task_document"
        self.agent_info_path = self.data_dir / "agent_info.json"

        self.actions_dir.mkdir(parents=True, exist_ok=True)
        self.task_docs_dir.mkdir(parents=True, exist_ok=True)
        self.log_file_path.touch(exist_ok=True)
        if not self.agent_info_path.exists():
            self.agent_info_path.write_text("{}", encoding="utf-8")

        # Load actions from directories into registry (no ChromaDB sync - deprecated)
        load_actions_from_directories(paths_to_scan=[str(self.actions_dir)])

        # Log action count
        actions = registry_instance.list_all_actions_as_json()
        action_names = [a.get("name") for a in actions if a.get("name")]
        logger.info(f"Action registry loaded. {len(action_names)} actions available: [{', '.join(sorted(action_names))}]")

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------
    def _load_log_entries(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        try:
            with self.log_file_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning(f"[LOG PARSE] Skipping malformed line in {self.log_file_path}")
        except FileNotFoundError:
            pass
        return entries

    def _write_log_entries(self, entries: Iterable[Dict[str, Any]]) -> None:
        with self.log_file_path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, default=str) + "\n")

    def _append_log_entry(self, entry: Dict[str, Any]) -> None:
        with self.log_file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")

    # ------------------------------------------------------------------
    # Prompt logging & token usage helpers
    # ------------------------------------------------------------------
    def log_prompt(
        self,
        *,
        input_data: Dict[str, str],
        output: Optional[str],
        provider: str,
        model: str,
        config: Dict[str, Any],
        status: str,
        token_count_input: Optional[int] = None,
        token_count_output: Optional[int] = None,
    ) -> None:
        """
        Store a single prompt interaction with metadata and token counts.

        Each call appends a structured record to the log file so usage metrics
        and model behavior can be inspected later.

        Args:
            input_data: Serialized prompt inputs sent to the model provider.
            output: The raw model output string, if available.
            provider: Name of the LLM provider (e.g., OpenAI, Anthropic).
            model: Specific model identifier used for the request.
            config: Provider-specific configuration details for the call.
            status: Execution status for the prompt (e.g., ``"success"`` or
                ``"error"``).
            token_count_input: Optional token count for the prompt payload.
            token_count_output: Optional token count for the model response.
        """
        entry = {
            "entry_type": "prompt_log",
            "datetime": datetime.datetime.utcnow().isoformat(),
            "input": input_data,
            "output": output,
            "provider": provider,
            "model": model,
            "config": config,
            "status": status,
            "token_count_input": token_count_input,
            "token_count_output": token_count_output,
        }
        self._append_log_entry(entry)

    def _iter_prompt_logs(self) -> Iterable[Dict[str, Any]]:
        for entry in self._load_log_entries():
            if entry.get("entry_type") == "prompt_log":
                yield entry

    # ------------------------------------------------------------------
    # Action history logging
    # ------------------------------------------------------------------
    def upsert_action_history(
        self,
        run_id: str,
        *,
        session_id: str,
        parent_id: str | None,
        name: str,
        action_type: str,
        status: str,
        inputs: Dict[str, Any] | None,
        outputs: Dict[str, Any] | None,
        started_at: str | None,
        ended_at: str | None,
    ) -> None:
        """
        Insert or update an action execution history entry.

        The log is keyed by ``run_id``; repeated writes merge new details while
        preserving the initial ``startedAt`` value when absent.

        Args:
            run_id: Unique identifier for the action execution instance.
            session_id: Identifier for the session that triggered the action.
            parent_id: Optional run identifier for the parent action in a tree.
            name: Human-readable action name.
            action_type: Action type label; duplicated into ``type`` for
                backward compatibility.
            status: Current execution status.
            inputs: Serialized action inputs, if available.
            outputs: Serialized action outputs, if available.
            started_at: ISO timestamp for when execution began.
            ended_at: ISO timestamp for when execution completed.
        """
        entries = self._load_log_entries()
        payload = {
            "entry_type": "action_history",
            "runId": run_id,
            "sessionId": session_id,
            "parentId": parent_id,
            "name": name,
            "action_type": action_type,
            "type": action_type,
            "status": status,
            "inputs": inputs,
            "outputs": outputs,
            "startedAt": started_at,
            "endedAt": ended_at,
        }

        found = False
        for entry in entries:
            if entry.get("entry_type") == "action_history" and entry.get("runId") == run_id:
                entry["action_type"] = payload["action_type"]
                entry["type"] = payload["type"]
                entry.update({k: v for k, v in payload.items() if v is not None or k in {"inputs", "outputs"}})
                if entry.get("startedAt") is None:
                    entry["startedAt"] = started_at
                found = True
                break

        if not found:
            if payload["startedAt"] is None:
                payload["startedAt"] = datetime.datetime.utcnow().isoformat()
            entries.append(payload)

        self._write_log_entries(entries)

    # ------------------------------------------------------------------
    # Fast append-only action logging (for parallel execution)
    # ------------------------------------------------------------------
    def log_action_start(
        self,
        run_id: str,
        *,
        session_id: str | None,
        parent_id: str | None,
        name: str,
        action_type: str,
        inputs: Dict[str, Any] | None,
        started_at: str,
    ) -> None:
        """
        Fast O(1) append for action start - no file read/rewrite.

        This method only appends to the log file, avoiding the O(n) read/search/write
        pattern of upsert_action_history. Use this for parallel action execution.

        Args:
            run_id: Unique identifier for the action execution instance.
            session_id: Identifier for the session that triggered the action.
            parent_id: Optional run identifier for the parent action.
            name: Human-readable action name.
            action_type: Action type label.
            inputs: Serialized action inputs.
            started_at: ISO timestamp for when execution began.
        """
        entry = {
            "entry_type": "action_history",
            "runId": run_id,
            "sessionId": session_id,
            "parentId": parent_id,
            "name": name,
            "action_type": action_type,
            "type": action_type,
            "status": "running",
            "inputs": inputs,
            "outputs": None,
            "startedAt": started_at,
            "endedAt": None,
        }
        self._append_log_entry(entry)

    def log_action_end(
        self,
        run_id: str,
        *,
        outputs: Dict[str, Any] | None,
        status: str,
        ended_at: str,
    ) -> None:
        """
        Fast O(1) append for action end - separate entry, no file rewrite.

        This method appends a completion record rather than updating the original
        start entry. The get_action_history method merges these records.

        Args:
            run_id: Unique identifier for the action execution instance.
            outputs: Serialized action outputs.
            status: Final execution status (success/error).
            ended_at: ISO timestamp for when execution completed.
        """
        entry = {
            "entry_type": "action_end",
            "runId": run_id,
            "status": status,
            "outputs": outputs,
            "endedAt": ended_at,
        }
        self._append_log_entry(entry)

    async def log_action_start_async(
        self,
        run_id: str,
        *,
        session_id: str | None,
        parent_id: str | None,
        name: str,
        action_type: str,
        inputs: Dict[str, Any] | None,
        started_at: str,
    ) -> None:
        """Async wrapper for log_action_start - runs file I/O in thread pool."""
        await asyncio.to_thread(
            self.log_action_start,
            run_id,
            session_id=session_id,
            parent_id=parent_id,
            name=name,
            action_type=action_type,
            inputs=inputs,
            started_at=started_at,
        )

    async def log_action_end_async(
        self,
        run_id: str,
        *,
        outputs: Dict[str, Any] | None,
        status: str,
        ended_at: str,
    ) -> None:
        """Async wrapper for log_action_end - runs file I/O in thread pool."""
        await asyncio.to_thread(
            self.log_action_end,
            run_id,
            outputs=outputs,
            status=status,
            ended_at=ended_at,
        )

    def _iter_action_history(self) -> Iterable[Dict[str, Any]]:
        for entry in self._load_log_entries():
            if entry.get("entry_type") == "action_history":
                yield entry

    def find_actions_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        Return all action history entries matching the given status.

        Args:
            status: Status value to filter (e.g., ``"current"`` or ``"pending"``).

        Returns:
            List of action history dictionaries where ``status`` matches.
        """
        return [entry for entry in self._iter_action_history() if entry.get("status") == status]

    def get_action_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve recent action history entries ordered by start time.

        This method merges action_history (start) entries with action_end entries
        to reconstruct complete action records. This supports the append-only
        logging pattern used for parallel execution.

        Args:
            limit: Maximum number of entries to return, sorted newest-first.

        Returns:
            A list of action history dictionaries truncated to ``limit``
            entries.
        """
        starts: Dict[str, Dict[str, Any]] = {}
        ends: Dict[str, Dict[str, Any]] = {}

        # Collect start and end entries
        for entry in self._load_log_entries():
            entry_type = entry.get("entry_type")
            run_id = entry.get("runId")
            if not run_id:
                continue

            if entry_type == "action_history":
                # For duplicate starts (shouldn't happen), keep the latest
                starts[run_id] = entry
            elif entry_type == "action_end":
                ends[run_id] = entry

        # Merge start + end into complete records
        history: List[Dict[str, Any]] = []
        for run_id, start in starts.items():
            if run_id in ends:
                # Merge end data into start entry
                end = ends[run_id]
                start["status"] = end.get("status", start.get("status"))
                start["outputs"] = end.get("outputs", start.get("outputs"))
                start["endedAt"] = end.get("endedAt", start.get("endedAt"))
            history.append(start)

        history.sort(
            key=lambda e: datetime.datetime.fromisoformat(e.get("startedAt") or datetime.datetime.min.isoformat()),
            reverse=True,
        )
        return history[:limit]

    # ------------------------------------------------------------------
    # Task logging helpers
    # ------------------------------------------------------------------
    def log_task(self, task: Task) -> None:
        """
        Persist or update a task log entry for tracking execution progress.

        The task is serialized to JSON-compatible primitives and either
        appended to the log or merged with an existing entry for the same task
        identifier.

        Args:
            task: The :class:`~core.task.task.Task` instance to record.
        """
        doc = {
            "entry_type": "task_log",
            "task_id": task.id,
            "name": task.name,
            "instruction": task.instruction,
            "todos": [asdict(todo) for todo in task.todos],
            "created_at": task.created_at,
            "status": task.status,
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }

        entries = self._load_log_entries()
        for entry in entries:
            if entry.get("entry_type") == "task_log" and entry.get("task_id") == task.id:
                entry.update(doc)
                break
        else:
            entries.append(doc)

        self._write_log_entries(entries)

    def _iter_task_logs(self) -> Iterable[Dict[str, Any]]:
        for entry in self._load_log_entries():
            if entry.get("entry_type") == "task_log":
                yield entry

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
        path.write_text(json.dumps(action_dict, indent=2, default=str), encoding="utf-8")

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
        self.agent_info_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

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
    def _extract_task_document_metadata(self, raw_text: str, fallback_name: str) -> tuple[str, str]:
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
            first_para = next((blk.strip() for blk in raw_text.split("\n\n") if blk.strip()), "")
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

            name, description = self._extract_task_document_metadata(raw_text, path.stem)
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

    # ------------------------------------------------------------------
    # Task helpers (for recovery)
    # ------------------------------------------------------------------
    def find_current_task_steps(self) -> List[Dict[str, Any]]:
        """
        List steps across all tasks that are marked as ``current``.

        Returns:
            A list of dictionaries pairing ``task_id`` with the active step
            metadata.
        """
        results: List[Dict[str, Any]] = []
        for entry in self._iter_task_logs():
            task_id = entry.get("task_id")
            for step in entry.get("steps", []):
                if step.get("status") == "current":
                    results.append({"task_id": task_id, "step": step})
        return results

    def update_step_status(
        self,
        task_id: str,
        action_id: str,
        status: str,
        failure_message: Optional[str] = None,
    ) -> None:
        """
        Update the status of a task step and persist the change.

        Args:
            task_id: Identifier for the task owning the step.
            action_id: The step's action identifier used to locate it.
            status: New status string to assign to the step.
            failure_message: Optional failure detail to attach when updating.
        """
        entries = self._load_log_entries()
        updated = False
        for entry in entries:
            if entry.get("entry_type") != "task_log" or entry.get("task_id") != task_id:
                continue
            for step in entry.get("steps", []):
                if step.get("action_id") == action_id:
                    step["status"] = status
                    if failure_message is not None:
                        step["failure_message"] = failure_message
                    updated = True
                    break
            if updated:
                entry["updated_at"] = datetime.datetime.utcnow().isoformat()
                break
        if updated:
            self._write_log_entries(entries)
