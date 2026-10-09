# -*- coding: utf-8 -*-
"""Bring what a new release ships into an existing managed install.

A managed install keeps CODE in the install directory (replaced wholesale by
an upgrade) and the user's copies of ``app/data``, ``app/config`` and
``skills`` in the per-user STATE directory. run.py seeds those trees only when
they are absent, so an upgraded install would never receive an action file or
a skill that is new in this release (the Mini Browser's actions, for one), nor
the ``skills_config.json`` entry that enables a new default skill: actions
load from STATE, and a non-empty ``enabled_skills`` list is a whitelist.

:func:`sync_shipped_files` closes that gap, conservatively:

- It records every shipped file it has handled under ``app/data/action/`` and
  ``skills/`` in a manifest, ``STATE/app/data/.shipped_manifest.json``.
- Without a manifest (a fresh install, or the first start after upgrading
  from a release that had none) every shipped file missing from STATE is
  copied. Afterwards only files shipped for the first time since the manifest
  was written, and still missing from STATE, are copied.
- A STATE file is never overwritten (the user may have edited it). A file the
  user deleted after it was recorded is never brought back, nor is a new file
  put into a skill or action folder the user removed.
- ``skills_config.json``: when ``enabled_skills`` is a non-empty whitelist,
  skills that this release newly enables by default are appended, unless the
  user already lists them as enabled or disabled; the names already offered
  are remembered, so a skill the user turned off is never turned back on.

Stdlib only (run.py calls it before dependencies are installed), and it never
raises: every problem is reported through ``log`` and retried at the next
start where that makes sense.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

__all__ = [
    "MANIFEST_RELPATH",
    "SKILLS_CONFIG_RELPATH",
    "SYNC_ROOTS",
    "sync_shipped_files",
]

#: Shipped trees whose NEW files are synced into STATE (relative, POSIX).
SYNC_ROOTS: Tuple[str, ...] = ("app/data/action", "skills")
#: Where the record of handled shipped files and offered skills lives.
MANIFEST_RELPATH = "app/data/.shipped_manifest.json"
SKILLS_CONFIG_RELPATH = "app/config/skills_config.json"

_MANIFEST_VERSION = 1
# Never shipped content: caches and VCS/OS clutter.
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
_SKIP_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
_SKIP_SUFFIXES = (".pyc", ".pyo", ".tmp")
_MAX_LISTED = 8  # copied paths named in the log line


def _default_log(message: str) -> None:
    print(message)


def sync_shipped_files(
    code_root: Any,
    state_root: Any,
    log: Callable[[str], None] = _default_log,
) -> Dict[str, Any]:
    """Copy newly shipped files into STATE and enable newly shipped skills.

    Args:
        code_root: The install's code tree (read only).
        state_root: The user's state tree (written).
        log: Receives one line per notable outcome (default: print).

    Returns:
        ``{"first_run", "copied", "skipped_removed", "failed",
        "skills_enabled", "manifest_written"}``. Never raises.
    """
    report: Dict[str, Any] = {
        "first_run": False,
        "copied": [],
        "skipped_removed": [],
        "failed": [],
        "skills_enabled": [],
        "manifest_written": False,
    }
    try:
        _sync(Path(code_root), Path(state_root), log, report)
    except Exception as exc:  # last line of defence: startup must go on
        _safe_log(log, f"  Warning: syncing shipped files failed: {_describe(exc)}")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# The pass
# ─────────────────────────────────────────────────────────────────────────────


def _sync(
    code_root: Path,
    state_root: Path,
    log: Callable[[str], None],
    report: Dict[str, Any],
) -> None:
    if _same_dir(code_root, state_root):
        return  # a checkout: code and state are one tree, nothing to bring over

    manifest_path = state_root / MANIFEST_RELPATH
    manifest = _load_manifest(manifest_path, log)
    first_run = manifest is None
    report["first_run"] = first_run
    recorded: Set[str] = set(manifest["files"]) if manifest else set()
    offered: Optional[List[str]] = manifest["skills_offered"] if manifest else None

    shipped = _shipped_files(code_root, log)
    handled = _copy_new_files(code_root, state_root, shipped, recorded, report, log)

    shipped_skills, evaluated = _enable_new_skills(
        code_root, state_root, offered, report, log
    )
    skills_record = list(offered or [])
    if evaluated:
        seen = {name.lower() for name in skills_record}
        for name in shipped_skills:
            if name.lower() not in seen:
                skills_record.append(name)
                seen.add(name.lower())

    files_record = sorted(recorded | handled)
    unchanged = (
        manifest is not None
        and files_record == sorted(recorded)
        and skills_record == list(offered or [])
    )
    if not unchanged:
        payload = {
            "version": _MANIFEST_VERSION,
            "files": files_record,
            "skills_offered": skills_record,
        }
        try:
            _write_json_atomic(manifest_path, payload, indent=1)
            report["manifest_written"] = True
        except OSError as exc:
            _safe_log(
                log,
                f"  Warning: could not record shipped files in {MANIFEST_RELPATH}: "
                f"{_describe(exc)}",
            )

    copied = report["copied"]
    if copied:
        shown = ", ".join(copied[:_MAX_LISTED])
        more = (
            f" (+{len(copied) - _MAX_LISTED} more)" if len(copied) > _MAX_LISTED else ""
        )
        _safe_log(log, f"  Added {len(copied)} new shipped file(s): {shown}{more}")
    if report["skills_enabled"]:
        _safe_log(
            log,
            "  Enabled newly shipped skill(s): " + ", ".join(report["skills_enabled"]),
        )


def _copy_new_files(
    code_root: Path,
    state_root: Path,
    shipped: Iterable[str],
    recorded: Set[str],
    report: Dict[str, Any],
    log: Callable[[str], None],
) -> Set[str]:
    """Copy shipped files missing from STATE; return the paths now handled.

    A path is handled once STATE has it, or once the user's removal of its
    folder was respected. A failed copy is left unhandled so the next start
    retries it.
    """
    recorded_units = {unit for unit in map(_unit, recorded) if unit}
    handled: Set[str] = set()
    for rel in shipped:
        if rel in recorded:
            continue  # handled by an earlier start: STATE's copy is the user's
        dest = state_root / rel
        if _exists(dest):
            handled.add(rel)  # never overwrite
            continue
        unit = _unit(rel)
        if unit in recorded_units and not (state_root / unit).is_dir():
            # The user removed this skill (or action folder): keep it removed.
            handled.add(rel)
            report["skipped_removed"].append(rel)
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(code_root / rel, dest)
        except OSError as exc:
            report["failed"].append(rel)
            _safe_log(log, f"  Warning: could not copy {rel}: {_describe(exc)}")
            continue
        handled.add(rel)
        report["copied"].append(rel)
    return handled


def _enable_new_skills(
    code_root: Path,
    state_root: Path,
    offered: Optional[List[str]],
    report: Dict[str, Any],
    log: Callable[[str], None],
) -> Tuple[List[str], bool]:
    """Append newly shipped default skills to the user's whitelist.

    Returns ``(shipped_enabled_names, evaluated)``. ``evaluated`` is False when
    the user's config could not be read, so the names are offered again at
    the next start instead of being recorded as handled.
    """
    shipped_config = _read_json(code_root / SKILLS_CONFIG_RELPATH)
    shipped = _names(
        shipped_config.get("enabled_skills")
        if isinstance(shipped_config, dict)
        else None
    )
    seen = {name.lower() for name in (offered or [])}
    new = [name for name in shipped if name.lower() not in seen]
    if not new:
        return shipped, True

    user_path = state_root / SKILLS_CONFIG_RELPATH
    if not user_path.is_file():
        # No config: the skill loader enables every skill by default.
        return shipped, True
    user_config = _read_json(user_path)
    if not isinstance(user_config, dict):
        _safe_log(
            log,
            f"  Warning: {SKILLS_CONFIG_RELPATH} could not be read; new skills "
            "were not enabled (will retry at the next start)",
        )
        return shipped, False
    enabled = user_config.get("enabled_skills")
    if not isinstance(enabled, list) or not enabled:
        return shipped, True  # no whitelist: every skill is already enabled
    disabled = user_config.get("disabled_skills")
    listed = {
        name.strip().lower()
        for name in list(enabled) + (disabled if isinstance(disabled, list) else [])
        if isinstance(name, str)
    }
    added = [name for name in new if name.strip().lower() not in listed]
    if not added:
        return shipped, True
    user_config["enabled_skills"] = list(enabled) + added
    try:
        _write_json_atomic(user_path, user_config, indent=2)
    except OSError as exc:
        _safe_log(
            log,
            f"  Warning: could not enable new skills in {SKILLS_CONFIG_RELPATH}: "
            f"{_describe(exc)} (will retry at the next start)",
        )
        return shipped, False
    report["skills_enabled"].extend(added)
    return shipped, True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _shipped_files(code_root: Path, log: Callable[[str], None]) -> List[str]:
    """Relative POSIX paths of every shipped file under the sync roots."""

    def report_error(error: OSError) -> None:
        _safe_log(
            log, f"  Warning: could not list {error.filename}: {_describe(error)}"
        )

    found: List[str] = []
    for rel_root in SYNC_ROOTS:
        base = code_root / rel_root
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base, onerror=report_error):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for name in sorted(filenames):
                if name in _SKIP_FILES or name.endswith(_SKIP_SUFFIXES):
                    continue
                path = Path(dirpath) / name
                try:
                    found.append(path.relative_to(code_root).as_posix())
                except ValueError:
                    continue
    return found


def _unit(rel: str) -> Optional[str]:
    """The folder a path belongs to: ``skills/<name>`` or a sub-folder of
    ``app/data/action``. None for a file directly under a sync root."""
    parts = rel.split("/")
    for rel_root in SYNC_ROOTS:
        root_parts = rel_root.split("/")
        depth = len(root_parts)
        if parts[:depth] == root_parts and len(parts) > depth + 1:
            return "/".join(parts[: depth + 1])
    return None


def _load_manifest(path: Path, log: Callable[[str], None]) -> Optional[Dict[str, Any]]:
    """The manifest, or None when there is none (or it cannot be used)."""
    if not _exists(path):
        return None
    data = _read_json(path)
    files = data.get("files") if isinstance(data, dict) else None
    offered = data.get("skills_offered") if isinstance(data, dict) else None
    if not isinstance(files, list) or not isinstance(offered, list):
        _safe_log(
            log,
            f"  Warning: {MANIFEST_RELPATH} is unreadable; rebuilding it "
            "(files missing from your state directory will be restored)",
        )
        return None
    return {
        "files": [f for f in files if isinstance(f, str) and f],
        "skills_offered": _names(offered),
    }


def _names(value: Any) -> List[str]:
    """Distinct non-empty strings of a JSON list, in order."""
    if not isinstance(value, list):
        return []
    names: List[str] = []
    seen: Set[str] = set()
    for item in value:
        if isinstance(item, str) and item.strip() and item.lower() not in seen:
            names.append(item)
            seen.add(item.lower())
    return names


def _read_json(path: Path) -> Any:
    """Parsed JSON, or None when the file is missing or not valid JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: Path, data: Any, *, indent: int) -> None:
    """Write JSON through a temp file and an atomic rename (raises OSError)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _exists(path: Path) -> bool:
    try:
        return path.exists() or path.is_symlink()
    except OSError:
        return True  # unknown: treat as present, never overwrite


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _describe(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0]}" if text else type(exc).__name__


def _safe_log(log: Callable[[str], None], message: str) -> None:
    try:
        log(message)
    except Exception:
        pass
