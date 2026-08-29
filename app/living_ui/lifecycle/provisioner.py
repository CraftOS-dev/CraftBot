"""DevProvisioner — creates, refreshes, destroys and reaps DEV environments.

A dev environment is a full code copy of the project under
living_ui/_staging/project/<id>/ with its identity rewritten for a hidden
port. Unlike the staging supervisor it replaces, it NEVER clones the live
database: the copy boots with no pb_data at all, PocketBase creates it and
replays the migration chain — so every open_dev is also an implicit
migrations-from-empty test, and no real user data ever enters an
environment the agent or verifier writes to.

Composition mirrors LivingUIRunner: the lifecycle constructs and drives
this class; it never reaches back into the manager or the registry. The
authoritative "a dev copy exists" record lives in the factory host sidecar
(.factory/host.json, key "staging" — historical name, kept so records and
reapers from older versions stay compatible).
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.living_ui.lifecycle.environment import DevInstance

# Outside the manager's 3100-3199 pool on purpose: _load_projects rebuilds
# port bookkeeping from registered projects only, and cleanup_on_startup's
# orphan killer scans that range — dev envs own their ports and their reaping.
DEV_PORT_RANGE = (3900, 3999)

# Same guard the wizard uses for its ids: nothing outside this pattern ever
# becomes part of an rmtree'd path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")

# What a dev copy takes from the real project. pb_data is deliberately
# ABSENT (fresh DB from migration replay at boot); pb_public too — the
# gate's build step recreates it inside the copy. triggers.json MUST
# travel: without it the copy's trigger guard declares nothing, every ⚡
# fire 400s, the walker fails an unfixable "defect", and the arc sticks
# (observed live 2026-08-06, kanban board).
_COPY_FILES = ("manifest.json", "operations.json", "triggers.json", "LIVING_UI.md")
_COPY_CREDS = (".superuser", ".agent-token")
_COPY_DIRS = ("frontend", "pb/pb_hooks", "pb/pb_migrations", ".lui", "reference")

# What sync_code refreshes on each fix-mission iteration: the agent-owned
# paths (ownership rule, agent-guide §1) — never manifest.json (the copy's
# port rewrite must survive).
_SYNC_FILES = ("operations.json", "triggers.json", "LIVING_UI.md")
_SYNC_DIRS = ("frontend/src", "pb/pb_hooks", "pb/pb_migrations", "reference")
_SYNC_PKG = ("frontend/package.json", "frontend/package-lock.json")


class DevProvisioner:
    """Creates, refreshes, destroys and reaps dev environments. Knows nothing
    about the manager's registry, sessions or broadcasting — the lifecycle
    composes this class; it never reaches back."""

    def __init__(self, living_ui_dir: Path, runner) -> None:
        self.living_ui_dir = Path(living_ui_dir)
        self.root = self.living_ui_dir / "_staging" / "project"
        self.runner = runner
        # Live process handles, keyed by project id. Best-effort only —
        # after a CraftBot restart the pid in the sidecar record is all
        # that's left, and destroy/reap fall back to it.
        self._processes: Dict[str, subprocess.Popen] = {}

    # ── create / refresh ───────────────────────────────────────────────────
    async def create_copy(self, project) -> DevInstance:
        """Build a fresh dev copy of `project` (code only — no database) and
        rewrite its identity for a hidden port. Does NOT boot it — the
        lifecycle runs the shared launch pipeline against the returned dir.
        Raises on failure; a partial copy is removed."""
        if not _ID_RE.match(project.id or ""):
            raise ValueError(f"unsafe project id for dev copy: {project.id!r}")
        src = Path(project.path)
        if not (src / "manifest.json").exists():
            raise FileNotFoundError(f"not a Living UI project: {src}")

        dev_dir = self.root / project.id
        if dev_dir.exists():
            self._guarded_rmtree(dev_dir)
        dev_dir.mkdir(parents=True)

        try:
            for rel in _COPY_FILES + _COPY_CREDS:
                f = src / rel
                if f.exists():
                    shutil.copy2(f, dev_dir / rel)
            for rel in _COPY_DIRS:
                d = src / rel
                if d.is_dir():
                    # node_modules rides along inside frontend/ — without it
                    # the gate cold-installs for up to 600 s per dev boot.
                    shutil.copytree(d, dev_dir / rel, symlinks=True)
            (dev_dir / "logs").mkdir(exist_ok=True)

            port = self._free_port()
            self._rewrite_manifest(dev_dir, port)

            # The manifest rewrite invalidated the system-hash canon;
            # kit-sync re-vendors the kit and re-records hashes (same
            # recovery the ZIP-import path uses) — without it the gate's
            # ownership step fails with "modified: manifest.json".
            await self.runner.kit_sync(dev_dir)
        except Exception:
            self._guarded_rmtree(dev_dir)
            raise

        instance = DevInstance(
            project_id=project.id,
            dir=dev_dir,
            port=port,
            created_at=time.time(),
        )
        logger.info(
            f"[LIVING_UI:DEV] created dev copy of {project.id} at "
            f"{dev_dir} (port {port})"
        )
        return instance

    def sync_code(self, project, dev_dir: Path) -> None:
        """Refresh the agent-owned paths real → dev (fix-mission iterations
        edit the real files; the dev copy is what gets gated and served).
        Keeps the rewritten manifest."""
        src = Path(project.path)
        dev_dir = Path(dev_dir)
        if not (dev_dir / "manifest.json").exists():
            raise FileNotFoundError(f"dev copy missing at {dev_dir}")

        # A changed package.json means new/changed deps: drop node_modules so
        # the pipeline's install step runs for real instead of being skipped.
        for rel in _SYNC_PKG:
            s, d = src / rel, dev_dir / rel
            if s.exists() and (not d.exists() or s.read_bytes() != d.read_bytes()):
                shutil.copy2(s, d)
                nm = dev_dir / "frontend" / "node_modules"
                if nm.is_dir():
                    logger.info(
                        "[LIVING_UI:DEV] package.json changed — "
                        "clearing dev node_modules for a fresh install"
                    )
                    self._guarded_rmtree(nm)

        for rel in _SYNC_FILES:
            s = src / rel
            if s.exists():
                shutil.copy2(s, dev_dir / rel)
        for rel in _SYNC_DIRS:
            s, d = src / rel, dev_dir / rel
            if s.is_dir():
                if d.exists():
                    self._guarded_rmtree(d)
                shutil.copytree(s, d, symlinks=True)

    def reset_db(self, dev_dir: Path) -> None:
        """Drop the dev copy's database so the next boot recreates it from
        the migration chain. Called on every open_dev reuse: each iteration
        re-proves the chain replays cleanly from empty, and stale test
        records never accumulate into false verifier context."""
        pb_data = Path(dev_dir) / "pb" / "pb_data"
        if pb_data.exists():
            self._guarded_rmtree(pb_data)

    # ── process bookkeeping ────────────────────────────────────────────────
    def adopt_process(self, instance: DevInstance, process) -> None:
        instance.process = process
        instance.pid = process.pid
        self._processes[instance.project_id] = process

    # ── destroy / reap ─────────────────────────────────────────────────────
    def destroy(self, project_id: str, record: Optional[Dict[str, Any]]) -> None:
        """Kill the dev process and delete the copy. Idempotent and
        best-effort: a half-dead dev env must never block a promote."""
        process = self._processes.pop(project_id, None)
        if process is not None and process.poll() is None:
            self._kill(process=process)
        elif record and record.get("pid"):
            self._kill(pid=int(record["pid"]))

        dev_dir = (
            Path(record["dir"])
            if record and record.get("dir")
            else (self.root / project_id)
        )
        if dev_dir.exists():
            try:
                self._guarded_rmtree(dev_dir)
                logger.info(f"[LIVING_UI:DEV] destroyed dev copy of {project_id}")
            except Exception as e:
                logger.warning(f"[LIVING_UI:DEV] failed to delete {dev_dir}: {e}")

    def reap_all(self, records: Dict[str, Dict[str, Any]]) -> int:
        """Startup reaper: no dev copy is legitimately alive when CraftBot
        boots (their missions died with the process), so kill every recorded
        pid and delete everything under the dev root — including dirs with
        no surviving record. Deliberate, unlike the blind orphan rmtree in
        cleanup_on_startup (which skips _staging entirely)."""
        reaped = 0
        for project_id, record in records.items():
            self.destroy(project_id, record)
            reaped += 1
        if self.root.exists():
            for leftover in self.root.iterdir():
                try:
                    self._guarded_rmtree(leftover)
                    reaped += 1
                    logger.info(f"[LIVING_UI:DEV] reaped leftover {leftover.name}")
                except Exception as e:
                    logger.warning(f"[LIVING_UI:DEV] failed to reap {leftover}: {e}")
        return reaped

    # ── internals ──────────────────────────────────────────────────────────
    def _guarded_rmtree(self, target: Path) -> None:
        """Only ever delete inside living_ui/_staging/ — the same
        strict-ancestor discipline delete_project adopted after rmtree wiped
        the working tree twice (2026-07-25/26). By construction this also
        makes it impossible for the provisioner to delete a LIVE pb_data:
        live projects do not live under the dev root."""
        resolved = Path(target).resolve()
        dev_root = (self.living_ui_dir / "_staging").resolve()
        if dev_root not in resolved.parents:
            raise ValueError(f"refusing to delete {resolved} — outside {dev_root}")
        shutil.rmtree(resolved)

    def _free_port(self) -> int:
        for port in range(DEV_PORT_RANGE[0], DEV_PORT_RANGE[1] + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
        raise RuntimeError("No free port in the dev range 3900-3999")

    def _rewrite_manifest(self, dev_dir: Path, port: int) -> None:
        """Rewrite the copy's identity: its port (`lui ops/run/data` derive
        their base URL from manifest.port — a stale port would make CLI
        calls from the dev dir hit the LIVE app) and `env: "dev"`, which the
        A2APP identity endpoint surfaces so any client can structurally
        confirm which environment a port belongs to."""
        manifest_path = dev_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_port = manifest.get("port")
        manifest["port"] = port
        manifest["env"] = "dev"
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
            logger.warning(f"[LIVING_UI:DEV] kill failed: {e}")
