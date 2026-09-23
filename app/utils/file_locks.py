"""
File Locks Module

This module provides locks so that write_file.py and stream_edit.py can be used
in parallel without causing file corruption through editing the same file at the
same time.

"""
import os
import threading

_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()

def get_file_lock(path: str) -> threading.Lock:
    norm = os.path.realpath(os.path.abspath(path))
    norm = os.path.normcase(norm)
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(norm)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[norm] = lock
        return lock
