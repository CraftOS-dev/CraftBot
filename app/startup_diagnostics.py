# -*- coding: utf-8 -*-
"""
app.startup_diagnostics

Small, dependency-free helpers for startup and lifecycle diagnostics
(issue #224, Phase 0): the runtime summary logged once at startup, and the
traceback text used when a component or a session loop fails.

Secret hygiene: the app's loguru sinks use ``diagnose=True``, which prints
the values of local variables in a logged traceback. Passing an exception to
loguru (``logger.exception`` / ``opt(exception=...)``) from a frame that
holds an API key would therefore write the key into the log. These helpers
render tracebacks with the standard library instead, which shows code lines
only, never variable values. The runtime summary reads no environment
variables, paths, user names or host names.
"""

from __future__ import annotations

import asyncio
import platform
import sys
import traceback
from typing import Dict


def describe_runtime() -> Dict[str, str]:
    """Return the facts needed to diagnose an environment mismatch.

    Read-only: it inspects state that is already set and never imports,
    installs or applies anything.
    """
    # Installed by agent_core/core/impl/action/manager.py on 3.11+.
    shim_active = getattr(asyncio.wait_for, "__name__", "") == "_compat_wait_for"
    # Set on the asyncio module by nest_asyncio.apply().
    nest_applied = bool(getattr(asyncio, "_nest_patched", False))
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": f"{platform.system()} {platform.release()}".strip(),
        "arch": platform.machine() or "unknown",
        "frozen": "yes" if getattr(sys, "frozen", False) else "no",
        "wait_for_shim": "active" if shim_active else "inactive",
        "nest_asyncio": "applied" if nest_applied else "not applied",
    }


def format_runtime_summary(info: Dict[str, str]) -> str:
    """Render ``describe_runtime()`` as one log line."""
    return "[STARTUP] Runtime: " + ", ".join(f"{k}={v}" for k, v in info.items())


def log_runtime_info(log=None) -> Dict[str, str]:
    """Log the runtime summary once and return it."""
    if log is None:
        from app.logger import logger as log
    info = describe_runtime()
    log.info(format_runtime_summary(info))
    return info


def format_exception_details(exc: BaseException) -> str:
    """Full traceback text for ``exc``, without local variable values."""
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(lines).rstrip()
