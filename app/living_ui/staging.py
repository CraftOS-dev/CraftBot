"""
Staging copies of DELIVERED Living UI apps — the modify-era half of
test-junk isolation (spec: plans/quizzical-greeting-alpaca).

Once an app is delivered its pb_data holds real user data AND PocketBase
serves the frontend from disk per-request (--publicDir pb/pb_public, which
the gate's vite build overwrites with emptyOutDir: true). So on a delivered
app, running the gate against the real directory blanks the live UI, and
letting the agent/verifier test against the real port pollutes real data.

The staging copy fixes both mechanically: a full project copy under
living_ui/_staging/project/<id>/ with a cloned DB, booted on a hidden port.
All gating, relaunching, agent testing and walk-verification happen there;
the real app keeps serving the old working code untouched. On a clean
verify, the caller "flips" — relaunches the real project (new migrations
apply to real data at boot) and destroys the copy, and every test record
dies with it.

Composition mirrors V2Runner: the manager constructs and drives this class;
it never reaches back into the manager or the registry. The authoritative
"a staging copy exists" record lives in the factory host sidecar
(.factory/host.json, key "staging") — actions redirect from it, the boot
reaper kills from it, clearing it ends staging mode.
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.living_ui.pb_data_io import snapshot_pb_data

# Outside the manager's 3100-3199 pool on purpose: _load_projects rebuilds
# port bookkeeping from registered projects only, and cleanup_on_startup's
# orphan killer scans that range — staging owns its ports and its reaping.
STAGING_PORT_RANGE = (3900, 3999)

# Same guard the wizard uses for its staging ids: nothing outside this
# pattern ever becomes part of an rmtree'd path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")

# What a staging copy takes from the real project. pb_data arrives via the
# sqlite backup API (never a file copy of a live WAL DB); pb_public is
# deliberately absent — the gate's build step recreates it inside the copy.
# triggers.json MUST travel: without it the copy's trigger guard declares
# nothing, every ⚡ fire 400s, the walker fails an unfixable "defect", and
# the arc sticks (observed live 2026-08-06, kanban board — three identical
# STUCKs on one missing file).
_COPY_FILES = ("manifest.json", "operations.json", "triggers.json", "LIVING_UI.md")
_COPY_CREDS = (".superuser", ".agent-token")
_COPY_DIRS = ("frontend", "pb/pb_hooks", "pb/pb_migrations", ".lui", "reference")

# What sync_code refreshes on each fix-mission iteration: the agent-owned
# paths (ownership rule, agent-guide §1) — never manifest.json (the copy's
# port rewrite must survive) and never pb/pb_data (the agent's in-app test
# data persists across iterations).
_SYNC_FILES = ("operations.json", "triggers.json", "LIVING_UI.md")
_SYNC_DIRS = ("frontend/src", "pb/pb_hooks", "pb/pb_migrations", "reference")
_SYNC_PKG = ("frontend/package.json", "frontend/package-lock.json")


@dataclass
class StagingInstance:
    """One staging copy. `process` is runtime-only; everything else
    round-trips through the sidecar record."""

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
    def from_record(cls, project_id: str, record: Dict[str, Any]) -> "StagingInstance":
        return cls(
            project_id=project_id,
            dir=Path(record.get("dir", "")),
            port=int(record.get("port", 0)),
            created_at=float(record.get("created_at", 0)),
            pid=record.get("pid"),
        )


class StagingSupervisor:
    """Creates, refreshes, destroys and reaps staging copies. Knows nothing
    about the manager's registry, sessions or broadcasting — the manager
    composes this class; it never reaches back."""

    def __init__(self, living_ui_dir: Path, v2_runner) -> None:
        self.living_ui_dir = Path(living_ui_dir)
        self.root = self.living_ui_dir / "_staging" / "project"
        self.v2_runner = v2_runner
        # Live process handles, keyed by project id. Best-effort only —
        # after a CraftBot restart the pid in the sidecar record is all
        # that's left, and destroy/reap fall back to it.
        self._processes: Dict[str, subprocess.Popen] = {}

    # ── create / refresh ───────────────────────────────────────────────────
    async def create_copy(self, project) -> StagingInstance:
        """Build a fresh staging copy of `project` (code + DB clone) and
        rewrite its identity for a hidden port. Does NOT boot it — the
        manager runs the shared launch pipeline against the returned dir.
        Raises on failure; a partial copy is removed."""
        if not _ID_RE.match(project.id or ""):
            raise ValueError(f"unsafe project id for staging: {project.id!r}")
        src = Path(project.path)
        if not (src / "manifest.json").exists():
            raise FileNotFoundError(f"not a Living UI project: {src}")

        staging_dir = self.root / project.id
        if staging_dir.exists():
            self._guarded_rmtree(staging_dir)
        staging_dir.mkdir(parents=True)

        try:
            for rel in _COPY_FILES + _COPY_CREDS:
                f = src / rel
                if f.exists():
                    shutil.copy2(f, staging_dir / rel)
            for rel in _COPY_DIRS:
                d = src / rel
                if d.is_dir():
                    # node_modules rides along inside frontend/ — without it
                    # the gate cold-installs for up to 600 s per staging boot.
                    shutil.copytree(d, staging_dir / rel, symlinks=True)
            (staging_dir / "logs").mkdir(exist_ok=True)

            # DB clone: consistent even while the real app is serving.
            snapshot_pb_data(
                src / "pb" / "pb_data",
                staging_dir / "pb" / "pb_data",
                self.living_ui_dir,
            )

            port = self._free_port()
            self._rewrite_manifest_port(staging_dir, port)

            # The port rewrite invalidated the system-hash canon; kit-sync
            # re-vendors the kit and re-records hashes (same recovery the
            # ZIP-import path uses) — without it the gate's ownership step
            # fails with "modified: manifest.json".
            await self.v2_runner.kit_sync(staging_dir)
        except Exception:
            self._guarded_rmtree(staging_dir)
            raise

        instance = StagingInstance(
            project_id=project.id,
            dir=staging_dir,
            port=port,
            created_at=time.time(),
        )
        logger.info(
            f"[LIVING_UI:STAGING] created copy of {project.id} at "
            f"{staging_dir} (port {port})"
        )
        return instance

    def sync_code(self, project, staging_dir: Path) -> None:
        """Refresh the agent-owned paths real → staging (fix-mission
        iterations edit the real files; the staging copy is what gets gated
        and served). Keeps staging pb_data and the rewritten manifest."""
        src = Path(project.path)
        staging_dir = Path(staging_dir)
        if not (staging_dir / "manifest.json").exists():
            raise FileNotFoundError(f"staging copy missing at {staging_dir}")

        # A changed package.json means new/changed deps: drop node_modules so
        # the pipeline's install step runs for real instead of being skipped.
        for rel in _SYNC_PKG:
            s, d = src / rel, staging_dir / rel
            if s.exists() and (not d.exists() or s.read_bytes() != d.read_bytes()):
                shutil.copy2(s, d)
                nm = staging_dir / "frontend" / "node_modules"
                if nm.is_dir():
                    logger.info(
                        "[LIVING_UI:STAGING] package.json changed — "
                        "clearing staging node_modules for a fresh install"
                    )
                    self._guarded_rmtree(nm)

        for rel in _SYNC_FILES:
            s = src / rel
            if s.exists():
                shutil.copy2(s, staging_dir / rel)
        for rel in _SYNC_DIRS:
            s, d = src / rel, staging_dir / rel
            if s.is_dir():
                if d.exists():
                    self._guarded_rmtree(d)
                shutil.copytree(s, d, symlinks=True)

    # ── process bookkeeping ────────────────────────────────────────────────
    def adopt_process(self, instance: StagingInstance, process) -> None:
        instance.process = process
        instance.pid = process.pid
        self._processes[instance.project_id] = process

    # ── destroy / reap ─────────────────────────────────────────────────────
    def destroy(self, project_id: str, record: Optional[Dict[str, Any]]) -> None:
        """Kill the staging process and delete the copy. Idempotent and
        best-effort: a half-dead staging must never block a flip."""
        process = self._processes.pop(project_id, None)
        if process is not None and process.poll() is None:
            self._kill(process=process)
        elif record and record.get("pid"):
            self._kill(pid=int(record["pid"]))

        staging_dir = (
            Path(record["dir"])
            if record and record.get("dir")
            else (self.root / project_id)
        )
        if staging_dir.exists():
            try:
                self._guarded_rmtree(staging_dir)
                logger.info(f"[LIVING_UI:STAGING] destroyed copy of {project_id}")
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI:STAGING] failed to delete {staging_dir}: {e}"
                )

    def reap_all(self, records: Dict[str, Dict[str, Any]]) -> int:
        """Startup reaper: no staging copy is legitimately alive when
        CraftBot boots (their missions died with the process), so kill every
        recorded pid and delete everything under the staging root — including
        dirs with no surviving record. Deliberate, unlike the blind orphan
        rmtree in cleanup_on_startup (which skips _staging entirely)."""
        reaped = 0
        for project_id, record in records.items():
            self.destroy(project_id, record)
            reaped += 1
        if self.root.exists():
            for leftover in self.root.iterdir():
                try:
                    self._guarded_rmtree(leftover)
                    reaped += 1
                    logger.info(f"[LIVING_UI:STAGING] reaped leftover {leftover.name}")
                except Exception as e:
                    logger.warning(
                        f"[LIVING_UI:STAGING] failed to reap {leftover}: {e}"
                    )
        return reaped

    # ── internals ──────────────────────────────────────────────────────────
    def _guarded_rmtree(self, target: Path) -> None:
        """Only ever delete inside living_ui/_staging/ — the same
        strict-ancestor discipline delete_project adopted after rmtree wiped
        the working tree twice (2026-07-25/26)."""
        resolved = Path(target).resolve()
        staging_root = (self.living_ui_dir / "_staging").resolve()
        if staging_root not in resolved.parents:
            raise ValueError(f"refusing to delete {resolved} — outside {staging_root}")
        shutil.rmtree(resolved)

    def _free_port(self) -> int:
        for port in range(STAGING_PORT_RANGE[0], STAGING_PORT_RANGE[1] + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
        raise RuntimeError("No free port in the staging range 3900-3999")

    def _rewrite_manifest_port(self, staging_dir: Path, port: int) -> None:
        """`lui ops/run/data` derive their base URL from manifest.port — a
        stale port would make CLI calls from the staging dir hit the LIVE
        app. Same rewrite (including the inlined pipeline string) the
        ZIP-import path does."""
        manifest_path = staging_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_port = manifest.get("port")
        manifest["port"] = port
        if isinstance(manifest.get("pipeline"), dict) and old_port:
            manifest["pipeline"] = json.loads(
                json.dumps(manifest["pipeline"]).replace(str(old_port), str(port))
            )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def _kill(self, process=None, pid: Optional[int] = None) -> None:
        try:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
            elif pid:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except OSError:
                    return  # already gone
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"[LIVING_UI:STAGING] kill failed: {e}")
