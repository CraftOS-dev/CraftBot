"""Memory files written from outside content stay out of the prompt.

Ported from OpenClaw's memory provenance (MIT): src/agents/memory-write-
provenance.ts, src/memory/memory-artifact-provenance.ts, the bootstrap gate
in src/agents/bootstrap-files.ts and the check in src/commands/doctor-memory-
provenance.ts. CraftBot puts USER.md and SOUL.md in every system prompt and
MEMORY.md in its memory previews, so one injected email that gets written
into them would steer every later run.

With "Guard memory files" on (Settings > Security > Files):

- Every write by the agent's file tools (write_file, stream_edit) to a
  guarded file records the file's hash and where the write came from. It
  is "untrusted" when the run was started by a third party or has read
  outside content (``app.security.content.runs``), or when the file no
  longer matches the hash of the last recorded write: something outside the
  tracked tools (a shell command, an editor) changed it in between. Once
  untrusted, later writes keep it untrusted (OpenClaw).
- An untrusted file is left out of the system prompt and the memory
  previews. The agent can still read it explicitly. The security check
  lists it, and ``trust`` re-accepts it after the user reviewed it.
- A file with no record yet is trusted, as in OpenClaw: turning the guard
  on never drops a user's existing files.
- Writes through CraftBot's own pages (the file editors, the memory panel,
  restore, reset, profile import) are the owner's (OpenClaw's "owner"
  class). A page that replaces the whole file clears the quarantine; an
  item edit in the memory panel keeps it, since the user did not see the
  whole file.
- Conversation lines from third parties, and the agent's replies in a run
  that read outside content, are kept out of the queue the memory
  processor distills into MEMORY.md (OpenClaw's session ingestion promotes
  only owner and agent lines: packages/memory-host-sdk/src/host/
  session-provenance.ts).

With the guard off nothing is recorded or checked.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from agent_core.utils.logger import logger
from app.security.files import ensure_private_dir, write_private_json
from app.security.policy import get_policy

# The files CraftBot puts into context on its own (OpenClaw guards its root
# MEMORY.md and USER.md; CraftBot also injects SOUL.md into every prompt).
GUARDED_FILES = ("USER.md", "SOUL.md", "MEMORY.md")

AGENT = "agent"
OWNER = "owner"
UNTRUSTED = "untrusted"
_TRUSTED = frozenset({AGENT, OWNER})
_SCHEMA = 1

_lock = threading.RLock()
_cache: Dict[str, Any] = {"mtime": None, "files": {}}
_warned: set = set()


# ── where things live ──


def records_path() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / ".security" / "memory_provenance.json"


def _root() -> Path:
    from app.config import AGENT_FILE_SYSTEM_PATH

    return Path(AGENT_FILE_SYSTEM_PATH)


def _real(path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def guarded_name(path) -> Optional[str]:
    """The guarded file ``path`` resolves to (symlinks followed), or None."""
    if not path:
        return None
    real = _real(path)
    if os.path.basename(real) not in GUARDED_FILES and os.path.basename(
        str(path)
    ) not in GUARDED_FILES:
        return None  # cheap exit before resolving the agent file system
    root = _root()
    for name in GUARDED_FILES:
        if real == _real(root / name):
            return name
    return None


def _hash_file(name: str) -> str:
    try:
        data = (_root() / name).read_bytes()
    except OSError:
        data = b""
    return hashlib.sha256(data).hexdigest()


# ── the record store ──


def _load() -> Dict[str, Dict[str, Any]]:
    """The records, re-read only when the file changed (one stat per call)."""
    path = records_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = None
    if mtime == _cache["mtime"]:
        return _cache["files"]
    files: Dict[str, Dict[str, Any]] = {}
    if mtime is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for name, record in (raw.get("files") or {}).items():
                if name in GUARDED_FILES and isinstance(record, dict):
                    files[name] = record
        except (OSError, ValueError, AttributeError):
            # An unreadable store must not quietly trust everything it held.
            files = {
                name: {
                    "origin": UNTRUSTED,
                    "reason": "the record of who wrote it could not be read",
                    "since": 0,
                    "at": 0,
                }
                for name in GUARDED_FILES
            }
    _cache["mtime"] = mtime
    _cache["files"] = files
    return files


def _save(files: Dict[str, Dict[str, Any]]) -> None:
    path = records_path()
    ensure_private_dir(path.parent)
    write_private_json(path, {"version": _SCHEMA, "files": files})
    try:
        _cache["mtime"] = path.stat().st_mtime_ns
    except OSError:
        _cache["mtime"] = None
    _cache["files"] = files


def _audit(event: str, **fields: Any) -> None:
    try:
        from app.security import audit

        audit.record(event, **fields)
    except Exception as exc:
        logger.debug(f"[SECURITY] memory guard audit failed: {exc}")


# ── who is writing ──


def _current_session() -> Optional[str]:
    try:
        from agent_core.core.event_stream.event import SESSION_ID_INPUT_KEY
        from agent_core.core.impl.action.context import current_input_data

        data = current_input_data.get() or {}
        return data.get(SESSION_ID_INPUT_KEY)
    except Exception:
        return None


def _run_concern(session_id: Optional[str]) -> str:
    """Why a write from this session's run is untrusted, or ""."""
    from app.security.content import runs

    state = runs.get(session_id)
    if getattr(state, "third_party", False):
        return "written in a run a third party's message started"
    if state.tainted:
        return f"written after the run read {state.taint_reason or 'outside content'}"
    return ""


# ── writing ──


@contextlib.contextmanager
def tracking(path) -> Iterator[None]:
    """Wrap one write by the agent's file tools.

    The record is reserved before the write and restored if the write
    fails, so a reader never sees new content under the old trust
    (OpenClaw's recordMemoryArtifactWriteProvenance + rollback).
    """
    if not get_policy().guard_memory:
        yield
        return
    name = guarded_name(path)
    if name is None:
        yield
        return
    session_id = _current_session()
    concern = _run_concern(session_id)
    with _lock:
        files = dict(_load())
        previous = files.get(name)
        before = _hash_file(name)
        now = time.time()
        if previous and previous.get("origin") not in _TRUSTED:
            origin, reason = UNTRUSTED, previous.get("reason") or concern
            since = previous.get("since", now)
        elif concern:
            origin, reason, since = UNTRUSTED, concern, now
        elif previous and previous.get("hash") != before:
            origin, since = UNTRUSTED, now
            reason = "changed outside CraftBot's file tools before this write"
        else:
            origin, reason, since = AGENT, "", None
        reserved = {
            "origin": origin,
            "hash": (previous or {}).get("hash", before),
            "at": now,
            "session": session_id or "",
            "reason": reason,
        }
        if since is not None:
            reserved["since"] = since
        files[name] = reserved
        _save(files)
    try:
        yield
    except BaseException:
        with _lock:
            files = dict(_load())
            if previous is None:
                files.pop(name, None)
            else:
                files[name] = previous
            _save(files)
        raise
    with _lock:
        files = dict(_load())
        record = dict(files.get(name) or reserved)
        record["hash"] = _hash_file(name)
        files[name] = record
        _save(files)
    if origin == UNTRUSTED and (not previous or previous.get("origin") in _TRUSTED):
        _audit("memory_file_untrusted", file=name, reason=reason, session_id=session_id or "")


def record_owner_write(path, *, whole_file: bool) -> None:
    """A write through CraftBot's own pages, after it succeeded.

    ``whole_file``: the user saw and saved (or restored, reset, imported) the
    whole file, which clears a quarantine. Otherwise an untrusted file stays
    untrusted, with its hash brought up to date.
    """
    if not get_policy().guard_memory:
        return
    try:
        _record_owner_write(path, whole_file)
    except Exception as exc:
        # The page's write already succeeded; the next agent write will see
        # a changed hash and keep the file out, which fails safe.
        logger.warning(f"[SECURITY] Could not record the owner's write: {exc}")


def _record_owner_write(path, whole_file: bool) -> None:
    name = guarded_name(path)
    if name is None:
        return
    with _lock:
        files = dict(_load())
        previous = files.get(name) or {}
        now = time.time()
        if whole_file or previous.get("origin") in (None, AGENT, OWNER):
            record = {"origin": OWNER, "hash": _hash_file(name), "at": now, "session": "", "reason": ""}
        else:
            record = {**previous, "hash": _hash_file(name), "at": now}
        files[name] = record
        _save(files)
    _warned.discard(name)


def trust(path) -> bool:
    """The user reviewed a quarantined file and accepts it as it is now."""
    name = guarded_name(path) or (path if path in GUARDED_FILES else None)
    if name is None:
        return False
    with _lock:
        files = dict(_load())
        files[name] = {
            "origin": OWNER,
            "hash": _hash_file(name),
            "at": time.time(),
            "session": "",
            "reason": "",
        }
        _save(files)
    _warned.discard(name)
    _audit("memory_file_trusted", file=name)
    return True


# ── reading ──


def is_excluded(name: str) -> bool:
    """Whether automatic context leaves this guarded file out (guard on and
    its record untrusted). Logged once per file and process, as OpenClaw."""
    if not get_policy().guard_memory:
        return False
    with _lock:
        record = _load().get(name)
    if not record or record.get("origin") in _TRUSTED:
        return False
    if name not in _warned:
        _warned.add(name)
        logger.warning(
            f"[SECURITY] Leaving {name} out of automatic context: "
            f"{record.get('reason') or 'untrusted'}. Review it in Settings > "
            f"Security > Security check."
        )
    return True


def filter_pointers(pointers: Iterable[Any]) -> List[Any]:
    """Memory previews without those from excluded files."""
    pointers = list(pointers)
    if not get_policy().guard_memory:
        return pointers
    excluded = {name for name in GUARDED_FILES if is_excluded(name)}
    if not excluded:
        return pointers
    kept = []
    for pointer in pointers:
        file_path = str(getattr(pointer, "file_path", "") or "")
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = _root() / candidate
        if guarded_name(candidate) in excluded:
            continue
        kept.append(pointer)
    return kept


def untrusted_files() -> List[Dict[str, Any]]:
    """Guarded files automatic context leaves out, for the security check."""
    if not get_policy().guard_memory:
        return []
    with _lock:
        files = _load()
    out = []
    for name in GUARDED_FILES:
        record = files.get(name)
        if not record or record.get("origin") in _TRUSTED:
            continue
        if not (_root() / name).exists():
            continue
        out.append(
            {
                "name": name,
                "path": str(_root() / name),
                "reason": record.get("reason") or "",
                "since": record.get("since", record.get("at", 0)),
                "last_write": record.get("at", 0),
            }
        )
    return out


# ── what the memory processor distills ──


def admits_user_message(entry: Dict[str, Any]) -> bool:
    """Whether a conversation message goes to the memory queue. A third
    party's message does not while the guard is on."""
    if not entry.get("third_party"):
        return True
    return not get_policy().guard_memory


def admits_agent_message(session_id: Optional[str]) -> bool:
    """Whether an agent reply goes to the memory queue. A reply in a run a
    third party started, or that read outside content, does not while the
    guard is on."""
    if not get_policy().guard_memory:
        return True
    return not _run_concern(session_id)


def _reset_for_tests() -> None:
    with _lock:
        _cache["mtime"] = None
        _cache["files"] = {}
        _warned.clear()
