"""Pet/mascot persistence and progression layer.

Owns the JSON-backed pet state (stage, mood, hunger, batteries, outfit,
location, unlocks) and the token-driven economy that powers it. The
React-side mascot reads/writes this state via WebSocket events.
"""

from app.ui_layer.mascot.pet_catalog import (
    STAGE_THRESHOLDS,
    STAGE_BODY_HEIGHT,
    UNLOCK_CATALOG,
    DEFAULT_UNLOCKS,
    BODY_COLORS,
    ACCENT_COLORS,
    ANTENNA_VARIANTS,
    ACCESSORIES,
    LOCATIONS,
    stage_for_tokens,
    next_stage_threshold,
)
from app.ui_layer.mascot.pet_store import PetStore, get_pet_store

__all__ = [
    "PetStore",
    "get_pet_store",
    "STAGE_THRESHOLDS",
    "STAGE_BODY_HEIGHT",
    "UNLOCK_CATALOG",
    "DEFAULT_UNLOCKS",
    "BODY_COLORS",
    "ACCENT_COLORS",
    "ANTENNA_VARIANTS",
    "ACCESSORIES",
    "LOCATIONS",
    "stage_for_tokens",
    "next_stage_threshold",
]
