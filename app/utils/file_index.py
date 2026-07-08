"""
CraftBot FindIndex — SQLite FTS5 trigram filename index with watchdog updates.

Replaces live os.walk retrieval for find_files (issue #354).
Full crawl under the resolved base_directory, skipping known noise
directories (VCS metadata, dependency/build caches, OS reserved folders).
"""

from __future__ import annotations

import fnmatch
import os
import re
import sqlite3
import stat
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

_SKIP_DIR_NAMES = {
    ".craftbot",
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "venv",
    ".venv",
    ".env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "$recycle.bin",
    "system volume information",
}

_build_locks_registry_lock = threading.Lock()
_build_locks: dict[str, threading.Lock] = {}
_watcher_lock = threading.Lock()
_watchers: dict[str, _RootWatcher] = {}

# normcased root -> set of changed absolute paths reported by that root's
# watcher since the last build_index() pass consumed them. An empty/missing
# entry means "no known pending changes" (build_index can use the cheap
# cached-count path). A non-empty entry lets build_index apply just those
# paths (_apply_targeted_changes) instead of re-walking the entire tree.
#
# _needs_full_rewalk holds roots where a directory-level event (rename,
# move, delete of a whole subtree) was observed. A single directory event
# doesn't tell us which of its descendants changed, so those roots fall
# back to one full _incremental_update pass instead of a targeted one.
#
# _verified_roots holds roots that have had at least one real check (full
# crawl or incremental/targeted pass) *in this process*. Without it, a
# freshly restarted process with an existing, matching, non-empty index
# and no recorded pending changes would trust that index as fresh even
# though real changes may have happened while the process was down.
_pending_changes_lock = threading.Lock()
_pending_changes: dict[str, set[str]] = {}
_needs_full_rewalk: set[str] = set()
_verified_roots: set[str] = set()


def _get_build_lock(root: str) -> threading.Lock:
    """Per-root build lock so unrelated roots never block each other."""
    key = os.path.normcase(root)
    with _build_locks_registry_lock:
        lock = _build_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _build_locks[key] = lock
        return lock


def _is_skip_path(path: str) -> bool:
    """True if *path* has a _SKIP_DIR_NAMES component anywhere in it.

    Lowercases explicitly rather than relying on os.path.normcase, which is
    only case-insensitive on Windows (a no-op on POSIX) — this must match
    _iter_files' always-case-insensitive entry.name.lower() check on every
    platform, or a mixed-case noise directory would be excluded from the
    crawl but not from watcher events on Linux/macOS.
    """
    parts = path.replace("\\", "/").split("/")
    return any(part.lower() in _SKIP_DIR_NAMES for part in parts)


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
    """Recursive file iterator mirroring os.walk (skips _SKIP_DIR_NAMES, no symlink follow)."""
    stack = [root]
    while stack:
        dir_path = stack.pop()
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() in _SKIP_DIR_NAMES:
                                continue
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

    with _get_build_lock(root):
        conn = _connect(root)
        try:
            _init_schema(conn)
            stored_root = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (_META_ROOT,)
            ).fetchone()
            has_rows = (
                conn.execute("SELECT 1 FROM files LIMIT 1").fetchone() is not None
            )
            root_matches_stored = bool(
                stored_root
                and os.path.normcase(stored_root[0]) == os.path.normcase(root)
            )

            key = os.path.normcase(root)

            if (
                not force
                and has_rows
                and root_matches_stored
                and key in _verified_roots
                and not _peek_has_pending_changes(root)
            ):
                total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                return IndexStats(
                    files_indexed=total,
                    files_added=0,
                    files_updated=0,
                    files_removed=0,
                    duration_seconds=time.perf_counter() - started,
                )

            if not force and has_rows and root_matches_stored:
                # A non-empty pending set (reported directly by this root's
                # watcher) lets us apply just those paths — O(changes), not
                # O(total files indexed). Fall back to the full re-walk when
                # a directory-level event was seen (a single event doesn't
                # tell us which descendants changed) or when this root has
                # no verified state yet in this process (e.g. right after a
                # restart, before any watcher has run — an empty pending set
                # there must not be mistaken for "nothing changed").
                pending, needs_full = _pop_pending_changes(root)
                if needs_full or key not in _verified_roots or not pending:
                    stats = _incremental_update(conn, root)
                else:
                    stats = _apply_targeted_changes(conn, root, pending)
                _verified_roots.add(key)
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

            # Bulk (re)build: drop the per-row FTS sync triggers so the crawl's
            # inserts don't each pay a trigram-index write, then rebuild the
            # FTS index in one pass at the end (standard FTS5 external-content
            # bulk-load pattern). _init_schema recreates the triggers after.
            _pop_pending_changes(root)  # full crawl already reflects current state
            _verified_roots.add(key)
            conn.execute("DROP TRIGGER IF EXISTS files_ai")
            conn.execute("DROP TRIGGER IF EXISTS files_ad")
            conn.execute("DROP TRIGGER IF EXISTS files_au")
            conn.execute("DELETE FROM files")
            count = _full_crawl(conn, root)
            conn.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")
            _init_schema(conn)
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
    normcased_prefix = os.path.normcase(prefix)
    for (path,) in conn.execute("SELECT path FROM files"):
        if path == root:
            continue
        if not os.path.normcase(path).startswith(normcased_prefix):
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            removed += 1
            continue
        if path not in seen:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            removed += 1

    conn.commit()
    # files_indexed is discarded by every caller — see _apply_targeted_changes.
    return -1, added, updated, removed


def _peek_has_pending_changes(root: str) -> bool:
    key = os.path.normcase(root)
    with _pending_changes_lock:
        return bool(_pending_changes.get(key)) or key in _needs_full_rewalk


def _pop_pending_changes(root: str) -> tuple[set[str], bool]:
    """Clear and return (changed_paths, needs_full_rewalk) for *root*."""
    key = os.path.normcase(root)
    with _pending_changes_lock:
        paths = _pending_changes.pop(key, set())
        needs_full = key in _needs_full_rewalk
        _needs_full_rewalk.discard(key)
        return paths, needs_full


def _mark_needs_full_rewalk(root: str) -> None:
    key = os.path.normcase(root)
    with _pending_changes_lock:
        _needs_full_rewalk.add(key)


def _apply_targeted_changes(
    conn: sqlite3.Connection, root: str, changed_paths: set[str]
) -> tuple[int, int, int, int]:
    """Apply exactly the given changed paths to the index — no tree walk.

    Cost is O(len(changed_paths)), not O(total files indexed), which is what
    keeps watcher-driven updates cheap even on huge, highly active roots
    (unlike _incremental_update, which re-walks everything every time).
    """
    added = updated = removed = 0
    for path in changed_paths:
        try:
            # lstat (not following symlinks) so a symlink is never indexed
            # here as a "file" — matches _iter_files/_full_crawl, which
            # also never treats symlinks as files. Deriving is_file from
            # this same stat (rather than a separate os.path.isfile call,
            # which *does* follow symlinks) keeps the two code paths from
            # disagreeing about what counts as an indexable file.
            st = os.stat(path, follow_symlinks=False)
            is_file = stat.S_ISREG(st.st_mode)
        except OSError:
            st = None
            is_file = False

        row = conn.execute(
            "SELECT mtime, size FROM files WHERE path = ?", (path,)
        ).fetchone()

        if st is None or not is_file:
            if row is not None:
                conn.execute("DELETE FROM files WHERE path = ?", (path,))
                removed += 1
            continue

        basename = os.path.basename(path)
        if row is None:
            conn.execute(
                "INSERT INTO files(path, basename, mtime, size) VALUES (?, ?, ?, ?)",
                (path, basename, st.st_mtime, st.st_size),
            )
            added += 1
        elif row[0] != st.st_mtime or row[1] != st.st_size:
            conn.execute(
                "UPDATE files SET basename = ?, mtime = ?, size = ? WHERE path = ?",
                (basename, st.st_mtime, st.st_size, path),
            )
            updated += 1

    conn.commit()
    # files_indexed is discarded by every caller (search(), _flush()) — skip
    # the O(total rows) COUNT(*) a real total would cost on every flush.
    return -1, added, updated, removed


def _fts_prefilter_sql(pattern: str) -> tuple[str, list[str]] | None:
    if "*" not in pattern and "?" not in pattern and "[" not in pattern:
        return ("f.basename = ?", [pattern])

    if pattern.startswith("*"):
        remainder = pattern[1:]
        next_star = remainder.find("*")
        literal = remainder[:next_star] if next_star >= 0 else remainder
        if len(literal) >= 2 and "?" not in literal and "[" not in literal:
            quoted = '"' + literal.replace('"', '""') + '"'
            return ("files_fts.basename MATCH ?", [quoted])
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


def list_local_drives() -> list[str]:
    """Return mount points of local fixed drives (cross-platform).

    Used both for boot-time index pre-warming and for the find_files
    ``all_drives`` option, so "search everywhere" means the same set of
    roots in both places.
    """
    import psutil

    drives = []
    for part in psutil.disk_partitions(all=False):
        opts = part.opts.lower().split(",")
        if os.name == "nt" and "fixed" not in opts:
            continue
        drives.append(part.mountpoint)
    return drives


def resolve_roots(
    base_directory: str, windows: bool = False
) -> tuple[list[str], dict | None]:
    """Validate and normalize a possibly '|'-joined base_directory string.

    Shared by both find_files action variants (posix/windows) via module
    import — same reasoning as find_files' docstring below: a same-module
    sibling helper in the action file itself would not be resolvable under
    the sandboxed exec model those actions run under.

    Returns (roots, None) on success, or ([], error_dict) if base_directory
    is empty/only separators/whitespace, or any listed root doesn't exist
    or isn't a directory.
    """
    if not base_directory:
        base_directory = os.path.expanduser("~")

    raw_roots = [part.strip() for part in base_directory.split("|") if part.strip()]
    if not raw_roots:
        return [], {
            "status": "error",
            "matches": [],
            "message": "base_directory must contain at least one non-empty path.",
        }

    roots = []
    for root in raw_roots:
        if windows:
            root = root.replace("/", "\\")
        root = os.path.normpath(os.path.expanduser(root))

        if not os.path.exists(root):
            return [], {
                "status": "error",
                "matches": [],
                "message": f"Base directory does not exist: {root}",
            }
        if not os.path.isdir(root):
            return [], {
                "status": "error",
                "matches": [],
                "message": f"Base directory is not a directory: {root}",
            }
        roots.append(root)

    return roots, None


def find_files(
    base_directory: str,
    file_pattern: str,
    recursive: bool,
    all_drives: bool = False,
    limit: int | None = None,
) -> dict:
    """Search one or more roots for basenames matching *file_pattern*.

    Shared implementation for the find_files action. Kept here (rather than
    as a helper in the action module) because "internal" actions are
    executed by extracting and exec'ing only the single decorated function's
    own source — a call to a same-module sibling function is not resolvable
    at that point, while an attribute access on an imported module is.

    *base_directory* may contain multiple absolute paths joined by '|' to
    search several roots in one call. If *all_drives* is True, *base_directory*
    is ignored and every local fixed drive is searched instead. *limit*, if
    given, caps the total number of matches across all roots combined.
    """
    if all_drives:
        roots = list_local_drives()
        if not roots:
            return {
                "status": "error",
                "matches": [],
                "message": "Could not determine local drives for all_drives search.",
            }
    else:
        roots = [part.strip() for part in base_directory.split("|") if part.strip()]

    seen: set[str] = set()
    matches: list[str] = []
    for root in roots:
        start_watcher(root)
        root_matches = search(root, file_pattern)
        if not recursive:
            root_abs = os.path.abspath(root)
            root_matches = [
                path
                for path in root_matches
                if os.path.normcase(os.path.dirname(path)) == os.path.normcase(root_abs)
            ]
        for path in root_matches:
            if path not in seen:
                seen.add(path)
                matches.append(path)
                if limit is not None and len(matches) >= limit:
                    break
        if limit is not None and len(matches) >= limit:
            break

    scope = ", ".join(roots) if roots else base_directory
    return {
        "status": "success",
        "matches": matches,
        "message": ""
        if matches
        else f"No files matching '{file_pattern}' were found in '{scope}'.",
    }


def start_watcher(root: str) -> bool:
    """Start a debounced watchdog observer for *root* (once per root)."""
    if not WATCHDOG_AVAILABLE:
        return False

    root = os.path.abspath(root)
    key = os.path.normcase(root)
    with _watcher_lock:
        if key in _watchers and _watchers[key].is_running:
            return True
        watcher = _RootWatcher(root, _DEBOUNCE_SECONDS)
        if not watcher.start():
            return False
        _watchers[key] = watcher
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

    def _on_change(self, path: str, event_type: str) -> None:
        if _is_skip_path(path):
            return
        if event_type == "dir_changed":
            # A single directory-level event (rename/move/delete of a whole
            # subtree) doesn't tell us which descendants changed — the next
            # build_index() pass does one full re-walk for this root instead
            # of trusting an incomplete targeted-changes set.
            _mark_needs_full_rewalk(self.root)
        else:
            key = os.path.normcase(self.root)
            with _pending_changes_lock:
                _pending_changes.setdefault(key, set()).add(path)
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
        # A newly created directory has no stale descendants to reconcile —
        # files created inside it later fire their own normal per-path
        # events — so this isn't treated as a structural "dir_changed"
        # event. Only a directory *move/rename* gets that treatment (see
        # on_moved): that's the one case with no per-descendant events.
        if not event.is_directory:
            self._callback(event.src_path, "created")

    def on_modified(self, event) -> None:
        # Directory "modified" events don't reliably signal an added/removed
        # descendant (they can fire for metadata-only changes too), so they
        # aren't treated as structural — only a directory move/rename is.
        if not event.is_directory:
            self._callback(event.src_path, "modified")

    def on_deleted(self, event) -> None:
        # A deleted directory's contents already generate their own
        # per-file delete events in the common case (recursive delete, or
        # Explorer moving it to $RECYCLE.BIN as an on_moved) — the
        # directory-level event itself adds no new information, so it's
        # not treated as structural here either.
        if not event.is_directory:
            self._callback(event.src_path, "deleted")

    def on_moved(self, event) -> None:
        if event.is_directory:
            # The one case that genuinely needs whole-subtree reconciliation:
            # a rename/move doesn't generate per-descendant events, so we
            # can't know what changed underneath without a real re-walk.
            self._callback(event.src_path, "dir_changed")
            return
        self._callback(event.src_path, "deleted")
        if event.dest_path:
            self._callback(event.dest_path, "created")
