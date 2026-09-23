"""Read-only file watchers that report changes made outside the UI.

The agent and background jobs write config, memory and workspace files
without telling the UI. ``ChangeWatcher`` watches those paths with
``watchdog`` and reports debounced changes per target, which the browser
adapter turns into ``resource_changed`` notifications
(docs/plans/ui-data-freshness-plan.md, WS-3). It never writes to anything
it watches.

A watched *file* is observed through its parent directory, so files that
are replaced atomically (temp file + rename) or created later are still seen.
"""

from __future__ import annotations

import fnmatch
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

OnChange = Callable[[str, Set[str]], None]
IdForPath = Callable[[Path], Optional[str]]


@dataclass(frozen=True)
class WatchTarget:
    """One thing to watch.

    ``name`` is passed back to the change callback. ``path`` is a file or a
    directory; a directory is watched recursively when ``recursive`` is set.
    ``id_for`` maps a changed path to an id (e.g. its parent directory); when
    it returns None, or isn't given, the change carries no ids ("everything").
    Paths containing any of ``ignore`` as a path component are skipped, and
    when ``pattern`` is set only file names matching it (fnmatch) count.
    """

    name: str
    path: Path
    recursive: bool = False
    debounce: float = 0.3
    id_for: Optional[IdForPath] = None
    ignore: Tuple[str, ...] = field(default_factory=tuple)
    pattern: Optional[str] = None

    def matches(self, changed: Path) -> bool:
        if self.ignore and any(part in self.ignore for part in changed.parts):
            return False
        if self.pattern and not fnmatch.fnmatch(changed.name, self.pattern):
            return False
        if changed == self.path:
            return True
        if self.recursive:
            return self.path in changed.parents
        # A directory target without recursion: direct children only.
        return changed.parent == self.path


class _Debouncer:
    """Collects ids for one target and fires once per quiet period."""

    def __init__(self, target: WatchTarget, on_change: OnChange) -> None:
        self._target = target
        self._on_change = on_change
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._ids: Set[str] = set()
        self._everything = False

    def add(self, changed_id: Optional[str]) -> None:
        with self._lock:
            if changed_id is None:
                self._everything = True
            else:
                self._ids.add(changed_id)
            # Restart the quiet period: agents often write in several steps.
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._target.debounce, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            ids = set() if self._everything else self._ids
            self._ids = set()
            self._everything = False
            self._timer = None
        try:
            self._on_change(self._target.name, ids)
        except Exception:
            pass

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class _Handler(FileSystemEventHandler):
    def __init__(self, targets: List[Tuple[WatchTarget, _Debouncer]]) -> None:
        self._targets = targets

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed_no_write"):
            return
        paths = [event.src_path]
        dest = getattr(event, "dest_path", "")
        if dest:
            paths.append(dest)
        for raw in paths:
            changed = Path(os.fsdecode(raw))
            for target, debouncer in self._targets:
                if target.matches(changed):
                    debouncer.add(target.id_for(changed) if target.id_for else None)


class ChangeWatcher:
    """Watches a set of targets and reports debounced changes to ``on_change``.

    ``on_change(name, ids)`` runs on a timer thread; keep it thread-safe.
    """

    def __init__(self, targets: List[WatchTarget], on_change: OnChange) -> None:
        self._targets = [(t, _Debouncer(t, on_change)) for t in targets]
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        if self._observer is not None:
            return
        # One schedule per watched directory; recursive if any target needs it.
        dirs: Dict[Path, bool] = {}
        for target, _ in self._targets:
            watch_dir = target.path if target.path.is_dir() else target.path.parent
            if not watch_dir.is_dir():
                continue  # Missing folder: nothing to watch until a restart.
            dirs[watch_dir] = dirs.get(watch_dir, False) or (
                target.recursive and target.path.is_dir()
            )
        observer = Observer()
        handler = _Handler(self._targets)
        for watch_dir, recursive in dirs.items():
            try:
                observer.schedule(handler, str(watch_dir), recursive=recursive)
            except OSError:
                continue
        observer.daemon = True
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        observer, self._observer = self._observer, None
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)
        for _, debouncer in self._targets:
            debouncer.cancel()
