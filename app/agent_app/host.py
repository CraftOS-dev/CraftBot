"""Agent App host: brings up the Agent App manager for the running agent.

Agent Apps belong to the agent, not to any one front end, so the manager is
started by ``AgentBase.run()`` before the WebSocket interface comes up, the
same way in the browser and the terminal edition. The interface adapter only
registers its broadcast callbacks on top (``register_broadcast_callbacks``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agent_core.utils.logger import logger

from app.config import AGENT_WORKSPACE_ROOT

from ._state import get_agent_app_manager, set_agent_app_manager
from .broadcast import make_todo_broadcast_hook
from .manager import AgentAppManager

if TYPE_CHECKING:
    from app.agent_base import AgentBase


def start_agent_app_host(agent: "AgentBase") -> AgentAppManager:
    """Create the process-wide AgentAppManager and start its background work.

    Must run inside the event loop (auto-launch is scheduled as a task).
    Calling it twice is a bug: there is exactly one manager per process.
    """
    if get_agent_app_manager() is not None:
        raise RuntimeError("The Agent App host is already running")

    manager = AgentAppManager(workspace_root=AGENT_WORKSPACE_ROOT)
    # Bind session manager and trigger service for project sessions
    manager.bind_session_manager(agent.session_manager, agent.trigger_service)

    # Clean up orphan processes and folders from previous sessions
    manager.cleanup_on_startup()

    # Start watchdog to monitor running Agent App processes
    manager.start_watchdog()

    # Auto-launch projects that have auto_launch enabled
    asyncio.create_task(manager.auto_launch_projects())

    # Global accessor for Agent App actions and the interface adapter
    set_agent_app_manager(manager)

    # Subscribe the Agent App module to SessionManager todo updates so
    # that the agent's build breakdown streams to every client automatically.
    agent.session_manager.add_post_update_todos_hook(make_todo_broadcast_hook())

    # READ-ONLY build observer: derive construction-dock build events from
    # the actions the agent already performs (write_file / stream_edit /
    # agent_app_scaffold / agent_app_notify_ready). These hooks are
    # single-callback and currently unset; the executor wraps them in
    # try/except and the observer swallows all exceptions, so this can
    # never affect a build. It reads inputs/outputs only, mutates nothing.
    try:
        from . import construction_events

        on_start, on_end = construction_events.make_action_hooks()
        agent.action_manager._on_action_start = on_start
        agent.action_manager._on_action_end = on_end
    except Exception as e:
        logger.warning(f"[AGENT_APP] build-event observer not attached: {e}")

    return manager
