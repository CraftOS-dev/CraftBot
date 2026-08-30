"""Broadcast callback registry and dispatchers for Agent App events.

The browser adapter registers async callbacks at startup. Agent actions
(running in the main loop) call the broadcast_agent_app_ready / _progress
wrappers directly. SessionManager hooks (running on a worker thread pool) go
through make_todo_broadcast_hook, which schedules the async broadcast onto
the main loop in a thread-safe way.
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from ._state import get_agent_app_manager

# Registered async callbacks into the browser adapter.
_broadcast_ready_callback: Optional[Callable[[str, str, int], Awaitable[bool]]] = None
_broadcast_created_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = (
    None
)
_broadcast_progress_callback: Optional[
    Callable[[str, str, int, str], Awaitable[None]]
] = None
_broadcast_todos_callback: Optional[
    Callable[[str, List[Dict[str, Any]]], Awaitable[None]]
] = None
_broadcast_data_changed_callback: Optional[Callable[[str], Awaitable[None]]] = None
_broadcast_build_event_callback: Optional[
    Callable[[str, Dict[str, Any]], Awaitable[None]]
] = None
_broadcast_wizard_open_callback: Optional[
    Callable[[Dict[str, Any]], Awaitable[None]]
] = None

# Captured at register time so cross-thread dispatchers (action handlers
# running on a worker thread pool) can schedule coroutines onto the main loop.
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def register_broadcast_callbacks(
    broadcast_ready: Callable[[str, str, int], Awaitable[bool]],
    broadcast_progress: Callable[[str, str, int, str], Awaitable[None]],
    broadcast_todos: Optional[
        Callable[[str, List[Dict[str, Any]]], Awaitable[None]]
    ] = None,
    broadcast_data_changed: Optional[Callable[[str], Awaitable[None]]] = None,
    broadcast_created: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    broadcast_build_event: Optional[
        Callable[[str, Dict[str, Any]], Awaitable[None]]
    ] = None,
    broadcast_wizard_open: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> None:
    """Register broadcast callbacks for Agent App actions to use.

    Called by the browser_adapter when it initializes.
    """
    global \
        _broadcast_ready_callback, \
        _broadcast_created_callback, \
        _broadcast_progress_callback, \
        _broadcast_todos_callback
    global _broadcast_data_changed_callback, _main_loop
    global _broadcast_build_event_callback, _broadcast_wizard_open_callback
    _broadcast_ready_callback = broadcast_ready
    _broadcast_created_callback = broadcast_created
    _broadcast_progress_callback = broadcast_progress
    _broadcast_todos_callback = broadcast_todos
    _broadcast_data_changed_callback = broadcast_data_changed
    _broadcast_build_event_callback = broadcast_build_event
    _broadcast_wizard_open_callback = broadcast_wizard_open
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        _main_loop = None
        logger.warning(
            "[AGENT_APP] No running loop at callback registration — cross-thread broadcasts will fail"
        )
    logger.info("[AGENT_APP] Broadcast callbacks registered")


async def broadcast_agent_app_ready(project_id: str, url: str, port: int) -> bool:
    """Broadcast that a Agent App is ready. Returns True on success."""
    if _broadcast_ready_callback:
        return await _broadcast_ready_callback(project_id, url, port)
    logger.warning(
        f"[AGENT_APP] broadcast_agent_app_ready called but callback is None "
        f"(manager={get_agent_app_manager() is not None})"
    )
    return False


async def broadcast_agent_app_wizard_open(payload: Dict[str, Any]) -> bool:
    """Open the Create Custom wizard in the browser at the interview step
    (chat-path requirements phase). Returns False when no browser adapter is
    registered — callers fail open (build proceeds without questions)."""
    if _broadcast_wizard_open_callback:
        await _broadcast_wizard_open_callback(payload)
        return True
    return False


async def broadcast_agent_app_created(project: Dict[str, Any]) -> bool:
    """Broadcast that a Agent App project was created (and registered).

    Used by the agent's scaffold action so a chat-created Agent App shows up
    in the browser's project list immediately, mirroring the modal flow.
    Returns True on success.
    """
    if _broadcast_created_callback:
        await _broadcast_created_callback(project)
        return True
    logger.warning(
        f"[AGENT_APP] broadcast_agent_app_created called but callback is None "
        f"(manager={get_agent_app_manager() is not None})"
    )
    return False


async def broadcast_agent_app_progress(
    project_id: str, phase: str, progress: int, message: str
) -> bool:
    """Broadcast Agent App creation progress. Returns True on success."""
    if _broadcast_progress_callback:
        await _broadcast_progress_callback(project_id, phase, progress, message)
        return True
    return False


async def _broadcast_todos_async(project_id: str, todos: List[Dict[str, Any]]) -> bool:
    """Internal async broadcaster used by the sync dispatcher below."""
    if _broadcast_todos_callback:
        await _broadcast_todos_callback(project_id, todos)
        return True
    return False


def _dispatch_todos(project_id: str, todos: List[Dict[str, Any]]) -> bool:
    """Thread-safe todo broadcast.

    Handles both calling contexts:
      - Main asyncio loop: schedules via loop.create_task
      - Worker thread: uses asyncio.run_coroutine_threadsafe against _main_loop

    Returns True if the broadcast was scheduled, False otherwise.
    """
    if not _broadcast_todos_callback:
        return False

    coro = _broadcast_todos_async(project_id, todos)

    try:
        running = asyncio.get_running_loop()
        running.create_task(coro)
        return True
    except RuntimeError:
        pass

    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return True

    coro.close()
    logger.warning("[AGENT_APP] No main loop available; todo broadcast skipped")
    return False


async def _broadcast_build_event_async(project_id: str, event: Dict[str, Any]) -> bool:
    """Internal async broadcaster used by the sync dispatcher below."""
    if _broadcast_build_event_callback:
        await _broadcast_build_event_callback(project_id, event)
        return True
    return False


def dispatch_build_event(project_id: str, event: Dict[str, Any]) -> bool:
    """Thread-safe build-event broadcast (called from the read-only
    construction observer). Same dual-context handling as _dispatch_todos:
    schedules onto the running loop, or onto the captured main loop from a
    worker thread. Fire-and-forget — never blocks the action pipeline."""
    if not _broadcast_build_event_callback:
        return False

    coro = _broadcast_build_event_async(project_id, event)

    try:
        running = asyncio.get_running_loop()
        running.create_task(coro)
        return True
    except RuntimeError:
        pass

    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return True

    coro.close()
    return False


async def _broadcast_data_changed_async(project_id: str) -> bool:
    """Internal async broadcaster used by the sync dispatcher below."""
    if _broadcast_data_changed_callback:
        await _broadcast_data_changed_callback(project_id)
        return True
    return False


def dispatch_agent_app_data_changed(project_id: str) -> bool:
    """Thread-safe signal that a Agent App's data was modified by the agent.

    Handles both calling contexts:
      - Main asyncio loop: schedules via loop.create_task
      - Worker thread: uses asyncio.run_coroutine_threadsafe against _main_loop

    Returns True if the broadcast was scheduled, False otherwise.
    """
    if not _broadcast_data_changed_callback:
        return False

    coro = _broadcast_data_changed_async(project_id)

    try:
        running = asyncio.get_running_loop()
        running.create_task(coro)
        return True
    except RuntimeError:
        pass

    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return True

    coro.close()
    logger.warning("[AGENT_APP] No main loop available; data-changed broadcast skipped")
    return False


def make_todo_broadcast_hook() -> Callable[[Any, List[Dict[str, Any]]], None]:
    """Build a post-update-todos hook that broadcasts todos for Agent App sessions.

    The returned callable matches SessionManager's PostUpdateTodosHook signature:
        (session, updated_todos_as_dicts) -> None

    It filters non-Agent-App sessions by checking whether the session id maps
    to a project, so registering it globally is safe.
    """

    def hook(session: Any, todos: List[Dict[str, Any]]) -> None:
        manager = get_agent_app_manager()
        if manager is None:
            return
        project = manager.get_project_by_session_id(session.id)
        if project is None:
            return  # non-Agent-App session — silently skip
        logger.debug(
            f"[AGENT_APP] Broadcasting {len(todos)} todos to project {project.id}"
        )
        _dispatch_todos(project.id, todos)
        # Narrate plan milestones into the build feed (start / complete rows).
        try:
            from . import construction_events

            construction_events.record_todo_transitions(project.id, todos)
        except Exception:
            pass

    return hook
