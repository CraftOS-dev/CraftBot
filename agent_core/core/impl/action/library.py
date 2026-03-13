# -*- coding: utf-8 -*-
"""
ActionLibrary for managing action storage and retrieval.

This module provides the ActionLibrary class that handles storing,
retrieving, and searching actions via DatabaseInterface.
"""

import datetime
from typing import List, Optional

from agent_core.core.action import Action
from agent_core.decorators import profile, OperationCategory
from agent_core.core.protocols.database import DatabaseInterfaceProtocol
from agent_core.utils.logger import logger


class ActionLibrary:
    """
    Manages storing, retrieving, and modifying actions via DatabaseInterface.
    """

    def __init__(self, llm_interface, db_interface: DatabaseInterfaceProtocol):
        """
        Initialize the library responsible for persisting actions.

        Args:
            llm_interface: LLM client used elsewhere for generating actions.
            db_interface: Database gateway that handles MongoDB/ChromaDB storage.
        """
        self.llm_interface = llm_interface
        self.db_interface = db_interface

    def store_action(self, action: Action):
        """
        Persist an action definition and stamp its update time.

        Args:
            action: Action instance to serialize and store.
        """
        action_dict = action.to_dict()
        action_dict["updatedAt"] = datetime.datetime.utcnow().isoformat()
        self.db_interface.store_action(action_dict)

    @profile("action_library_retrieve_action", OperationCategory.ACTION_LIBRARY)
    def retrieve_action(self, action_name: str) -> Optional[Action]:
        """
        Fetch a single action by name.

        Args:
            action_name: Case-insensitive name of the action to retrieve.

        Returns:
            Optional[Action]: Hydrated action instance if found, otherwise ``None``.
        """
        action_data = self.db_interface.get_action(action_name)
        if action_data:
            return Action.from_dict(action_data)
        return None

    @profile("action_library_retrieve_default_action", OperationCategory.ACTION_LIBRARY)
    def retrieve_default_action(self) -> List[Action]:
        """
        Retrieve actions marked as defaults.
        These actions are always available to the agents regardless of the mode.

        Returns:
            List[Action]: All default actions stored in the database.
        """
        docs = self.db_interface.list_actions(default=True)
        return [Action.from_dict(doc) for doc in docs]

    def get_default_action_names(self) -> set[str]:
        return {
            action.name
            for action in self.retrieve_default_action()
        }

    def delete_action(self, action_name: str):
        """Deletes an action from storage."""
        self.db_interface.delete_action(action_name)
