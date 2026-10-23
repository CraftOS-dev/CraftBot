"""Shared serialization and atomic writes for settings.json."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from functools import wraps
from pathlib import Path


settings_write_lock = threading.RLock()


def settings_transaction(function):
    """Serialize a settings read-modify-write, including nested mutations."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with settings_write_lock:
            return function(*args, **kwargs)

    return wrapped


def write_settings(path: Path, settings: dict) -> None:
    """Publish a complete JSON snapshot without exposing a partial write.

    Mutators must hold settings_write_lock from their read through this write.
    The reentrant lock also protects callers that only publish a snapshot.
    """
    with settings_write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(settings, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                os.chmod(temporary, path.stat().st_mode)
            for attempt in range(10):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    # A Windows reader can briefly deny replacement.
                    if os.name != "nt" or attempt == 9:
                        raise
                    time.sleep(0.005 * (attempt + 1))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
