# -*- coding: utf-8 -*-
"""Session model classes.

A Session is the only work primitive: a persistent, standalone agent lane
with its own event stream, trigger queue, loaded capabilities and todos.
It replaces the former Task/task-session split.
"""

from agent_core.core.session.todo import TodoItem, TodoStatus
from agent_core.core.session.session import Session, SessionType, MAIN_SESSION_ID

__all__ = ["TodoItem", "TodoStatus", "Session", "SessionType", "MAIN_SESSION_ID"]
