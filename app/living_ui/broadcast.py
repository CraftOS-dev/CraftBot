"""Broadcast callback registry and dispatchers for Living UI events.

The browser adapter registers async callbacks at startup. Agent actions
(running in the main loop) call the broadcast_living_ui_ready / _progress
wrappers directly. TaskManager hooks (running on a worker thread pool) go
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

from ._state import get_living_ui_manager

# Registered async callbacks into the browser adapter.
_broadcast_ready_callback: Optional[Callable[[str, str, int], Awaitable[bool]]] = None
_broadcast_progress_callback: Optional[
    Callable[[str, str, int, str], Awaitable[None]]
] = None
_broadcast_todos_callback: Optional[
    Callable[[str, List[Dict[str, Any]]], Awaitable[None]]
] = None
_broadcast_data_changed_callback: Optional[Callable[[str], Awaitable[None]]] = None

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
) -> None:
    """Register broadcast callbacks for Living UI actions to use.

    Called by the browser_adapter when it initializes.
    """
    global \
        _broadcast_ready_callback, \
        _broadcast_progress_callback, \
        _broadcast_todos_callback
    global _broadcast_data_changed_callback, _main_loop
    _broadcast_ready_callback = broadcast_ready
    _broadcast_progress_callback = broadcast_progress
    _broadcast_todos_callback = broadcast_todos
    _broadcast_data_changed_callback = broadcast_data_changed
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        _main_loop = None
        logger.warning(
            "[LIVING_UI] No running loop at callback registration — cross-thread broadcasts will fail"
        )
    logger.info("[LIVING_UI] Broadcast callbacks registered")


async def broadcast_living_ui_ready(project_id: str, url: str, port: int) -> bool:
    """Broadcast that a Living UI is ready. Returns True on success."""
    if _broadcast_ready_callback:
        return await _broadcast_ready_callback(project_id, url, port)
    logger.warning(
        f"[LIVING_UI] broadcast_living_ui_ready called but callback is None "
        f"(manager={get_living_ui_manager() is not None})"
    )
    return False


async def broadcast_living_ui_progress(
    project_id: str, phase: str, progress: int, message: str
) -> bool:
    """Broadcast Living UI creation progress. Returns True on success."""
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
    logger.warning("[LIVING_UI] No main loop available; todo broadcast skipped")
    return False


async def _broadcast_data_changed_async(project_id: str) -> bool:
    """Internal async broadcaster used by the sync dispatcher below."""
    if _broadcast_data_changed_callback:
        await _broadcast_data_changed_callback(project_id)
        return True
    return False


def dispatch_living_ui_data_changed(project_id: str) -> bool:
    """Thread-safe signal that a Living UI's data was modified by the agent.

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
    logger.warning("[LIVING_UI] No main loop available; data-changed broadcast skipped")
    return False


def make_todo_broadcast_hook() -> Callable[[Any, List[Dict[str, Any]]], None]:
    """Build a post-update-todos hook that broadcasts todos for Living UI tasks.

    The returned callable matches TaskManager's PostUpdateTodosHook signature:
        (active_task, updated_todos_as_dicts) -> None

    It filters non-Living-UI tasks by checking whether the task id maps to
    a project, so registering it globally is safe.
    """

    def hook(task: Any, todos: List[Dict[str, Any]]) -> None:
        manager = get_living_ui_manager()
        if manager is None:
            return
        project = manager.get_project_by_task_id(task.id)
        if project is None:
            return  # non-Living-UI task — silently skip
        logger.debug(
            f"[LIVING_UI] Broadcasting {len(todos)} todos to project {project.id}"
        )
        _dispatch_todos(project.id, todos)

    return hook
