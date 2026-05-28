"""JSON-file storage in <project_root>/.credentials/.

Two parallel APIs share the same on-disk format and directory:

  - ``save_credential`` / ``load_credential`` / ``has_credential`` /
    ``remove_credential``: per-integration credentials (auth tokens,
    access tokens, OAuth refresh tokens, etc.). Files like
    ``github.json``, ``slack.json``.

  - ``save_config`` / ``load_config`` / ``has_config`` /
    ``remove_config``: per-integration runtime config (watch tags,
    channel filters, polling intervals, etc.). Files like
    ``github_config.json``, ``slack_config.json``.

The two are kept in separate files so saving config never rewrites a
credential file (less risk for the secret-bearing data, easier diffing,
clearer mental model). Both use the same JSON-of-dataclass shape.

The directory location comes from ``ConfigStore.project_root``, which the
host sets via ``configure(project_root=...)``.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional, Type, TypeVar

from .config import ConfigStore
from .logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def _credentials_dir() -> Path:
    path = ConfigStore.project_root / ".credentials"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
    return path


# ════════════════════════════════════════════════════════════════════════
# Internal: shared I/O for both credentials and config
# ════════════════════════════════════════════════════════════════════════


def _load_dataclass(filename: str, cls: Type[T], kind: str) -> Optional[T]:
    """Read a JSON file and instantiate ``cls`` with the matching fields.

    Unknown JSON keys are silently dropped (so removing a field from the
    dataclass doesn't break loading older files). ``kind`` is just a log
    label ("credential" / "config")."""
    path = _credentials_dir() / filename
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        valid = {fld.name for fld in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})
    except Exception as e:
        logger.warning(f"Failed to load {kind} {filename}: {e}")
        return None


def _save_dataclass(filename: str, obj, kind: str) -> None:
    """Serialize a dataclass instance to ``.credentials/<filename>``."""
    path = _credentials_dir() / filename
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(obj), f, indent=2, default=str)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        logger.info(f"Saved {kind}: {filename}")
    except Exception as e:
        logger.error(f"Failed to save {kind} {filename}: {e}")


def _remove(filename: str, kind: str) -> bool:
    path = _credentials_dir() / filename
    if path.exists():
        path.unlink()
        logger.info(f"Removed {kind}: {filename}")
        return True
    return False


# ════════════════════════════════════════════════════════════════════════
# Credentials API
# ════════════════════════════════════════════════════════════════════════


def has_credential(filename: str) -> bool:
    return (_credentials_dir() / filename).exists()


def load_credential(filename: str, credential_cls: Type[T]) -> Optional[T]:
    return _load_dataclass(filename, credential_cls, "credential")


def save_credential(filename: str, credential) -> None:
    _save_dataclass(filename, credential, "credential")


def remove_credential(filename: str) -> bool:
    return _remove(filename, "credential")


# ════════════════════════════════════════════════════════════════════════
# Config API — same on-disk layout, different filename convention
# ════════════════════════════════════════════════════════════════════════


def has_config(filename: str) -> bool:
    return (_credentials_dir() / filename).exists()


def load_config(filename: str, config_cls: Type[T]) -> Optional[T]:
    return _load_dataclass(filename, config_cls, "config")


def save_config(filename: str, config) -> None:
    _save_dataclass(filename, config, "config")


def remove_config(filename: str) -> bool:
    return _remove(filename, "config")
