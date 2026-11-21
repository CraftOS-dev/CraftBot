# -*- coding: utf-8 -*-
"""
app.startup_diagnostics

Small, dependency-free helpers for diagnostics (issue #224, Phase 0).

Secret hygiene: the app's loguru sinks use ``diagnose=True``, which prints
the values of local variables in a logged traceback. Passing an exception to
loguru (``logger.exception`` / ``opt(exception=...)``) from a frame that
holds an API key would therefore write the key into the log. These helpers
render tracebacks with the standard library instead, which shows code lines
only, never variable values.
"""

from __future__ import annotations

import traceback


def format_exception_details(exc: BaseException) -> str:
    """Full traceback text for ``exc``, without local variable values."""
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(lines).rstrip()
