# -*- coding: utf-8 -*-
"""
Protocol definition for DatabaseInterface.

This module defines the DatabaseInterfaceProtocol that specifies the
interface for persistence operations. The protocol enables structural
typing for database operations across different agent implementations.
"""

from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core import Task


class DatabaseInterfaceProtocol(Protocol):
    """
    Protocol for database persistence operations.

    This defines the minimal interface that a database implementation
    must provide for use by shared agent code.
    """

    def log_task(self, task: "Task") -> None:
        """
        Persist or update a task log entry.

        Args:
            task: The Task instance to record.
        """
        ...

    def upsert_action_history(
        self,
        run_id: str,
        *,
        session_id: str,
        parent_id: Optional[str],
        name: str,
        action_type: str,
        status: str,
        inputs: Optional[Dict[str, Any]],
        outputs: Optional[Dict[str, Any]],
        started_at: Optional[str],
        ended_at: Optional[str],
    ) -> None:
        """
        Insert or update an action execution history entry.

        Args:
            run_id: Unique identifier for the action execution.
            session_id: Session that triggered the action.
            parent_id: Optional parent action identifier.
            name: Human-readable action name.
            action_type: Action type label.
            status: Current execution status.
            inputs: Serialized action inputs.
            outputs: Serialized action outputs.
            started_at: ISO timestamp for execution start.
            ended_at: ISO timestamp for execution end.
        """
        ...

    async def log_action_start_async(
        self,
        run_id: str,
        *,
        session_id: Optional[str],
        parent_id: Optional[str],
        name: str,
        action_type: str,
        inputs: Optional[Dict[str, Any]],
        started_at: str,
    ) -> None:
        """
        Fast O(1) append for action start (async version).

        Args:
            run_id: Unique identifier for the action execution.
            session_id: Session that triggered the action.
            parent_id: Optional parent action identifier.
            name: Human-readable action name.
            action_type: Action type label.
            inputs: Serialized action inputs.
            started_at: ISO timestamp for execution start.
        """
        ...

    async def log_action_end_async(
        self,
        run_id: str,
        *,
        outputs: Optional[Dict[str, Any]],
        status: str,
        ended_at: str,
    ) -> None:
        """
        Fast O(1) append for action end (async version).

        Args:
            run_id: Unique identifier for the action execution.
            outputs: Serialized action outputs.
            status: Final execution status.
            ended_at: ISO timestamp for execution end.
        """
        ...

    def get_action_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve recent action history entries.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of action history dictionaries.
        """
        ...

    def find_actions_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        Return all action history entries matching the given status.

        Args:
            status: Status value to filter.

        Returns:
            List of matching action history dictionaries.
        """
        ...

    def search_actions(self, query: str, top_k: int = 7) -> List[str]:
        """
        Search actions by semantic similarity.

        Args:
            query: Search query string.
            top_k: Maximum number of results.

        Returns:
            List of action names matching the query.
        """
        ...

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
        Store a prompt interaction with metadata.

        Args:
            input_data: Serialized prompt inputs.
            output: The model output string.
            provider: Name of the LLM provider.
            model: Model identifier used.
            config: Provider-specific configuration.
            status: Execution status.
            token_count_input: Token count for prompt.
            token_count_output: Token count for response.
        """
        ...
