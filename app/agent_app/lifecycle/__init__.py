"""Unified Agent App lifecycle — shadow/live environment separation.

One flow for first builds and modifies (2026-09-08 shadow rewrite; origin
spec docs/plans/agent-app-unified-lifecycle-plan.md, from the 2026-08-19 CRM
data-loss incident): every code change is developed and verified in a
SHADOW environment — the project's OWN code tree booted a second time on a
hidden port with a FRESH per-boot database (the migration chain replays at
boot; live data is never cloned) and a content-addressed build artifact
(pb/pb_public — the served live build — only changes at promote). A clean
verify PROMOTES: the real project boots with the new code, new migrations
apply to the real pb_data, and the shadow is torn down.

Nothing is copied to make an environment. LIVE and SHADOW are the same tree
with three redirected inputs (port, data dir, artifact dir) — which is why
the copy era's failure modes (locked in-place resets, corrupted partial
copies, sync drift, port squatting) are unrepresentable here: every shadow
boot gets fresh directories and a fresh port, and old state is swept lazily.

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
from app.agent_app.lifecycle.environment import has_live_env, live_db_exists
from app.agent_app.lifecycle.lifecycle import AppLifecycle
from app.agent_app.lifecycle.promoter import Promoter
from app.agent_app.lifecycle.provisioner import ShadowProvisioner

__all__ = [
    "AppLifecycle",
    "BackupEntry",
    "BackupService",
    "BackupStore",
    "ShadowProvisioner",
    "Promoter",
    "has_live_env",
    "live_db_exists",
]
