"""OpenRouter catalog + credits helpers for the settings UI.

OpenRouter exposes a public model catalog at GET /api/v1/models (no auth)
and a credits endpoint at GET /api/v1/credits / GET /api/v1/auth/key
(auth required). The model picker renders the catalog and the balance.

The catalog is cached in-process for 5 minutes — OpenRouter publishes new
models periodically, but ~300 entries is enough payload that we don't
want to re-fetch on every settings page open.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_api_key, get_base_url


_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_CATALOG_TTL_SECONDS = 300  # 5 min — matches OR's own cache windows
_CATALOG_TIMEOUT = 15.0
_CREDITS_TIMEOUT = 10.0

# In-process cache: { base_url: (timestamp, models) }
_catalog_cache: Dict[str, tuple] = {}


def _resolve_base_url(base_url: Optional[str] = None) -> str:
    if base_url:
        return base_url
    configured = get_base_url("openrouter")
    return configured or _DEFAULT_BASE_URL


def _normalize_model(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Project the OpenRouter model record to the fields the UI needs.

    OpenRouter's payload is large per-model (descriptions, hugging-face links,
    etc.). We only ship what the picker actually renders — keeps WS frames
    small and makes the frontend types narrower.
    """
    pricing = raw.get("pricing") or {}
    architecture = raw.get("architecture") or {}
    top_provider = raw.get("top_provider") or {}
    return {
        "id": raw.get("id"),
        "canonical_slug": raw.get("canonical_slug"),
        "name": raw.get("name") or raw.get("id"),
        "description": (raw.get("description") or "")[:500],
        "context_length": raw.get("context_length") or top_provider.get("context_length"),
        "input_modalities": architecture.get("input_modalities") or [],
        "output_modalities": architecture.get("output_modalities") or [],
        "pricing": {
            "prompt": pricing.get("prompt"),
            "completion": pricing.get("completion"),
            "image": pricing.get("image"),
            "input_cache_read": pricing.get("input_cache_read"),
            "input_cache_write": pricing.get("input_cache_write"),
        },
        "supported_parameters": raw.get("supported_parameters") or [],
        "is_moderated": top_provider.get("is_moderated"),
    }


def fetch_models(
    base_url: Optional[str] = None,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Return the OpenRouter model catalog (cached).

    Returns:
        {"success": bool, "models": [...], "fetched_at": int, "error": str?}
    """
    url = _resolve_base_url(base_url)
    cache_key = url

    if not force_refresh:
        entry = _catalog_cache.get(cache_key)
        if entry is not None:
            ts, models = entry
            if (time.time() - ts) < _CATALOG_TTL_SECONDS:
                return {
                    "success": True,
                    "models": models,
                    "fetched_at": int(ts),
                    "cached": True,
                }

    try:
        with httpx.Client(timeout=_CATALOG_TIMEOUT) as client:
            response = client.get(f"{url.rstrip('/')}/models")
        if response.status_code != 200:
            return {
                "success": False,
                "models": [],
                "error": f"OpenRouter /models returned status {response.status_code}",
            }
        raw_models = response.json().get("data") or []
        models = [_normalize_model(m) for m in raw_models if m.get("id")]
        _catalog_cache[cache_key] = (time.time(), models)
        return {
            "success": True,
            "models": models,
            "fetched_at": int(time.time()),
            "cached": False,
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "models": [],
            "error": "Timed out fetching OpenRouter model catalog",
        }
    except httpx.RequestError as exc:
        return {
            "success": False,
            "models": [],
            "error": f"Network error fetching OpenRouter models: {exc}",
        }
    except Exception as exc:  # pragma: no cover — defensive
        return {
            "success": False,
            "models": [],
            "error": f"Unexpected error fetching OpenRouter models: {exc}",
        }


def fetch_credits(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Return account credit info for the configured OpenRouter key.

    Hits /api/v1/credits (preferred — newer endpoint with `total_credits` /
    `total_usage`). Falls back to /api/v1/auth/key on 404 since older keys /
    routes still expose the legacy shape.

    Returns:
        {"success": bool, "balance": float, "usage": float, "limit": float?,
         "label": str?, "error": str?}
    """
    if not api_key:
        api_key = get_api_key("openrouter")
    if not api_key:
        return {
            "success": False,
            "error": "No OpenRouter API key configured",
        }

    url = _resolve_base_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with httpx.Client(timeout=_CREDITS_TIMEOUT) as client:
            response = client.get(f"{url.rstrip('/')}/credits", headers=headers)
            if response.status_code == 404:
                # Legacy fallback
                response = client.get(f"{url.rstrip('/')}/auth/key", headers=headers)

        if response.status_code in (401, 403):
            return {
                "success": False,
                "error": "Invalid API key",
            }
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Credits endpoint returned status {response.status_code}",
            }

        data = response.json().get("data") or {}

        # /credits shape: { total_credits, total_usage }
        # /auth/key shape: { label, usage, limit, is_free_tier, ... }
        total_credits = data.get("total_credits")
        total_usage = data.get("total_usage")
        if total_credits is not None or total_usage is not None:
            credits = float(total_credits) if total_credits is not None else 0.0
            usage = float(total_usage) if total_usage is not None else 0.0
            return {
                "success": True,
                "balance": max(0.0, credits - usage),
                "usage": usage,
                "limit": credits if total_credits is not None else None,
                "label": data.get("label"),
                "is_free_tier": data.get("is_free_tier"),
            }

        # Legacy /auth/key
        usage = float(data.get("usage") or 0.0)
        limit = data.get("limit")
        balance = None
        if limit is not None:
            balance = max(0.0, float(limit) - usage)
        return {
            "success": True,
            "balance": balance,
            "usage": usage,
            "limit": float(limit) if limit is not None else None,
            "label": data.get("label"),
            "is_free_tier": data.get("is_free_tier"),
        }

    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "Timed out fetching OpenRouter credits",
        }
    except httpx.RequestError as exc:
        return {
            "success": False,
            "error": f"Network error fetching OpenRouter credits: {exc}",
        }
    except Exception as exc:  # pragma: no cover — defensive
        return {
            "success": False,
            "error": f"Unexpected error fetching OpenRouter credits: {exc}",
        }


def invalidate_catalog_cache() -> None:
    _catalog_cache.clear()
