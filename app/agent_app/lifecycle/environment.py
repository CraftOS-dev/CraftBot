"""Environment identity: the dev-instance value object and the one
structural predicate the lifecycle branches on.

live_db_exists() replaces the retired "delivered" sidecar flag. The flag
could diverge from reality (it did, 2026-08-19: a two-week-in-use CRM read
as never-delivered and its live DB was restored to a stale baseline); the
filesystem cannot — a live database either exists or it does not.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


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


@dataclass
class ShadowInstance:
    """One SHADOW environment: the project's OWN code tree booted on a hidden
    port with a fresh database and a content-addressed build artifact.
    Nothing is copied — `dir` is the per-boot state directory (data + logs),
    not a code tree. `process` is runtime-only; everything else round-trips
    through the factory-host sidecar record.

    The sidecar key keeps its historical "staging" name — a storage detail
    the reapers and redirects already speak.
    """

    project_id: str
    dir: Path  # <agent_app>/_shadow/<project>/<boot-id>/ — data, logs
    port: int
    created_at: float
    public_dir: Path = Path("")  # the served build artifact (content-addressed)
    pid: Optional[int] = None
    process: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def data_dir(self) -> Path:
        return self.dir / "pb_data"

    @property
    def log_dir(self) -> Path:
        return self.dir / "logs"

    def to_record(self) -> Dict[str, Any]:
        return {
            "dir": str(self.dir),
            "port": self.port,
            "url": self.url,
            "pid": self.pid,
            "public_dir": str(self.public_dir),
            "created_at": self.created_at,
        }
