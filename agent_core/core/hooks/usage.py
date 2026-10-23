"""Deliver async hooks in the request's context and drain them at shutdown.

The loop belongs to a request, not to a long-lived model instance. Worker
threads inherit that ownership through ContextVars, including session context.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from contextvars import ContextVar
import logging
import threading

_loop = ContextVar("usage_owner_loop", default=None)
_request_pending = ContextVar("usage_request_pending", default=None)
_pending: set = set()
_lock = threading.Lock()
_logger = logging.getLogger(__name__)


def _track(future):
    # A Task is bound to its loop. Track a thread-safe completion handle so
    # application shutdown can also drain workers owned by other running loops.
    completion = concurrent.futures.Future()
    with _lock:
        _pending.add(completion)

    def done(item):
        cancelled = item.cancelled()
        error = None if cancelled else item.exception()
        with _lock:
            _pending.discard(completion)
        if cancelled:
            completion.cancel()
        elif error is not None:
            completion.set_exception(error)
            _logger.error(
                "Usage delivery failed",
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            completion.set_result(None)

    future.add_done_callback(done)
    return future


def dispatch_usage(hook, event) -> None:
    """Submit once; failed hooks are observable and never automatically retried."""

    async def deliver():
        await hook(event)

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    owner = _loop.get() or running
    if owner is None:
        # Synchronous callers have no event loop to own delivery. Finish the
        # hook before returning. Local reporters must be safe across loops.
        asyncio.run(deliver())
        return
    if owner.is_closed():
        raise RuntimeError("Usage request's event loop is closed")
    future = (
        owner.create_task(deliver())
        if owner is running
        else asyncio.run_coroutine_threadsafe(deliver(), owner)
    )
    _track(future)
    request = _request_pending.get()
    if request is not None:
        request.append(future)


async def _join(futures):
    if futures:
        await asyncio.gather(
            *(
                asyncio.shield(asyncio.wrap_future(f))
                if isinstance(f, concurrent.futures.Future)
                else asyncio.shield(f)
                for f in futures
            ),
            return_exceptions=True,
        )


async def to_thread_with_usage(function, /, *args, **kwargs):
    """Like to_thread, but delivery completes before a successful call returns.

    Cancellation leaves the worker tracked: shutdown drains it before closing
    the reporter. No request is resubmitted after an uncertain outcome.
    """
    request = []
    owner_token = _loop.set(asyncio.get_running_loop())
    pending_token = _request_pending.set(request)
    try:
        worker = _track(
            asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        )
        try:
            return await asyncio.shield(worker)
        finally:
            if worker.done():
                await _join(request)
    finally:
        _request_pending.reset(pending_token)
        _loop.reset(owner_token)


async def drain_usage() -> None:
    """Wait for workers and hooks, including hooks submitted by finishing workers."""
    while True:
        with _lock:
            pending = list(_pending)
        if not pending:
            return
        await _join(pending)
