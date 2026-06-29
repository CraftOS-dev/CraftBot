"""Pet system catalog: stage thresholds, unlocks, decay/earn constants.

All tunable economy numbers live here so balancing only touches one file.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ─────────────────────────────────────────────────────────────────────
# Stages — token thresholds drive progression
# ─────────────────────────────────────────────────────────────────────

# stage 1: 0 tokens (hatchling)
# stage 2: 10M tokens (chick) — antenna appears
# stage 3: 50M tokens (kid)
# stage 4: 200M tokens (teen)
# stage 5: 800M tokens (mature)
STAGE_THRESHOLDS: List[int] = [0, 10_000_000, 50_000_000, 200_000_000, 800_000_000]

# Body height in px per stage. Stage 5 = today's mature size.
STAGE_BODY_HEIGHT: Dict[int, int] = {
    1: 75,
    2: 95,
    3: 115,
    4: 140,
    5: 160,
}


def stage_for_tokens(lifetime_tokens: int) -> int:
    """Return the stage (1..5) for a given lifetime-tokens count."""
    stage = 1
    for i, threshold in enumerate(STAGE_THRESHOLDS, start=1):
        if lifetime_tokens >= threshold:
            stage = i
    return stage


def next_stage_threshold(stage: int) -> int | None:
    """Return the token threshold needed for the next stage, or None at max."""
    if stage >= len(STAGE_THRESHOLDS):
        return None
    return STAGE_THRESHOLDS[stage]


# ─────────────────────────────────────────────────────────────────────
# Economy — token-driven decay and battery earning
# ─────────────────────────────────────────────────────────────────────

# Time decay (per tick). Tick runs every 60 seconds.
# Rates are now 10× slower than the original tuning so casual use
# doesn't outpace the player's ability to refill batteries.
TICK_INTERVAL_S: float = 60.0
HUNGER_PER_HOUR_TIME: float = 1.0 / 60.0  # +1 hunger per 60 hours of idle
MOOD_DRIFT_PER_HOUR_TIME: float = 0.1     # mood drifts toward 50 very slowly

# Token-driven (per token consumed). Also 10× slower than the original
# tuning (+1 hunger per 100K tokens, +1 mood drain per 200K tokens).
HUNGER_PER_TOKEN: float = 1.0 / 100_000.0
MOOD_DRAIN_PER_TOKEN: float = 1.0 / 200_000.0

# Battery inventory cap. Buying past this is blocked by pet_store.
BATTERY_INVENTORY_MAX: int = 99

# Shop battery purchase cost (tokens per battery). Batteries are NOT
# auto-earned anymore — every battery comes from a deliberate shop
# purchase that deducts from spendable_tokens.
BATTERY_PURCHASE_COST: int = 5_000

# Feed effect.
FEED_HUNGER_REDUCTION: int = 10
FEED_MOOD_BONUS: int = 5

# Pet/stroke effect.
PET_MOOD_BONUS: int = 3

# Task outcome bonuses (fired by the existing successTaskCount / abortedTaskCount).
TASK_SUCCESS_MOOD_BONUS: int = 3
TASK_ABORT_MOOD_PENALTY: int = 5

# Hunger-pulls-mood threshold (hunger ≥ this drags mood toward 0).
# Rate is also 10× slower than the original tuning.
HUNGER_DRAGS_MOOD_AT: int = 80
HUNGER_DRAGS_MOOD_RATE_PER_HOUR: float = 0.2


# ─────────────────────────────────────────────────────────────────────
# Customization — visual variants (all free)
# ─────────────────────────────────────────────────────────────────────

# Body colors. Frontend reads these as SVG fill values.
BODY_COLORS: List[Dict[str, str]] = [
    {"id": "default", "label": "Bone", "value": "#FFFEFE"},
    {"id": "cream",   "label": "Cream", "value": "#FFE7C2"},
    {"id": "sky",     "label": "Sky",   "value": "#B3DCFF"},
    {"id": "mint",    "label": "Mint",  "value": "#B6F0C4"},
    {"id": "lilac",   "label": "Lilac", "value": "#D9BFFF"},
    {"id": "peach",   "label": "Peach", "value": "#FFB6A6"},
]

# Accent color (applied to BOTH eyes and antenna).
ACCENT_COLORS: List[Dict[str, str]] = [
    {"id": "default",   "label": "CraftBot Orange", "value": "#FF4F19"},
    {"id": "blue",      "label": "Electric Blue",    "value": "#3A8DFF"},
    {"id": "green",     "label": "Emerald",           "value": "#28C76F"},
    {"id": "purple",    "label": "Violet",            "value": "#9C5AFF"},
    {"id": "pink",      "label": "Hot Pink",          "value": "#FF4FA8"},
    {"id": "gold",      "label": "Gold",              "value": "#E8B100"},
]


# ─────────────────────────────────────────────────────────────────────
# Unlock catalog — paid by lifetime tokens
# ─────────────────────────────────────────────────────────────────────

# Antenna variants (only visible Stage 2+). Variant 1 is free at Stage 2.
ANTENNA_VARIANTS: List[Dict] = [
    {"id": "antenna_1", "label": "Stub",        "cost": 0,           "min_stage": 2},
    {"id": "antenna_2", "label": "Curved",      "cost": 2_000_000,   "min_stage": 2},
    {"id": "antenna_3", "label": "Double",      "cost": 10_000_000,  "min_stage": 3},
    {"id": "antenna_4", "label": "Bulb",        "cost": 30_000_000,  "min_stage": 3},
    {"id": "antenna_5", "label": "Crown Spike", "cost": 60_000_000,  "min_stage": 4},
]

# Accessories (head overlays). null/None = no accessory.
ACCESSORIES: List[Dict] = [
    {"id": "hat_cap",      "label": "Cap",      "cost": 100_000,    "min_stage": 1},
    {"id": "hat_beanie",   "label": "Beanie",   "cost": 500_000,    "min_stage": 2},
    {"id": "hat_headband", "label": "Headband", "cost": 2_000_000,  "min_stage": 2},
    {"id": "hat_halo",     "label": "Halo",     "cost": 20_000_000, "min_stage": 4},
    {"id": "hat_crown",    "label": "Crown",    "cost": 80_000_000, "min_stage": 5},
]

# Locations (backgrounds).
LOCATIONS: List[Dict] = [
    {
        "id": "grass_field",
        "label": "Grass Field",
        "cost": 0,
        "day_image":   "/mascot-backgrounds/background_1_day.jpg",
        "night_image": "/mascot-backgrounds/background_1_night.jpg",
        "image_grass_y":  "75%",
        "ground_line_y":  "81%",
    },
    {
        "id": "workshop",
        "label": "Workshop",
        "cost": 500_000,
        "day_image":   "/mascot-backgrounds/background_2_day.jpg",
        "night_image": "/mascot-backgrounds/background_2_night.jpg",
        "image_grass_y":  "75%",
        "ground_line_y":  "81%",
    },
    {
        "id": "beach",
        "label": "Beach",
        "cost": 5_000_000,
        "day_image":   "/mascot-backgrounds/background_3_day.jpg",
        "night_image": "/mascot-backgrounds/background_3_night.jpg",
        "image_grass_y":  "75%",
        "ground_line_y":  "81%",
    },
    {
        "id": "starfield",
        "label": "Starfield",
        "cost": 30_000_000,
        "day_image":   "/mascot-backgrounds/background_4_day.jpg",
        "night_image": "/mascot-backgrounds/background_4_night.jpg",
        "image_grass_y":  "75%",
        "ground_line_y":  "81%",
    },
]


# Full lookup of every unlockable item by id → entry.
UNLOCK_CATALOG: Dict[str, Dict] = {}
for entry in ANTENNA_VARIANTS:
    UNLOCK_CATALOG[entry["id"]] = {**entry, "kind": "antenna"}
for entry in ACCESSORIES:
    UNLOCK_CATALOG[entry["id"]] = {**entry, "kind": "accessory"}
for entry in LOCATIONS:
    UNLOCK_CATALOG[entry["id"]] = {
        "id": entry["id"],
        "label": entry["label"],
        "cost": entry["cost"],
        "min_stage": 1,
        "kind": "location",
    }


# Items unlocked from day one (no token cost AND min_stage 1).
DEFAULT_UNLOCKS: List[str] = [
    entry["id"]
    for entry in UNLOCK_CATALOG.values()
    if entry.get("cost", 0) == 0 and entry.get("min_stage", 1) <= 1
]
# Always include antenna_1 (free, gated by stage 2 — store auto-unlocks on stage-up).
if "antenna_1" not in DEFAULT_UNLOCKS:
    pass  # antenna_1 has cost 0 but min_stage 2, so it auto-unlocks on stage-up


# ─────────────────────────────────────────────────────────────────────
# Defaults — fresh pet state
# ─────────────────────────────────────────────────────────────────────

DEFAULT_PET_STATE: Dict = {
    "stage": 1,
    "lifetime_tokens": 0,
    # Tokens spent on consumables (only batteries today). Lifetime grows
    # monotonically; spent grows whenever the player buys batteries.
    # spendable = lifetime - spent.
    "spent_tokens": 0,
    "mood": 50,
    "hunger": 30,
    "battery_inventory": 0,
    "position": {"x": 0.0, "y": 0.0},
    "location": "grass_field",
    "outfit": {
        "body_color": "default",
        "accent_color": "default",
        "antenna": "antenna_1",
        "accessory": None,
    },
    "unlocks": list(DEFAULT_UNLOCKS),
}
