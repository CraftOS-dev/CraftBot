# -*- coding: utf-8 -*-
"""
app.network_interface

Single owner of every inbound and outbound HTTP call between the CraftBot
agent (running inside a container) and the craftbot.live dashboard backend.

Why centralise:
  - One place to read the spawn-injected env vars (CONTAINER_AUTH_TOKEN,
    CONTAINER_INSTANCE_ID, CONTAINER_DASHBOARD_URL).
  - One place to do the bearer-auth handshake on both directions.
  - Outbound calls (heartbeat, usage) batch + retry here so callers can
    fire-and-forget without stalling LLM work when the dashboard is unreachable.
  - Inbound endpoints (added in later slices) live next to the outbound client
    so they share auth + config.

Slice 1 scope: outbound `report_usage` only. The agent's existing
`UsageReporter` keeps writing to local SQLite; this client *additionally*
forwards each event to the dashboard so the dashboard's `UsageRecord` table
becomes the source of truth for billing.
"""

from app.network_interface.config import (
    NetworkInterfaceConfig,
    get_config,
    is_enabled,
)
from app.network_interface.outbound import (
    DashboardClient,
    get_dashboard_client,
    report_usage_to_dashboard,
)
from app.network_interface.heartbeat import (
    HeartbeatLoop,
    get_heartbeat_loop,
    start_heartbeat,
)
from app.network_interface.snapshot import (
    build_events_snapshot,
    build_state_snapshot,
    derive_agent_state,
    process_uptime_seconds,
)
from app.network_interface.inbound import (
    INBOUND_PREFIX,
    register_routes,
)
from app.network_interface.server import (
    InboundServer,
)
from app.network_interface.bootstrap import (
    seed_default_provider_from_env,
)
from app.network_interface.state import (
    is_quota_locked,
    get_quota_reset,
    set_quota_lock,
)
from app.network_interface.errors import (
    ManagedQuotaExceededError,
)

__all__ = [
    "NetworkInterfaceConfig",
    "get_config",
    "is_enabled",
    "DashboardClient",
    "get_dashboard_client",
    "report_usage_to_dashboard",
    "HeartbeatLoop",
    "get_heartbeat_loop",
    "start_heartbeat",
    "derive_agent_state",
    "process_uptime_seconds",
    "build_state_snapshot",
    "build_events_snapshot",
    "INBOUND_PREFIX",
    "register_routes",
    "InboundServer",
    "seed_default_provider_from_env",
    "is_quota_locked",
    "get_quota_reset",
    "set_quota_lock",
    "ManagedQuotaExceededError",
]
