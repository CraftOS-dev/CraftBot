"""The Mini Browser's own thread and event loop.

Playwright objects belong to the event loop that created them, but Mini
Browser callers live on several loops: the main agent/UI loop, and each
sub-agent's private loop (``spawn_subagent`` runs ``asyncio.run`` in a worker
thread). So the browser gets one home: a daemon thread named ``mini-browser``
running its own loop. Every Playwright object, lock and background task of
the browser lives there, and callers marshal into it with :meth:`call`
(request/response, caller cancellation propagates) or :meth:`submit`
(fire-and-forget).

Starting the host only starts the thread and builds the
:class:`~app.mini_browser.core.BrowserCore`; Chromium itself starts on first
real use.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Set, TypeVar

from app.logger import logger

if TYPE_CHECKING:
    from app.mini_browser.core import BrowserCore

T = TypeVar("T")

THREAD_NAME = "mini-browser"
_START_TIMEOUT_S = 30.0
_CANCEL_GRACE_S = 5.0


def _default_core_factory() -> "BrowserCore":
    from app.mini_browser.core import BrowserCore

    return BrowserCore()


class MiniBrowserHost:
    """A daemon thread + event loop that owns one :class:`BrowserCore`."""

    def __init__(
        self, core_factory: Optional[Callable[[], "BrowserCore"]] = None
    ) -> None:
        self._factory = core_factory or _default_core_factory
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._core: Optional["BrowserCore"] = None
        # Strong references to fire-and-forget tasks (host loop only).
        self._submitted: Set[asyncio.Task] = set()

    # ── state ────────────────────────────────────────────────────────────────

    @property
    def core(self) -> "BrowserCore":
        core = self._core
        if core is None:
            raise RuntimeError("The Mini Browser host is not running")
        return core

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    def is_running(self) -> bool:
        thread, loop = self._thread, self._loop
        return (
            thread is not None
            and thread.is_alive()
            and loop is not None
            and not loop.is_closed()
        )

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the thread, loop and core (not Chromium). Idempotent, thread-safe."""
        with self._lock:
            if self.is_running():
                return
            loop = _new_loop()
            ready = threading.Event()
            box: dict = {}
            thread = threading.Thread(
                target=self._run, args=(loop, ready, box), name=THREAD_NAME, daemon=True
            )
            thread.start()
            if not ready.wait(_START_TIMEOUT_S):
                loop.call_soon_threadsafe(loop.stop)
                raise RuntimeError("The Mini Browser host did not start in time")
            if "error" in box:
                thread.join(_CANCEL_GRACE_S)
                error = box["error"]
                raise RuntimeError(
                    f"The Mini Browser host failed to start: {type(error).__name__}"
                ) from error
            self._loop, self._thread, self._core = loop, thread, box["core"]
            self._submitted = set()
        logger.debug("[MiniBrowser] Host thread started")

    def _run(
        self, loop: asyncio.AbstractEventLoop, ready: threading.Event, box: dict
    ) -> None:
        asyncio.set_event_loop(loop)
        try:
            box["core"] = self._factory()
        except BaseException as exc:  # reported to start()
            box["error"] = exc
            ready.set()
            asyncio.set_event_loop(None)
            loop.close()
            return
        ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                _cancel_pending(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as exc:
                logger.debug(f"[MiniBrowser] Host loop cleanup: {type(exc).__name__}")
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    async def call(self, fn: Callable[["BrowserCore"], Awaitable[T]]) -> T:
        """Run ``fn(core)`` on the host loop and return its result.

        Works from any loop or thread. Cancelling the caller cancels the work
        on the host loop.
        """
        self.start()
        loop, core = self._loop, self._core
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            return await fn(core)
        try:
            future = asyncio.run_coroutine_threadsafe(_invoke(fn, core), loop)
        except RuntimeError:
            from app.mini_browser.errors import MiniBrowserError

            raise MiniBrowserError("MINI_BROWSER_NOT_RUNNING") from None
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

    def submit(
        self, fn: Callable[["BrowserCore"], Awaitable[Any]], *, start: bool = True
    ) -> concurrent.futures.Future:
        """Fire-and-forget ``fn(core)`` on the host loop. Thread-safe.

        Runs in a clean context (no caller context variables). Failures are
        logged and set on the returned future. With ``start=False`` a host
        that is not running is not started: the future fails instead.
        """
        result: concurrent.futures.Future = concurrent.futures.Future()
        if start:
            self.start()
        loop, core = self._loop, self._core
        if loop is None or core is None or not self.is_running():
            result.set_exception(RuntimeError("The Mini Browser host is not running"))
            return result

        def schedule() -> None:
            if not result.set_running_or_notify_cancel():
                return
            task = contextvars.Context().run(loop.create_task, _logged(fn, core))
            self._submitted.add(task)
            task.add_done_callback(lambda t: self._finish_submitted(t, result))

        try:
            loop.call_soon_threadsafe(schedule)
        except RuntimeError as exc:  # the loop closed meanwhile
            result.set_exception(exc)
        return result

    def _finish_submitted(
        self, task: asyncio.Task, result: concurrent.futures.Future
    ) -> None:
        self._submitted.discard(task)
        if task.cancelled():
            result.set_exception(concurrent.futures.CancelledError())
        elif task.exception() is not None:
            result.set_exception(task.exception())
        else:
            result.set_result(task.result())

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Close Chromium, stop the loop and join the thread. Never raises."""
        with self._lock:
            loop, thread, core = self._loop, self._thread, self._core
        if loop is None or thread is None:
            return
        deadline = time.monotonic() + max(1.0, float(timeout))
        if thread is threading.current_thread():
            # Called from the host loop itself: it cannot join its own thread.
            try:
                if core is not None:
                    await core.close()
            except Exception as exc:
                logger.warning(
                    f"[MiniBrowser] Browser close failed: {type(exc).__name__}"
                )
            finally:
                loop.stop()
            return
        if thread.is_alive() and not loop.is_closed() and core is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(core.close(), loop)
                await asyncio.wait_for(
                    asyncio.wrap_future(future),
                    max(0.5, deadline - time.monotonic() - 1.0),
                )
            except asyncio.TimeoutError:
                logger.warning("[MiniBrowser] Browser close timed out during shutdown")
            except Exception as exc:
                logger.warning(
                    f"[MiniBrowser] Browser close failed: {type(exc).__name__}"
                )
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
        await asyncio.to_thread(thread.join, max(0.5, deadline - time.monotonic()))
        if thread.is_alive():
            logger.warning("[MiniBrowser] Host thread did not stop in time")
        with self._lock:
            if self._thread is thread:
                self._loop = self._thread = self._core = None
        logger.debug("[MiniBrowser] Host stopped")


def _new_loop() -> asyncio.AbstractEventLoop:
    """A fresh loop that can run subprocesses (Playwright's driver).

    On Windows that has to be a Proactor loop, whatever the process-wide
    event loop policy says.
    """
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


async def _invoke(
    fn: Callable[["BrowserCore"], Awaitable[T]], core: "BrowserCore"
) -> T:
    return await fn(core)


async def _logged(
    fn: Callable[["BrowserCore"], Awaitable[Any]], core: "BrowserCore"
) -> Any:
    try:
        return await fn(core)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(f"[MiniBrowser] Background call failed: {type(exc).__name__}")
        raise


def _cancel_pending(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel what is left on the loop and let it unwind (bounded)."""
    tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    loop.run_until_complete(asyncio.wait(tasks, timeout=_CANCEL_GRACE_S))
    for task in tasks:
        if task.done() and not task.cancelled() and task.exception() is not None:
            logger.debug(
                f"[MiniBrowser] Task ended with {type(task.exception()).__name__} at shutdown"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Process-wide host
# ─────────────────────────────────────────────────────────────────────────────

_host_lock = threading.Lock()
_host: Optional[MiniBrowserHost] = None


def get_host() -> MiniBrowserHost:
    """The process-wide host, started (thread + core; Chromium starts lazily)."""
    global _host
    with _host_lock:
        if _host is None:
            _host = MiniBrowserHost()
        host = _host
    host.start()
    return host


def get_host_if_started() -> Optional[MiniBrowserHost]:
    """The process-wide host if its thread is running, else None (never starts it)."""
    host = _host
    return host if host is not None and host.is_running() else None
