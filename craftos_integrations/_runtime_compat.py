"""Runtime compatibility shims for environments where asyncio task context
gets lost or never registered.

Specifically: on some Python 3.14 conda-forge builds inside this host,
``asyncio.current_task()`` returns ``None`` even inside a coroutine started
via ``asyncio.create_task()``. That breaks any third-party library that uses
``asyncio.timeout(...)`` (websockets, aiohttp, etc.) because
``Timeout.__aenter__`` raises ``RuntimeError("Timeout should be used inside
a task")`` when ``current_task()`` is ``None``.

This shim relaxes that check: if ``current_task()`` is ``None``, the
timeout context simply runs without arming a deadline. When a task IS
detected, the original behavior is preserved.

The shim is idempotent and applied once at package import.
"""

from __future__ import annotations

import asyncio
import sys


_APPLIED = False


def apply_asyncio_timeout_shim() -> None:
    """Patch ``asyncio.timeouts.Timeout.__aenter__`` to tolerate missing tasks.

    Only applied on Python 3.11+ (where ``asyncio.timeouts`` exists). No-op on
    older versions, since they use ``async_timeout`` and have a separate fix path.
    """
    global _APPLIED
    if _APPLIED:
        return
    if sys.version_info < (3, 11):
        _APPLIED = True
        return

    try:
        from asyncio import timeouts as _t
    except ImportError:
        _APPLIED = True
        return

    Timeout = _t.Timeout
    original_aenter = Timeout.__aenter__

    async def patched_aenter(self):
        # Try the original first; if it would raise solely because there's no
        # task, fall through and let the body run unguarded.
        try:
            return await original_aenter(self)
        except RuntimeError as e:
            if "Timeout should be used inside a task" in str(e):
                # Mark as entered so __aexit__ doesn't object, but don't arm
                # a deadline. Since most callers in this codebase pass
                # ``timeout=None`` anyway, no real timeout is being lost.
                if hasattr(_t, "_State"):
                    self._state = _t._State.ENTERED
                self._task = None
                return self
            raise

    Timeout.__aenter__ = patched_aenter

    # Also patch __aexit__ to not crash when self._task is None.
    original_aexit = Timeout.__aexit__

    async def patched_aexit(self, exc_type, exc_val, exc_tb):
        if self._task is None:
            # We never armed; just transition state cleanly.
            if hasattr(_t, "_State"):
                self._state = _t._State.EXITED
            return None
        return await original_aexit(self, exc_type, exc_val, exc_tb)

    Timeout.__aexit__ = patched_aexit

    # Also patch sniffio (used by anyio/httpx) which checks
    # ``asyncio.current_task()`` for the same reason and raises
    # ``AsyncLibraryNotFoundError("unknown async library, or not in async
    # context")`` when it's None. Force it to assume asyncio whenever we
    # can detect a running loop — the alternatives (trio/curio) aren't in
    # play for this codebase.
    try:
        import sniffio  # type: ignore[import-untyped]

        original_sniff = sniffio.current_async_library

        def patched_sniff() -> str:
            try:
                return original_sniff()
            except sniffio.AsyncLibraryNotFoundError:
                try:
                    asyncio.get_running_loop()
                    return "asyncio"
                except RuntimeError:
                    raise

        sniffio.current_async_library = patched_sniff
    except ImportError:
        pass

    _APPLIED = True
