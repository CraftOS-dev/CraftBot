"""
CraftBot FindIndex — SQLite FTS5 trigram filename index with watchdog updates.

Replaces live os.walk retrieval for find_files (issue #354).
Full crawl under the resolved base_directory — no directory skip list.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass

    Observer = None  # type: ignore[misc, assignment]

_DEBOUNCE_SECONDS = 5.0
_DB_NAME = "findindex.db"
_META_ROOT = "indexed_root"
_META_BUILT_AT = "built_at"

_build_lock = threading.Lock()
_watcher_lock = threading.Lock()
_watchers: dict[str, _RootWatcher] = {}
_needs_incremental: dict[str, bool] = {}


@dataclass
class IndexStats:
    files_indexed: int
    files_added: int
    files_updated: int
    files_removed: int
    duration_seconds: float


def _index_dir(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".craftbot")


def _db_path(root: str) -> str:
    return os.path.join(_index_dir(root), _DB_NAME)


def _connect(root: str) -> sqlite3.Connection:
    os.makedirs(_index_dir(root), exist_ok=True)
    conn = sqlite3.connect(_db_path(root), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS files (
            rowid INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            basename TEXT NOT NULL,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            basename,
            content='files',
            content_rowid='rowid',
            tokenize='trigram'
        );

        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, basename) VALUES (new.rowid, new.basename);
        END;

        CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, basename)
            VALUES ('delete', old.rowid, old.basename);
        END;

        CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, basename)
            VALUES ('delete', old.rowid, old.basename);
            INSERT INTO files_fts(rowid, basename) VALUES (new.rowid, new.basename);
        END;
        """
    )
    conn.commit()


def _normalize_glob_part(part: str) -> str:
    if any(ch in part for ch in "*?[]"):
        return part
    return f"{part}*"


def _split_or_patterns(pattern: str) -> list[str]:
    if "|" in pattern:
        parts = [part.strip() for part in pattern.split("|") if part.strip()]
    elif re.search(r"\s+OR\s+", pattern, re.IGNORECASE):
        parts = [
            part.strip()
            for part in re.split(r"\s+OR\s+", pattern, flags=re.IGNORECASE)
            if part.strip()
        ]
    else:
        parts = [pattern]
    return [_normalize_glob_part(part) for part in parts]


def _iter_files(root: str):
    """Recursive file iterator mirroring os.walk (no skip list, no symlink follow)."""
    stack = [root]
    while stack:
        dir_path = stack.pop()
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            yield entry
                    except OSError:
                        continue
        except OSError:
            continue


def _file_stat(entry: os.DirEntry) -> tuple[float, int] | None:
    try:
        st = entry.stat(follow_symlinks=False)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def build_index(root: str, force: bool = False) -> IndexStats:
    """Build or incrementally refresh the filename index for *root*."""
    root = os.path.abspath(root)
    started = time.perf_counter()

    with _build_lock:
        conn = _connect(root)
        try:
            _init_schema(conn)
            stored_root = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (_META_ROOT,)
            ).fetchone()
            has_rows = (
                conn.execute("SELECT 1 FROM files LIMIT 1").fetchone() is not None
            )

            if (
                not force
                and has_rows
                and stored_root
                and os.path.normcase(stored_root[0]) == os.path.normcase(root)
                and not _needs_incremental.get(root, False)
            ):
                total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                return IndexStats(
                    files_indexed=total,
                    files_added=0,
                    files_updated=0,
                    files_removed=0,
                    duration_seconds=time.perf_counter() - started,
                )

            if not force and has_rows and stored_root and stored_root[0] == root:
                stats = _incremental_update(conn, root)
                _needs_incremental[root] = False
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (_META_BUILT_AT, str(time.time())),
                )
                conn.commit()
                return IndexStats(
                    files_indexed=stats[0],
                    files_added=stats[1],
                    files_updated=stats[2],
                    files_removed=stats[3],
                    duration_seconds=time.perf_counter() - started,
                )

            conn.execute("DELETE FROM files")
            conn.commit()
            count = _full_crawl(conn, root)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (_META_ROOT, root),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (_META_BUILT_AT, str(time.time())),
            )
            conn.commit()
            return IndexStats(
                files_indexed=count,
                files_added=count,
                files_updated=0,
                files_removed=0,
                duration_seconds=time.perf_counter() - started,
            )
        finally:
            conn.close()


def _full_crawl(conn: sqlite3.Connection, root: str) -> int:
    count = 0
    batch: list[tuple[str, str, float, int]] = []
    for entry in _iter_files(root):
        stat = _file_stat(entry)
        if stat is None:
            continue
        mtime, size = stat
        batch.append((entry.path, entry.name, mtime, size))
        if len(batch) >= 5000:
            conn.executemany(
                "INSERT INTO files(path, basename, mtime, size) VALUES (?, ?, ?, ?)",
                batch,
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT INTO files(path, basename, mtime, size) VALUES (?, ?, ?, ?)",
            batch,
        )
        count += len(batch)
    conn.commit()
    return count


def _incremental_update(
    conn: sqlite3.Connection, root: str
) -> tuple[int, int, int, int]:
    seen: set[str] = set()
    added = updated = 0
    prefix = root if root.endswith(os.sep) else root + os.sep

    for entry in _iter_files(root):
        stat = _file_stat(entry)
        if stat is None:
            continue
        path = entry.path
        seen.add(path)
        mtime, size = stat
        row = conn.execute(
            "SELECT mtime, size FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO files(path, basename, mtime, size) VALUES (?, ?, ?, ?)",
                (path, entry.name, mtime, size),
            )
            added += 1
        elif row[0] != mtime or row[1] != size:
            conn.execute(
                "UPDATE files SET basename = ?, mtime = ?, size = ? WHERE path = ?",
                (entry.name, mtime, size, path),
            )
            updated += 1

    removed = 0
    for (path,) in conn.execute("SELECT path FROM files"):
        if path == root:
            continue
        if not path.startswith(prefix):
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            removed += 1
            continue
        if path not in seen:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            removed += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    return total, added, updated, removed


def _fts_prefilter_sql(pattern: str) -> tuple[str, list[str]] | None:
    if "*" not in pattern and "?" not in pattern and "[" not in pattern:
        return ("f.basename = ?", [pattern])

    if pattern.startswith("*"):
        remainder = pattern[1:]
        next_star = remainder.find("*")
        literal = remainder[:next_star] if next_star >= 0 else remainder
        if len(literal) >= 2 and "?" not in literal and "[" not in literal:
            return ("files_fts.basename MATCH ?", [literal])
        return None

    star = pattern.find("*")
    if star > 0:
        literal = pattern[:star]
        if len(literal) >= 2 and "?" not in literal and "[" not in literal:
            quoted = '"' + literal.replace('"', '""') + '"'
            return ("files_fts.basename MATCH ?", [quoted])
    return None


def _search_single(
    conn: sqlite3.Connection,
    root: str,
    pattern: str,
    limit: int | None,
) -> list[str]:
    root_prefix = root if root.endswith(os.sep) else root + os.sep
    prefilter = _fts_prefilter_sql(pattern)
    matches: list[str] = []

    if prefilter:
        sql_fragment, params = prefilter
        if "files_fts" in sql_fragment:
            query = f"""
                SELECT f.path, f.basename
                FROM files f
                INNER JOIN files_fts ON files_fts.rowid = f.rowid
                WHERE f.path LIKE ? AND {sql_fragment}
            """
        else:
            query = f"""
                SELECT f.path, f.basename
                FROM files f
                WHERE f.path LIKE ? AND {sql_fragment}
            """
        rows = conn.execute(query, (root_prefix + "%", *params))
    else:
        rows = conn.execute(
            "SELECT path, basename FROM files WHERE path LIKE ?",
            (root_prefix + "%",),
        )

    for path, basename in rows:
        if fnmatch.fnmatch(basename, pattern):
            matches.append(os.path.abspath(path))
            if limit is not None and len(matches) >= limit:
                break
    return matches


def search(root: str, pattern: str, limit: int | None = None) -> list[str]:
    """Return all paths under *root* whose basename matches *pattern*."""
    root = os.path.abspath(root)
    build_index(root, force=False)

    patterns = _split_or_patterns(pattern)
    conn = _connect(root)
    try:
        seen: set[str] = set()
        results: list[str] = []
        for part in patterns:
            for path in _search_single(conn, root, part, limit):
                if path not in seen:
                    seen.add(path)
                    results.append(path)
                    if limit is not None and len(results) >= limit:
                        return results
        return results
    finally:
        conn.close()


def start_watcher(root: str) -> bool:
    """Start a debounced watchdog observer for *root* (once per root)."""
    if not WATCHDOG_AVAILABLE:
        return False

    root = os.path.abspath(root)
    with _watcher_lock:
        if root in _watchers and _watchers[root].is_running:
            return True
        watcher = _RootWatcher(root, _DEBOUNCE_SECONDS)
        if not watcher.start():
            return False
        _watchers[root] = watcher
        return True


class _RootWatcher:
    def __init__(self, root: str, debounce_seconds: float) -> None:
        self.root = root
        self.debounce_seconds = debounce_seconds
        self._observer: Observer | None = None
        self._is_running = False
        self._lock = threading.Lock()
        self._debounce_timer: threading.Timer | None = None
        self._pending = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> bool:
        if not WATCHDOG_AVAILABLE or Observer is None:
            return False
        if not os.path.isdir(self.root):
            return False
        self._observer = Observer()
        handler = _IndexEventHandler(self._on_change)
        self._observer.schedule(handler, self.root, recursive=True)
        self._observer.start()
        self._is_running = True
        return True

    def _on_change(self, _path: str, _event_type: str) -> None:
        _needs_incremental[self.root] = True
        with self._lock:
            self._pending = True
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self.debounce_seconds, self._flush)
            self._debounce_timer.start()

    def _flush(self) -> None:
        with self._lock:
            if not self._pending:
                return
            self._pending = False
            self._debounce_timer = None
        build_index(self.root, force=False)


class _IndexEventHandler(FileSystemEventHandler):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._callback(event.src_path, "created")

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._callback(event.src_path, "modified")

    def on_deleted(self, event) -> None:
        if not event.is_directory:
            self._callback(event.src_path, "deleted")

    def on_moved(self, event) -> None:
        if event.is_directory:
            return
        self._callback(event.src_path, "deleted")
        if event.dest_path:
            self._callback(event.dest_path, "created")
