# -*- coding: utf-8 -*-
"""Global runtime state for a single-user, single-agent process."""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from app.state.types import AgentProperties
from app.task import Task

@dataclass
class AgentState:
    """Authoritative runtime state for the agent."""

    current_task: Optional[Task] = None
    event_stream: Optional[str] = None
    gui_mode: bool = False
    agent_properties: AgentProperties = AgentProperties(current_task_id="", action_count=0)

    def update_current_task(self, new_task: Optional[Task]) -> None:
        self.current_task = new_task

    def update_event_stream(self, new_event_stream: Optional[str]) -> None:
        self.event_stream = new_event_stream

    def update_gui_mode(self, gui_mode: bool) -> None:
        self.gui_mode = gui_mode

    def refresh(
        self,
        *,
        current_task: Optional[Task] = None,
        event_stream: Optional[str] = None,
        gui_mode: Optional[bool] = None,
    ) -> None:
        """Update only fields that changed."""
        self.current_task = current_task
        self.event_stream = event_stream
        self.gui_mode = gui_mode

    def set_agent_property(self, key, value):
        """
        Sets a global agent property (not specific to any task).
        """
        self.agent_properties.set_property(key, value)

    def get_agent_property(self, key, default=None):
        """
        Retrieves a global agent property.
        """
        return self.agent_properties.get_property(key, default)

    def get_agent_properties(self):
        """
        Retrieves all global agent properties.
        """
        return self.agent_properties.to_dict()

# ---- Global runtime state ----
STATE = AgentState()
