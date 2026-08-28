# -*- coding: utf-8 -*-
"""Credential pools with per-error-class cooldowns (Phase 5, FR-7).

Pool per provider = [primary api_keys key] + extra_api_keys extras from
settings.json. Strategy is fill-first: always serve the FIRST key that is
not cooling down, which keeps traffic pinned to the primary (provider-side
prompt caches stay warm) and only rotates while a key is cooling.

Cooldown table (adapted from Hermes' error classes to our ErrorCategory,
docs/PROVIDER_LAYER_CATCHUP.md section 11.1):

    RATE_LIMIT   keep once; from the 2nd consecutive hit cool 60s,
                 doubling per repeat up to 15 min
    CREDIT/QUOTA cool 1h immediately (billing exhaustion)
    AUTH         cool 5 min (bad/revoked key)
    others       no credential action (provider-level, handled by fallback)

State is in-memory with best-effort persistence to
<project>/.credentials/pool_state.json; keys are stored as SHA-256
fingerprints, never raw. Everything fails open: with no extras configured,
resolve() returns the primary key every time — bit-identical to the
pre-pool behavior (NFR-3/NFR-1).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.utils.logger import logger

_RATE_LIMIT_BASE_COOLDOWN = 60.0
_RATE_LIMIT_MAX_COOLDOWN = 900.0
_BILLING_COOLDOWN = 3600.0
_AUTH_COOLDOWN = 300.0

_lock = threading.Lock()
# fingerprint -> {"cooling_until": float, "reason": str, "consecutive_rl": int}
_state: Optional[Dict[str, Dict[str, Any]]] = None
# provider -> fingerprint of the credential most recently served
_last_served: Dict[str, str] = {}


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _state_path() -> Optional[Path]:
    # Same .credentials/ directory the OAuth backends use.
    try:
        from craftos_integrations.credentials_store import _credentials_dir  # type: ignore

        return _credentials_dir() / "pool_state.json"
    except Exception:
        try:
            from app.config import SETTINGS_CONFIG_PATH  # type: ignore

            return (
                Path(SETTINGS_CONFIG_PATH).parents[2]
                / ".credentials"
                / "pool_state.json"
            )
        except Exception:
            return None


def _load_state() -> Dict[str, Dict[str, Any]]:
    global _state
    if _state is not None:
        return _state
    path = _state_path()
    try:
        _state = (
            json.loads(path.read_text(encoding="utf-8"))
            if path and path.exists()
            else {}
        )
    except Exception:
        _state = {}
    if not isinstance(_state, dict):
        _state = {}
    return _state


def _save_state() -> None:
    path = _state_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_load_state(), indent=1, sort_keys=True), encoding="utf-8"
        )
    except Exception as e:  # pragma: no cover — persistence is best-effort
        logger.debug(f"[POOL] state persist failed: {e}")


def reset_state_for_tests() -> None:
    global _state, _last_served
    with _lock:
        _state = {}
        _last_served = {}


def _pool_for(provider: str) -> List[str]:
    """[primary] + extras from settings; empty when the app layer is absent."""
    try:
        from app.config import get_api_key, get_extra_api_keys  # type: ignore

        primary = get_api_key(provider) or ""
        extras = get_extra_api_keys(provider)
        pool = ([primary] if primary else []) + [k for k in extras if k]
        # De-dup preserving order.
        seen: set = set()
        return [k for k in pool if not (k in seen or seen.add(k))]
    except Exception:
        return []


def has_pool(provider: str) -> bool:
    """True when more than one credential is configured for the provider."""
    return len(_pool_for(provider)) > 1


def resolve(provider: str, default: Optional[str] = None) -> Optional[str]:
    """Fill-first: the first non-cooling credential; all cooling -> primary."""
    pool = _pool_for(provider)
    if not pool:
        return default
    now = time.time()
    with _lock:
        state = _load_state()
        chosen = pool[0]
        for key in pool:
            entry = state.get(_fingerprint(key))
            if not entry or float(entry.get("cooling_until", 0)) <= now:
                chosen = key
                break
        _last_served[provider] = _fingerprint(chosen)
        return chosen


def make_resolver(provider: str, fallback_key: str):
    """Callable for per-request auth-header resolution in the SDK clients."""

    def _resolve() -> str:
        return resolve(provider, default=fallback_key) or fallback_key

    return _resolve


def note_failure(provider: str, category: Optional[str]) -> None:
    """Apply the cooldown table to the credential last served for provider.

    ``category`` is an ErrorCategory.value string (decoupled from the enum so
    this module has no import edge into the error layer).
    """
    if not category:
        return
    fp = _last_served.get(provider)
    if fp is None:
        return
    if not has_pool(provider):
        return  # single key: nothing to rotate to; leave state untouched
    now = time.time()
    with _lock:
        state = _load_state()
        entry = state.setdefault(fp, {"consecutive_rl": 0})
        if category == "rate_limit":
            entry["consecutive_rl"] = int(entry.get("consecutive_rl", 0)) + 1
            n = entry["consecutive_rl"]
            if n >= 2:
                cooldown = min(
                    _RATE_LIMIT_BASE_COOLDOWN * (2 ** (n - 2)),
                    _RATE_LIMIT_MAX_COOLDOWN,
                )
                entry["cooling_until"] = now + cooldown
                entry["reason"] = "rate_limit"
                logger.warning(
                    f"[POOL] {provider}: credential {fp} cooling {cooldown:.0f}s (rate limit)"
                )
        elif category in ("credit", "quota"):
            entry["cooling_until"] = now + _BILLING_COOLDOWN
            entry["reason"] = "billing"
            logger.warning(f"[POOL] {provider}: credential {fp} cooling 1h (billing)")
        elif category == "auth":
            entry["cooling_until"] = now + _AUTH_COOLDOWN
            entry["reason"] = "auth"
            logger.warning(f"[POOL] {provider}: credential {fp} cooling 5m (auth)")
        else:
            return
        _save_state()


def note_success(provider: str) -> None:
    """Clear failure bookkeeping for the credential that just served."""
    fp = _last_served.get(provider)
    if fp is None:
        return
    with _lock:
        state = _load_state()
        if fp in state:
            state.pop(fp, None)
            _save_state()
