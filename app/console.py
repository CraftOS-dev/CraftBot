"""Consistent Unicode console output for source and installed entry points."""

import os
import sys


def configure_console(*, log_file: str = None) -> None:
    if sys.platform != "win32":
        return
    # pythonw launched by Task Scheduler / HKCU Run has no standard handles.
    # Give it real files before any startup code flushes output or passes the
    # streams to a subprocess. Installation already supplies these handles,
    # which used to hide this crash until the first login after installation.
    if sys.stdout is None or sys.stderr is None:
        try:
            output = open(
                log_file or os.devnull, "a", encoding="utf-8", errors="replace"
            )
        except OSError:
            output = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = output
        if sys.stderr is None:
            sys.stderr = output
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    # Child interpreters must agree when their output is redirected to a log.
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
