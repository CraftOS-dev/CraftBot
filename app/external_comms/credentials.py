# -*- coding: utf-8 -*-
"""
app.external_comms.credentials

Simple JSON-file credential storage in .credentials/ folder.
One file per platform (e.g. slack.json, notion.json).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional, Type, TypeVar

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

T = TypeVar("T")

_credentials_dir: Optional[Path] = None


def _get_credentials_dir() -> Path:
    """Get the .credentials directory path, creating it if needed."""
    global _credentials_dir
    if _credentials_dir is None:
        from app.config import PROJECT_ROOT
        _credentials_dir = PROJECT_ROOT / ".credentials"
    _credentials_dir.mkdir(parents=True, exist_ok=True)
    return _credentials_dir


def has_credential(filename: str) -> bool:
    """Check if a credential file exists."""
    return (_get_credentials_dir() / filename).exists()


def load_credential(filename: str, credential_cls: Type[T]) -> Optional[T]:
    """
    Load a credential from a JSON file.

    Args:
        filename: e.g. "slack.json"
        credential_cls: Dataclass type to deserialize into.

    Returns:
        Instance of credential_cls, or None if file doesn't exist.
    """
    path = _get_credentials_dir() / filename
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Only pass fields that exist on the dataclass
        valid_fields = {fld.name for fld in fields(credential_cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return credential_cls(**filtered)
    except Exception as e:
        logger.warning(f"Failed to load credential {filename}: {e}")
        return None


def save_credential(filename: str, credential) -> None:
    """
    Save a credential dataclass to a JSON file.

    Args:
        filename: e.g. "slack.json"
        credential: Dataclass instance to serialize.
    """
    path = _get_credentials_dir() / filename
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(credential), f, indent=2, default=str)
        logger.info(f"Saved credential: {filename}")
    except Exception as e:
        logger.error(f"Failed to save credential {filename}: {e}")


def remove_credential(filename: str) -> bool:
    """
    Remove a credential file.

    Returns:
        True if file was removed, False if it didn't exist.
    """
    path = _get_credentials_dir() / filename
    if path.exists():
        path.unlink()
        logger.info(f"Removed credential: {filename}")
        return True
    return False
