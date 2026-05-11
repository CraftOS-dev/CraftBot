"""PyInstaller runtime hook: force UTF-8 on stdout/stderr.

In frozen builds — especially `console=False` windowed builds on Windows —
Python's stdout/stderr default to the system locale codec (cp1252 in most
locales). Any non-Latin-1 character (the box-drawing glyphs in run.py's
banner, emoji in messages, etc.) crashes with UnicodeEncodeError.

PYTHONIOENCODING is ignored by frozen PyInstaller bootloaders, so we
reconfigure here at startup, before any user code runs.

Strategy:
  0. PROBE the stream first by attempting a no-op write+flush. In a
     `console=False` windowed build on Windows, `sys.stdout` exists as a
     valid Python TextIOWrapper but its underlying Windows file handle
     is invalid — every real write raises `OSError: [Errno 22] Invalid
     argument`. The previous version of this hook trusted
     `stream.encoding == 'utf-8'` as proof the stream worked, which let
     these broken streams through unchanged and crashed later (e.g. on
     `print(..., flush=True)` in run.py's print_step). Probe = the only
     reliable test.
  1. If the stream supports `.reconfigure()` (Python 3.7+ TextIOWrapper),
     try it. Cheap and non-destructive.
  2. Otherwise rebuild a fresh TextIOWrapper around the underlying FD
     with UTF-8 encoding. We have to grab the FD before replacing.
  3. After every path we re-probe; if writes still fail, install a
     NullIO sink so unconditional `print()` calls don't crash.
"""

import io
import os
import sys


class _NullIO(io.TextIOBase):
    def isatty(self) -> bool:
        return False

    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        pass

    @property
    def encoding(self) -> str:
        return "utf-8"


class _SafeIO(io.TextIOBase):
    """Wraps a real stream and swallows OSError/ValueError on every write
    or flush. The probe in `_force_utf8` catches streams that are broken
    AT STARTUP, but in a frozen Windows build a stream can be valid when
    probed and start failing later (e.g. when a child process inherits
    the parent's stdout fd through a chain of subprocess.Popen calls and
    the eventual write to that fd raises errno 22). Wrapping defensively
    means a one-off write error doesn't crash the program — it just
    drops the message."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def write(self, s: str) -> int:
        try:
            return self._inner.write(s)
        except (OSError, ValueError):
            return len(s) if isinstance(s, str) else 0

    def flush(self) -> None:
        try:
            self._inner.flush()
        except (OSError, ValueError):
            pass

    def isatty(self) -> bool:
        try:
            return self._inner.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._inner.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._inner, "encoding", "utf-8") or "utf-8"

    @property
    def buffer(self):
        return getattr(self._inner, "buffer", None)


def _is_broken(stream) -> bool:
    """Return True if a no-op write+flush raises. Detects PyInstaller
    `console=False` Windows builds where stdout is a TextIOWrapper around
    an invalid HANDLE — encoding looks fine but real I/O explodes."""
    try:
        stream.write("")
        stream.flush()
    except (OSError, ValueError, AttributeError):
        return True
    return False


def _force_utf8(name: str) -> None:
    stream = getattr(sys, name, None)

    # No stream at all, or stream is already broken — install NullIO.
    if stream is None or _is_broken(stream):
        setattr(sys, name, _NullIO())
        return

    # Already UTF-8 and the probe passed — wrap in SafeIO and return.
    enc = getattr(stream, "encoding", "") or ""
    if enc.lower().replace("-", "") == "utf8":
        setattr(sys, name, _SafeIO(stream))
        return

    # Path 1: reconfigure() — preserves the stream object identity.
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            if not _is_broken(getattr(sys, name)):
                setattr(sys, name, _SafeIO(getattr(sys, name)))
                return
        except Exception:
            pass

    # Path 2: rebuild a TextIOWrapper around the same FD with UTF-8.
    fd = -1
    try:
        fd = stream.fileno()
    except Exception:
        pass
    if fd != -1:
        try:
            try:
                stream.flush()
            except Exception:
                pass
            new = io.TextIOWrapper(
                os.fdopen(fd, "wb", buffering=0, closefd=False),
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
                write_through=True,
            )
            setattr(sys, name, new)
            if not _is_broken(new):
                setattr(sys, name, _SafeIO(new))
                return
        except Exception:
            pass

    # Path 3: nothing worked — replace with a sink so prints don't crash.
    setattr(sys, name, _NullIO())


for _name in ("stdout", "stderr"):
    _force_utf8(_name)
