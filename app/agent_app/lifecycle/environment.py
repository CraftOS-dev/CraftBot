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
class DevInstance:
    """One dev environment: the project's code copied to a hidden port with
    its own (fresh) database. `process` is runtime-only; everything else
    round-trips through the factory-host sidecar record.

    The sidecar key and on-disk root keep their historical "staging" names —
    they are storage details shared with records written by older versions,
    and the boot reaper must keep finding both.
    """

    project_id: str
    dir: Path
    port: int
    created_at: float
    pid: Optional[int] = None
    process: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def to_record(self) -> Dict[str, Any]:
        return {
            "dir": str(self.dir),
            "port": self.port,
            "url": self.url,
            "pid": self.pid,
            "created_at": self.created_at,
        }

    @classmethod
    def from_record(cls, project_id: str, record: Dict[str, Any]) -> "DevInstance":
        return cls(
            project_id=project_id,
            dir=Path(record.get("dir", "")),
            port=int(record.get("port", 0)),
            created_at=float(record.get("created_at", 0)),
            pid=record.get("pid"),
        )
