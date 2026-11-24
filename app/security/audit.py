"""Security audit log: append-only JSON lines, each chained to the last.

Every record carries the SHA-256 of the line before it, so deleting or
editing a line breaks the chain from that point (``verify``). None of the
agents benchmarked (OpenClaw, Hermes Agent, Pi) has a tamper-evident trail.

Records are metadata only (what happened, to which action or setting,
with what outcome), never prompts, inputs, outputs or secret values.

Writes go through a background thread: ``record`` only queues, so an
action never waits on the disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from app.security.files import OWNER_FILE, ensure_private_dir

GENESIS = "0" * 64
_STOP = object()


def _digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()
        self._last = GENESIS

    # ── writing ──

    def record(self, event: str, **fields: Any) -> None:
        self._ensure_writer()
        self._queue.put({"ts": time.time(), "event": event, **fields})

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until everything queued so far is on disk (tests, export)."""
        if self._thread is None:
            return
        done = threading.Event()
        self._queue.put(done)
        done.wait(timeout)

    def _ensure_writer(self) -> None:
        if self._thread is not None:
            return
        with self._start_lock:
            if self._thread is None:
                ensure_private_dir(self.path.parent)
                self._last = self._tail_digest()
                self._thread = threading.Thread(
                    target=self._run, name="security-audit", daemon=True
                )
                self._thread.start()

    def _tail_digest(self) -> str:
        try:
            with open(self.path, "rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - 65536))
                lines = stream.read().splitlines()
        except FileNotFoundError:
            return GENESIS
        for raw in reversed(lines):
            if raw.strip():
                return _digest(raw.decode("utf-8", "replace"))
        return GENESIS

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            batch = [item]
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            waiters = []
            lines = []
            for entry in batch:
                if isinstance(entry, threading.Event):
                    waiters.append(entry)
                    continue
                if entry is _STOP:
                    continue
                entry["prev"] = self._last
                line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
                self._last = _digest(line)
                lines.append(line)
            if lines:
                self._append(lines)
            for waiter in waiters:
                waiter.set()

    def _append(self, lines) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, OWNER_FILE)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    # ── reading ──

    def entries(self, limit: int = 200) -> list:
        self.flush()
        try:
            with open(self.path, encoding="utf-8") as stream:
                lines = stream.readlines()[-limit:]
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def verify(self) -> Tuple[bool, int, Optional[int]]:
        """(intact, records checked, first broken line number or None)."""
        self.flush()
        previous = GENESIS
        count = 0
        for number, line in enumerate(self._lines(), start=1):
            try:
                entry = json.loads(line)
            except ValueError:
                return False, count, number
            if entry.get("prev") != previous:
                return False, count, number
            previous = _digest(line)
            count += 1
        return True, count, None

    def _lines(self) -> Iterator[str]:
        try:
            with open(self.path, encoding="utf-8") as stream:
                for raw in stream:
                    line = raw.rstrip("\n")
                    if line:
                        yield line
        except FileNotFoundError:
            return


_log: Optional[AuditLog] = None
_log_lock = threading.Lock()


def default_path() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / ".security" / "audit.jsonl"


def get_log() -> AuditLog:
    global _log
    if _log is None:
        with _log_lock:
            if _log is None:
                _log = AuditLog(default_path())
    return _log


def set_log_for_tests(log: Optional[AuditLog]) -> None:
    global _log
    _log = log


def record(event: str, **fields: Any) -> None:
    get_log().record(event, **fields)


def record_if_enabled(event: str, **fields: Any) -> None:
    from app.security.policy import get_policy

    if get_policy().audit_log:
        record(event, **fields)
