"""Persistent anonymous instance ID.

A UUID4 generated once per CraftBot installation and sent to the
marketplace server as the X-CraftBot-Instance header. Pseudonymous: not
derived from and never linked to any personal data.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import APP_CONFIG_PATH

logger = logging.getLogger(__name__)

INSTANCE_FILE_PATH = APP_CONFIG_PATH / "instance.json"

_instance_id_cache: Optional[str] = None


def get_instance_id() -> str:
    """Return the persistent instance UUID, creating it on first call."""
    global _instance_id_cache
    if _instance_id_cache:
        return _instance_id_cache

    try:
        if INSTANCE_FILE_PATH.exists():
            with open(INSTANCE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            instance_id = data.get("instance_id", "")
            if instance_id:
                _instance_id_cache = instance_id
                return instance_id
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[MARKETPLACE] Could not read instance.json, recreating: {e}")

    instance_id = str(uuid.uuid4())
    try:
        INSTANCE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INSTANCE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "instance_id": instance_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                f,
                indent=2,
            )
    except OSError as e:
        # Non-fatal: a fresh ID per session is acceptable degradation.
        logger.warning(f"[MARKETPLACE] Could not persist instance.json: {e}")

    _instance_id_cache = instance_id
    return instance_id
