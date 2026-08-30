"""Unified Agent App lifecycle — dev/live environment separation.

One flow for first builds and modifies (spec:
docs/plans/agent-app-unified-lifecycle-plan.md, from the 2026-08-19 CRM
data-loss incident): every code change is developed and verified in a DEV
environment — a runtime copy of the project's code booted on a hidden port
with a FRESH, schema-only database (the migration chain replays at boot;
live data is never cloned). A clean verify PROMOTES: the real project boots
with the new code, new migrations apply to the real pb_data, and the dev
copy is destroyed.

The single invariant this package enforces:

    Nothing writes to a live environment's pb_data except (a) PocketBase's
    migration replay during Promoter.promote(), and (b) a USER-CONFIRMED
    restore of a backup archive (manager.restore_backup, spec
    docs/plans/agent-app-backups-requirements.md FR9 — reversible by
    design: the pre-restore state is captured first, and the restore
    aborts if that capture fails). The agent has no restore action.

There is no stored "delivered" mode flag — the one thing it used to decide
(first vs update promote) is derived from filesystem state via
live_db_exists(), which cannot go stale the way the sidecar flag did.
"""

from app.agent_app.lifecycle.backups import BackupEntry, BackupService, BackupStore
from app.agent_app.lifecycle.environment import (
    DevInstance,
    has_live_env,
    live_db_exists,
)
from app.agent_app.lifecycle.lifecycle import AppLifecycle
from app.agent_app.lifecycle.promoter import Promoter
from app.agent_app.lifecycle.provisioner import DEV_PORT_RANGE, DevProvisioner

__all__ = [
    "AppLifecycle",
    "BackupEntry",
    "BackupService",
    "BackupStore",
    "DevInstance",
    "DevProvisioner",
    "DEV_PORT_RANGE",
    "Promoter",
    "has_live_env",
    "live_db_exists",
]
