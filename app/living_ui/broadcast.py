"""Broadcast callback registry and dispatchers for Living UI events.

The browser adapter registers async callbacks at startup. Agent actions
(running in the main loop) call the broadcast_living_ui_ready / _progress
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

from ._state import get_living_ui_manager

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
_broadcast_question_callback: Optional[Callable[[str, str, str], Awaitable[None]]] = (
    None
)

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
    broadcast_question: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
) -> None:
    """Register broadcast callbacks for Living UI actions to use.

    Called by the browser_adapter when it initializes.
    """
    global \
        _broadcast_ready_callback, \
        _broadcast_created_callback, \
        _broadcast_progress_callback, \
        _broadcast_todos_callback
    global _broadcast_data_changed_callback, _broadcast_question_callback, _main_loop
    _broadcast_ready_callback = broadcast_ready
    _broadcast_created_callback = broadcast_created
    _broadcast_progress_callback = broadcast_progress
    _broadcast_todos_callback = broadcast_todos
    _broadcast_data_changed_callback = broadcast_data_changed
    _broadcast_question_callback = broadcast_question
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


async def broadcast_living_ui_created(project: Dict[str, Any]) -> bool:
    """Broadcast that a Living UI project was created (and registered).

    Used by the agent's scaffold action so a chat-created Living UI shows up
    in the browser's project list immediately, mirroring the modal flow.
    Returns True on success.
    """
    if _broadcast_created_callback:
        await _broadcast_created_callback(project)
        return True
    logger.warning(
        f"[LIVING_UI] broadcast_living_ui_created called but callback is None "
        f"(manager={get_living_ui_manager() is not None})"
    )
    return False


async def broadcast_living_ui_question(session_id: str, message: str, options=None) -> bool:
    """Mirror an agent's final question onto the Living UI creation screen,
    so the user can answer even with the chat closed.

    Resolves the *creating* project from the session id and no-ops if the
    session isn't a Living UI project session. The on-screen answer is posted
    back through the normal chat path into the same session, which wakes the
    waiting run. Returns True if mirrored.
    """
    if not session_id or not _broadcast_question_callback:
        return False
    manager = get_living_ui_manager()
    if not manager:
        return False
    try:
        project = manager.get_project_by_session_id(session_id)
    except Exception:
        project = None
    if not project or getattr(project, "status", None) != "creating":
        return False
    await _broadcast_question_callback(project.id, session_id, message, options)
    return True


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
    """Build a post-update-todos hook that broadcasts todos for Living UI sessions.

    The returned callable matches SessionManager's PostUpdateTodosHook signature:
        (session, updated_todos_as_dicts) -> None

    It filters non-Living-UI sessions by checking whether the session id maps
    to a project, so registering it globally is safe.
    """

    def hook(session: Any, todos: List[Dict[str, Any]]) -> None:
        manager = get_living_ui_manager()
        if manager is None:
            return
        project = manager.get_project_by_session_id(session.id)
        if project is None:
            return  # non-Living-UI session — silently skip
        logger.debug(
            f"[LIVING_UI] Broadcasting {len(todos)} todos to project {project.id}"
        )
        _dispatch_todos(project.id, todos)

    return hook
