"""Pet state store — JSON persistence + token-driven economy.

State is persisted to ``{APP_DATA_PATH}/mascot/pet_state.json``. A single
``PetStore`` singleton owns the in-memory state and emits ``broadcast``
callbacks whenever the React side needs to re-render. The tick loop
(60s) runs the time-based decay; ``on_tokens_consumed`` runs the
token-driven decay + battery earning.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

# Matches #RRGGBB. Used by set_outfit to accept custom colors picked
# via the Customize modal's color-picker swatch in addition to the
# catalog ids ("default", "cream", etc.).
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _is_hex_color(s: Any) -> bool:
    return isinstance(s, str) and bool(_HEX_COLOR_RE.match(s))

from app.config import APP_DATA_PATH
from app.ui_layer.mascot.pet_catalog import (
    ACCENT_COLORS,
    ACCESSORIES,
    ANTENNA_VARIANTS,
    BATTERY_INVENTORY_MAX,
    BATTERY_PURCHASE_COST,
    BODY_COLORS,
    DEFAULT_PET_STATE,
    DEFAULT_UNLOCKS,
    FEED_HUNGER_REDUCTION,
    FEED_MOOD_BONUS,
    HUNGER_DRAGS_MOOD_AT,
    HUNGER_DRAGS_MOOD_RATE_PER_HOUR,
    HUNGER_PER_HOUR_TIME,
    HUNGER_PER_TOKEN,
    LOCATIONS,
    MOOD_DRAIN_PER_TOKEN,
    MOOD_DRIFT_PER_HOUR_TIME,
    PET_MOOD_BONUS,
    STAGE_THRESHOLDS,
    TASK_ABORT_MOOD_PENALTY,
    TASK_SUCCESS_MOOD_BONUS,
    TICK_INTERVAL_S,
    UNLOCK_CATALOG,
    next_stage_threshold,
    stage_for_tokens,
)

PET_DATA_DIR = APP_DATA_PATH / "mascot"
PET_STATE_PATH = PET_DATA_DIR / "pet_state.json"

# Broadcast callback signature. Implementation pushes the dict to all
# connected websockets as a {"type": "pet_state_update", "data": ...} envelope.
BroadcastFn = Callable[[str, Dict[str, Any]], Awaitable[None]]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class PetStore:
    """In-memory pet state with JSON persistence and economy hooks.

    Thread/async usage:
      - All mutations happen on the event loop (no locking needed).
      - ``persist()`` writes synchronously — JSON is tiny (<2 KB).
      - Tick loop is scheduled via ``start()`` / ``stop()``.
    """

    def __init__(self, broadcast: Optional[BroadcastFn] = None) -> None:
        self._state: Dict[str, Any] = {}
        self._broadcast: Optional[BroadcastFn] = broadcast
        self._tick_task: Optional[asyncio.Task] = None
        # Last wall-clock time we ran a tick. Used so the first tick after
        # a long shutdown doesn't crank the decay by the full elapsed time
        # (we cap elapsed at TICK_INTERVAL_S × 2 to keep returning users
        # from finding their pet starving).
        self._last_tick_at: float = time.time()
        # Token accumulator — backend sees CUMULATIVE tokens per item from
        # update_item_tokens, so we track the previously-seen total per
        # item to derive deltas.
        self._task_token_baseline: Dict[str, int] = {}
        # Fractional carry for token-driven decay so small token deltas
        # accumulate properly instead of being floor'd to 0.
        self._hunger_carry: float = 0.0
        self._mood_drain_carry: float = 0.0
        self._load()

    # ─────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if PET_STATE_PATH.exists():
            try:
                with open(PET_STATE_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._state = self._merge_defaults(raw)
                return
            except (json.JSONDecodeError, IOError):
                pass
        self._state = json.loads(json.dumps(DEFAULT_PET_STATE))

    @staticmethod
    def _merge_defaults(loaded: Dict[str, Any]) -> Dict[str, Any]:
        """Backfill any missing keys from defaults so older save files keep working."""
        merged = json.loads(json.dumps(DEFAULT_PET_STATE))
        for k, v in loaded.items():
            if k == "outfit" and isinstance(v, dict):
                merged_outfit = dict(merged["outfit"])
                merged_outfit.update(v)
                merged["outfit"] = merged_outfit
            elif k == "position" and isinstance(v, dict):
                merged["position"] = {
                    "x": float(v.get("x", 0.0)),
                    "y": float(v.get("y", 0.0)),
                }
            elif k == "unlocks" and isinstance(v, list):
                merged["unlocks"] = list({*v, *DEFAULT_UNLOCKS})
            else:
                merged[k] = v
        return merged

    def persist(self) -> None:
        try:
            PET_DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(PET_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except (IOError, OSError):
            pass

    # ─────────────────────────────────────────────────────────────────
    # Snapshot — what the frontend sees
    # ─────────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """Return a serializable snapshot of the current state + catalog."""
        stage = self._state["stage"]
        lifetime = int(self._state["lifetime_tokens"])
        spent = int(self._state.get("spent_tokens", 0))
        return {
            "stage": stage,
            "lifetimeTokens": lifetime,
            "spentTokens": spent,
            # Spendable currency = lifetime minus what's been spent on
            # consumables (batteries). Used by the shop's battery section
            # to gate purchase buttons.
            "spendableTokens": lifetime - spent,
            "mood": int(round(self._state["mood"])),
            "hunger": int(round(self._state["hunger"])),
            "batteryInventory": int(self._state["battery_inventory"]),
            "position": dict(self._state["position"]),
            "location": self._state["location"],
            "outfit": dict(self._state["outfit"]),
            "unlocks": list(self._state["unlocks"]),
            "stageProgress": self._stage_progress(),
            "catalog": self._catalog_snapshot(),
        }

    def _stage_progress(self) -> Dict[str, Any]:
        stage = self._state["stage"]
        tokens = int(self._state["lifetime_tokens"])
        current_threshold = STAGE_THRESHOLDS[stage - 1]
        next_threshold = next_stage_threshold(stage)
        if next_threshold is None:
            return {
                "stage": stage,
                "isMaxStage": True,
                "tokensIntoStage": tokens - current_threshold,
                "tokensForNextStage": None,
                "fraction": 1.0,
            }
        into = max(0, tokens - current_threshold)
        span = next_threshold - current_threshold
        return {
            "stage": stage,
            "isMaxStage": False,
            "tokensIntoStage": into,
            "tokensForNextStage": span,
            "fraction": min(1.0, into / span) if span > 0 else 0.0,
        }

    def _catalog_snapshot(self) -> Dict[str, Any]:
        return {
            "bodyColors": BODY_COLORS,
            "accentColors": ACCENT_COLORS,
            "antennas": ANTENNA_VARIANTS,
            "accessories": ACCESSORIES,
            "locations": LOCATIONS,
            # Shop-driven constants surfaced so the frontend doesn't have to
            # hard-code (and drift from) numbers that live in pet_catalog.py.
            "batteryPurchaseCost": BATTERY_PURCHASE_COST,
            "batteryInventoryMax": BATTERY_INVENTORY_MAX,
        }

    # ─────────────────────────────────────────────────────────────────
    # Broadcast helpers
    # ─────────────────────────────────────────────────────────────────

    def set_broadcast(self, broadcast: BroadcastFn) -> None:
        self._broadcast = broadcast

    async def _emit_state_update(self) -> None:
        if self._broadcast:
            try:
                await self._broadcast("pet_state_update", self.snapshot())
            except Exception:
                pass

    async def _emit_event(self, msg_type: str, data: Dict[str, Any]) -> None:
        if self._broadcast:
            try:
                await self._broadcast(msg_type, data)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────
    # Token consumption — main economy driver
    # ─────────────────────────────────────────────────────────────────

    async def on_task_token_total(
        self,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> None:
        """Called by browser_adapter whenever update_item_tokens fires.

        Backend sends cumulative-per-item totals, so we derive the delta
        against our per-task baseline and feed that into the economy.
        """
        total = int(input_tokens) + int(output_tokens) + int(cache_tokens)
        baseline = self._task_token_baseline.get(task_id, 0)
        delta = total - baseline
        if delta <= 0:
            self._task_token_baseline[task_id] = total
            return
        self._task_token_baseline[task_id] = total
        await self._consume_tokens(delta)

    async def _consume_tokens(self, delta: int) -> None:
        if delta <= 0:
            return

        prev_stage = self._state["stage"]
        prev_unlocks = set(self._state["unlocks"])

        self._state["lifetime_tokens"] = int(self._state["lifetime_tokens"]) + delta

        # Token-driven hunger increase.
        self._hunger_carry += delta * HUNGER_PER_TOKEN
        if self._hunger_carry >= 1.0:
            whole = int(self._hunger_carry)
            self._hunger_carry -= whole
            self._state["hunger"] = _clamp(self._state["hunger"] + whole, 0, 100)

        # Token-driven mood drain.
        self._mood_drain_carry += delta * MOOD_DRAIN_PER_TOKEN
        if self._mood_drain_carry >= 1.0:
            whole = int(self._mood_drain_carry)
            self._mood_drain_carry -= whole
            self._state["mood"] = _clamp(self._state["mood"] - whole, 0, 100)

        # NOTE: batteries are no longer auto-earned. Every battery now
        # comes from an explicit shop purchase (`buy_battery`) that
        # deducts BATTERY_PURCHASE_COST from spendable_tokens.

        # Stage promotion.
        new_stage = stage_for_tokens(self._state["lifetime_tokens"])
        stage_changed = False
        if new_stage != prev_stage:
            self._state["stage"] = new_stage
            stage_changed = True
            # When you reach Stage 2, the free antenna_1 unlocks automatically.
            if new_stage >= 2 and "antenna_1" not in self._state["unlocks"]:
                self._state["unlocks"].append("antenna_1")

        # Re-snapshot unlocks — token milestones might unlock things.
        # (Auto-unlock semantics: any item with cost > 0 still needs explicit
        # purchase via "pet_unlock", but min_stage gates DO open automatically
        # when a stage is reached — so we only re-emit unlocks on stage-up.)
        unlocks_changed = set(self._state["unlocks"]) != prev_unlocks

        self.persist()
        await self._emit_state_update()
        if stage_changed:
            await self._emit_event("pet_stage_up", {
                "stage": new_stage,
                "stageProgress": self._stage_progress(),
            })
        if unlocks_changed:
            await self._emit_event("pet_unlock", {
                "unlocks": list(self._state["unlocks"]),
            })

    # ─────────────────────────────────────────────────────────────────
    # Tick loop — time-based decay
    # ─────────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._tick_task is not None:
            return
        loop = asyncio.get_event_loop()
        self._tick_task = loop.create_task(self._tick_loop())

    def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None

    async def _tick_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(TICK_INTERVAL_S)
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                # Don't let a single tick failure kill the whole loop.
                await asyncio.sleep(TICK_INTERVAL_S)

    async def _tick(self) -> None:
        now = time.time()
        elapsed_s = min(now - self._last_tick_at, TICK_INTERVAL_S * 2.0)
        self._last_tick_at = now
        if elapsed_s <= 0:
            return

        elapsed_h = elapsed_s / 3600.0

        # Time-driven hunger increase.
        self._state["hunger"] = _clamp(
            self._state["hunger"] + HUNGER_PER_HOUR_TIME * elapsed_h,
            0,
            100,
        )

        # Mood drifts toward 50.
        mood = self._state["mood"]
        drift = MOOD_DRIFT_PER_HOUR_TIME * elapsed_h
        if mood > 50:
            mood = max(50, mood - drift)
        elif mood < 50:
            mood = min(50, mood + drift)
        self._state["mood"] = mood

        # Hunger pulls mood toward 0 when high.
        if self._state["hunger"] >= HUNGER_DRAGS_MOOD_AT:
            self._state["mood"] = _clamp(
                self._state["mood"] - HUNGER_DRAGS_MOOD_RATE_PER_HOUR * elapsed_h,
                0,
                100,
            )

        self.persist()
        await self._emit_state_update()

    # ─────────────────────────────────────────────────────────────────
    # Player actions
    # ─────────────────────────────────────────────────────────────────

    async def feed(self) -> Dict[str, Any]:
        """Consume one battery → reduce hunger, bump mood."""
        if self._state["battery_inventory"] <= 0:
            return {"success": False, "reason": "no_battery"}

        self._state["battery_inventory"] = int(self._state["battery_inventory"]) - 1
        self._state["hunger"] = _clamp(
            self._state["hunger"] - FEED_HUNGER_REDUCTION, 0, 100,
        )
        self._state["mood"] = _clamp(
            self._state["mood"] + FEED_MOOD_BONUS, 0, 100,
        )
        self.persist()
        await self._emit_state_update()
        await self._emit_event("pet_fed", {})
        return {"success": True}

    async def buy_battery(self) -> Dict[str, Any]:
        """Spend tokens from the spendable wallet to add 1 battery to
        inventory. lifetime_tokens is NOT decreased — stage gating uses
        the lifetime stat — so the cost lands in spent_tokens instead.
        """
        if self._state["battery_inventory"] >= BATTERY_INVENTORY_MAX:
            return {"success": False, "reason": "inventory_full"}
        lifetime = int(self._state["lifetime_tokens"])
        spent = int(self._state.get("spent_tokens", 0))
        if lifetime - spent < BATTERY_PURCHASE_COST:
            return {"success": False, "reason": "insufficient_tokens"}
        self._state["spent_tokens"] = spent + BATTERY_PURCHASE_COST
        self._state["battery_inventory"] = int(self._state["battery_inventory"]) + 1
        self.persist()
        await self._emit_state_update()
        return {"success": True}

    async def pet(self) -> Dict[str, Any]:
        """Stroke the pet — small mood bump."""
        self._state["mood"] = _clamp(
            self._state["mood"] + PET_MOOD_BONUS, 0, 100,
        )
        self.persist()
        await self._emit_state_update()
        await self._emit_event("pet_petted", {})
        return {"success": True}

    async def on_task_success(self) -> None:
        self._state["mood"] = _clamp(
            self._state["mood"] + TASK_SUCCESS_MOOD_BONUS, 0, 100,
        )
        self.persist()
        await self._emit_state_update()

    async def on_task_abort(self) -> None:
        self._state["mood"] = _clamp(
            self._state["mood"] - TASK_ABORT_MOOD_PENALTY, 0, 100,
        )
        self.persist()
        await self._emit_state_update()

    async def set_position(self, x: float, y: float) -> Dict[str, Any]:
        self._state["position"] = {"x": float(x), "y": float(y)}
        self.persist()
        # No broadcast — the dragging client owns the live position; we just
        # persist it so other tabs / the chat panel pick it up on next load.
        return {"success": True}

    async def set_location(self, location_id: str) -> Dict[str, Any]:
        if location_id not in self._state["unlocks"]:
            return {"success": False, "reason": "not_unlocked"}
        # Confirm it's actually a location.
        entry = UNLOCK_CATALOG.get(location_id)
        if not entry or entry.get("kind") != "location":
            return {"success": False, "reason": "not_a_location"}
        self._state["location"] = location_id
        self.persist()
        await self._emit_state_update()
        return {"success": True}

    async def set_outfit(self, outfit: Dict[str, Any]) -> Dict[str, Any]:
        new_outfit = dict(self._state["outfit"])
        if "body_color" in outfit:
            valid = {c["id"] for c in BODY_COLORS}
            val = outfit["body_color"]
            # Accept catalog ids OR raw #RRGGBB strings from the
            # custom-color swatch in the Customize modal.
            if val in valid or _is_hex_color(val):
                new_outfit["body_color"] = val
        if "accent_color" in outfit:
            valid = {c["id"] for c in ACCENT_COLORS}
            val = outfit["accent_color"]
            if val in valid or _is_hex_color(val):
                new_outfit["accent_color"] = val
        if "antenna" in outfit:
            if outfit["antenna"] in self._state["unlocks"]:
                new_outfit["antenna"] = outfit["antenna"]
        if "accessory" in outfit:
            if outfit["accessory"] is None:
                new_outfit["accessory"] = None
            elif outfit["accessory"] in self._state["unlocks"]:
                new_outfit["accessory"] = outfit["accessory"]
        self._state["outfit"] = new_outfit
        self.persist()
        await self._emit_state_update()
        return {"success": True}

    async def unlock(self, item_id: str) -> Dict[str, Any]:
        """Spend tokens from the spendable wallet to permanently unlock
        an item. lifetime_tokens stays untouched so stage progression is
        unaffected; the cost lands in spent_tokens.
        """
        if item_id in self._state["unlocks"]:
            return {"success": True, "reason": "already_unlocked"}
        entry = UNLOCK_CATALOG.get(item_id)
        if not entry:
            return {"success": False, "reason": "unknown_item"}
        if self._state["stage"] < entry.get("min_stage", 1):
            return {"success": False, "reason": "stage_too_low"}
        cost = int(entry.get("cost", 0))
        spent = int(self._state.get("spent_tokens", 0))
        spendable = int(self._state["lifetime_tokens"]) - spent
        if cost > spendable:
            return {"success": False, "reason": "insufficient_tokens"}
        if cost > 0:
            self._state["spent_tokens"] = spent + cost
        self._state["unlocks"].append(item_id)
        self.persist()
        await self._emit_state_update()
        await self._emit_event("pet_unlock", {"unlocks": list(self._state["unlocks"])})
        return {"success": True}

    def clear_task_baseline(self, task_id: str) -> None:
        """Drop the per-task baseline (called when a task ends)."""
        self._task_token_baseline.pop(task_id, None)


# ─────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────

_pet_store: Optional[PetStore] = None


def get_pet_store() -> PetStore:
    global _pet_store
    if _pet_store is None:
        _pet_store = PetStore()
    return _pet_store
