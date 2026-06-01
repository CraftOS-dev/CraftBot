# -*- coding: utf-8 -*-
"""
app.network_interface.config

Reads the three env vars the dashboard's instance-provisioning step injects
into every container at spawn time (see
apps/backend/src/api/instances/index.ts `containerEnv`):

    CONTAINER_AUTH_TOKEN     # per-instance shared bearer secret
    CONTAINER_INSTANCE_ID    # dashboard's Instance.id (cuid)
    CONTAINER_DASHBOARD_URL  # dashboard backend base URL (no trailing slash)

If any is missing the interface is "disabled" — the agent keeps running, all
outbound calls become silent no-ops, and inbound endpoints (when added) refuse
to start. This matches the dashboard's own degradation pattern: a half-
configured deployment must boot rather than crash-loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NetworkInterfaceConfig:
    """Resolved env-var view; immutable per-process."""

    auth_token: str
    instance_id: str
    dashboard_url: str

    @property
    def enabled(self) -> bool:
        return bool(self.auth_token and self.instance_id and self.dashboard_url)


_DEFAULT_DASHBOARD_URL_FALLBACK = "http://localhost:4000"


def _load_from_env() -> NetworkInterfaceConfig:
    raw_url = os.environ.get("CONTAINER_DASHBOARD_URL", "").strip()
    # Strip a single trailing slash so we can concatenate paths cleanly.
    dashboard_url = raw_url.rstrip("/") if raw_url else ""
    return NetworkInterfaceConfig(
        auth_token=os.environ.get("CONTAINER_AUTH_TOKEN", "").strip(),
        instance_id=os.environ.get("CONTAINER_INSTANCE_ID", "").strip(),
        dashboard_url=dashboard_url,
    )


_config: Optional[NetworkInterfaceConfig] = None


def get_config() -> NetworkInterfaceConfig:
    """Process-wide cached config. Env reads happen once at first call."""
    global _config
    if _config is None:
        _config = _load_from_env()
    return _config


def is_enabled() -> bool:
    """True iff all three spawn-injected env vars are present and non-empty."""
    return get_config().enabled


def reset_for_tests() -> None:
    """Drop the cached config; used by tests that monkeypatch env vars."""
    global _config
    _config = None


def dashboard_endpoint(path: str) -> str:
    """Join a relative path like `/api/instance-callback/usage` onto the
    configured dashboard URL, preserving any base path the URL already has.
    Returns empty string when disabled so callers can short-circuit cleanly."""
    cfg = get_config()
    if not cfg.enabled:
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return f"{cfg.dashboard_url}{path}"


def fallback_dashboard_url() -> str:
    """The dev-mode default when CONTAINER_DASHBOARD_URL is unset. Exposed
    only so tests / dev tooling can reference the same constant."""
    return _DEFAULT_DASHBOARD_URL_FALLBACK
