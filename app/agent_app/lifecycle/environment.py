"""Environment identity: the structural predicates the lifecycle branches on.

live_db_exists() replaces the retired "delivered" sidecar flag. The flag
could diverge from reality (it did, 2026-08-19: a two-week-in-use CRM read
as never-delivered and its live DB was restored to a stale baseline); the
filesystem cannot — a live database either exists or it does not.

The running-instance value object (a shadow's port, dir, pid, token) lives in
app.agent_app.instances.Instance now — one type for live and shadow, keyed by
a stable instance id, so nothing infers identity from a bare port.
"""

from pathlib import Path
from typing import Union


def live_db_exists(project_path: Union[str, Path]) -> bool:
    """True when the project's LIVE environment has a real database.

    This is the first-vs-update promote predicate: absent -> the promote
    boot creates pb_data fresh from the migration chain (first delivery);
    present -> the boot applies only new migrations on top and the data is
    otherwise untouched. External apps have no pb/ shape and never match —
    ask has_live_env() when the project might be one.
    """
    try:
        return (Path(project_path) / "pb" / "pb_data" / "data.db").exists()
    except (TypeError, OSError):
        return False


def has_live_env(project, host) -> bool:
    """True when `project` has a LIVE environment to protect — the one
    build-vs-modify predicate for callers that may hold an external app.

    Native apps answer structurally (live_db_exists); external apps have no
    pb/ shape, so the nearest structural fact is whether a promote ever
    succeeded (host.delivered_at — a write-once timestamp, not the retired
    mode flag). `host` is passed in, never imported: this module stays
    import-clean below the factory host.
    """
    if getattr(project, "project_type", "native") == "external":
        return host.delivered_at(project.id) is not None
    return live_db_exists(project.path)
