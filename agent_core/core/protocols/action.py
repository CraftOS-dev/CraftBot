# -*- coding: utf-8 -*-
"""
Protocol definitions for action execution.

This module defines protocols for ActionExecutor and ActionManager
that specify the interfaces for action execution and orchestration.
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple


class ActionLibraryProtocol(Protocol):
    """
    Protocol for action storage and retrieval.

    This defines the minimal interface for managing action definitions.
    """

    def retrieve_action(self, action_name: str) -> Optional[Any]:
        """
        Fetch a single action by name.

        Args:
            action_name: Name of the action to retrieve.

        Returns:
            Action instance if found, otherwise None.
        """
        ...

    def store_action(self, action: Any) -> None:
        """
        Persist an action definition.

        Args:
            action: Action instance to store.
        """
        ...

    def search_action(self, query: str, top_k: int = 50) -> List[str]:
        """
        Search for actions using vector similarity.

        Args:
            query: Natural-language description of the desired action.
            top_k: Maximum number of action names to return.

        Returns:
            List of matching action names.
        """
        ...

    def retrieve_default_action(self) -> List[Any]:
        """
        Retrieve actions marked as defaults.

        Returns:
            List of default actions.
        """
        ...

    def get_default_action_names(self) -> set:
        """
        Get names of default actions.

        Returns:
            Set of default action names.
        """
        ...

    def delete_action(self, action_name: str) -> None:
        """
        Delete an action.

        Args:
            action_name: Name of the action to delete.
        """
        ...


class ActionRouterProtocol(Protocol):
    """
    Protocol for action selection and routing.

    This defines the minimal interface for selecting actions
    based on user queries and task context.
    """

    async def select_action(
        self,
        query: str,
        action_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Select action in conversation mode.

        Args:
            query: User's request.
            action_type: Optional type filter.

        Returns:
            Decision with action_name and parameters.
        """
        ...

    async def select_action_in_task(
        self,
        query: str,
        action_type: Optional[str] = None,
        GUI_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Select action when a task is running.

        Args:
            query: Task-level instruction.
            action_type: Optional action type hint.
            GUI_mode: Whether in GUI mode.

        Returns:
            Decision with action_name, parameters, and reasoning.
        """
        ...

    async def select_action_in_simple_task(
        self,
        query: str,
    ) -> Dict[str, Any]:
        """
        Action selection for simple task mode.

        Args:
            query: Task-level instruction.

        Returns:
            Decision with action_name, parameters, and reasoning.
        """
        ...

    async def select_action_in_GUI(
        self,
        query: str,
        action_type: Optional[str] = None,
        GUI_mode: bool = False,
        reasoning: str = "",
    ) -> Dict[str, Any]:
        """
        GUI-specific action selection.

        Args:
            query: Task-level instruction.
            action_type: Optional action type hint.
            GUI_mode: Whether in GUI mode.
            reasoning: Pre-computed reasoning from VLM.

        Returns:
            Decision with action_name and parameters.
        """
        ...


class ActionExecutorProtocol(Protocol):
    """
    Protocol for action execution.

    This defines the minimal interface that an action executor
    must provide for executing actions in sandboxed or internal modes.
    """

    async def execute_atomic_action(
        self,
        action: Any,
        input_data: dict,
        *,
        timeout: Optional[int] = None,
    ) -> dict:
        """
        Execute an atomic action.

        Args:
            action: The Action object to execute.
            input_data: Input data to pass to the action.
            timeout: Optional timeout in seconds.

        Returns:
            Result dictionary from the action execution.
        """
        ...

    async def execute_action(
        self,
        action: Any,
        input_data: dict,
    ) -> dict:
        """
        Execute an action with tracking.

        Args:
            action: The Action object to execute.
            input_data: Input data to pass to the action.

        Returns:
            Result dictionary from the action execution.
        """
        ...


class ActionManagerProtocol(Protocol):
    """
    Protocol for action orchestration.

    This defines the minimal interface for managing action execution
    lifecycles, including observation steps and history logging.
    """

    async def execute_action(
        self,
        action: Any,
        context: str,
        event_stream: str,
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        is_running_task: bool = False,
        is_gui_task: bool = False,
        *,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute action with full lifecycle management.

        Args:
            action: The Action to execute.
            context: Context string for the action.
            event_stream: Event stream string for logging.
            parent_id: Optional parent action identifier.
            session_id: Session identifier.
            is_running_task: Whether a task is running.
            is_gui_task: Whether this is a GUI task.
            input_data: Optional pre-computed input data.

        Returns:
            Result dictionary with outputs and status.
        """
        ...

    def get_action_history(self, limit: int = 10) -> list:
        """
        Get recent action history.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of action history entries.
        """
        ...
