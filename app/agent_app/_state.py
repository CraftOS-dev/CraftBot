"""Module-level singleton for the AgentAppManager.

Lives in its own file so that `broadcast.py` and `actions.py` can import the
accessor without triggering circular imports through `__init__.py`.
"""

from typing import Optional

from .manager import AgentAppManager

_manager: Optional[AgentAppManager] = None


def get_agent_app_manager() -> Optional[AgentAppManager]:
    """Get the global AgentAppManager instance."""
    return _manager


def set_agent_app_manager(manager: AgentAppManager) -> None:
    """Set the global AgentAppManager instance (called by browser_adapter)."""
    global _manager
    _manager = manager
