"""ShadowProvisioner — creates, destroys and reaps SHADOW environments.

A shadow environment is NOT a copy. It is the project's own code tree booted
a second time with three redirected inputs: a hidden port, a fresh per-boot
database directory, and a content-addressed build artifact. The tree's
hooks, migrations, frontend source and node_modules are used in place — they
ARE the candidate code being verified.

The provisioner's discipline, learned from the copy era it replaces:

- NEVER delete in place on the hot path. Every boot gets a fresh
  `_shadow/<project>/<boot-id>/` directory and a fresh port, so a zombie
  process from a previous boot (Windows holds files open; kills can fail)
  can neither lock the new boot's files nor squat its port. Old boot dirs
  are swept lazily — a locked one just waits for the next sweep.
- Builds are content-addressed under `_shadow/<project>/builds/<fp>/`
  (written by the gate), so unchanged inputs reuse the artifact and the
  LIVE build in pb/pb_public is never touched outside a promote.

Composition mirrors AgentAppRunner: the lifecycle constructs and drives
this class; it never reaches back into the manager or the registry. The
authoritative "a shadow exists" record lives in the factory host sidecar
(.factory/host.json, key "staging" — historical name, kept because the
redirects and reapers already speak it).
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

from app.agent_app.lifecycle.environment import ShadowInstance

# Outside the manager's 3100-3199 pool on purpose: _load_projects rebuilds
# port bookkeeping from registered projects only, and cleanup_on_startup's
# orphan killer scans that range — shadows own their ports and their reaping.
SHADOW_PORT_RANGE = (3900, 3999)

# Content-addressed artifacts to keep per project (the newest is usually the
# only one that matters; a couple of spares make flip-flopping edits cheap).
_KEEP_BUILDS = 3

# Same guard the wizard uses for its ids: nothing outside this pattern ever
# becomes part of an rmtree'd path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class ShadowProvisioner:
    """Creates, destroys and reaps shadow environments. Knows nothing about
    the manager's registry, sessions or broadcasting — the lifecycle composes
    this class; it never reaches back."""

    def __init__(self, agent_app_dir: Path, runner) -> None:
        self.agent_app_dir = Path(agent_app_dir)
        self.root = self.agent_app_dir / "_shadow"
        self.runner = runner
        # Live process handles, keyed by project id. Best-effort only —
        # after a CraftBot restart the pid in the sidecar record is all
        # that's left, and destroy/reap fall back to it.
        self._processes: Dict[str, subprocess.Popen] = {}

    # ── boot preparation ───────────────────────────────────────────────────
    def prepare(
        self, project, previous: Optional[Dict[str, Any]]
    ) -> ShadowInstance:
        """Kill the previous shadow (best-effort) and mint a FRESH instance:
        new boot dir, new port. Never reuses directories, so a kill that
        fails cannot block the boot."""
        if not _ID_RE.match(project.id or ""):
            raise ValueError(f"unsafe project id for shadow env: {project.id!r}")
        self.kill(project.id, previous)

        boot_id = f"{int(time.time() * 1000):x}"
        boot_dir = self.root / project.id / boot_id
        (boot_dir / "logs").mkdir(parents=True)
        return ShadowInstance(
            project_id=project.id,
            dir=boot_dir,
            port=self._free_port(),
            created_at=time.time(),
        )

    def builds_root(self, project_id: str) -> Path:
        return self.root / project_id / "builds"

    # ── process bookkeeping ────────────────────────────────────────────────
    def adopt_process(self, instance: ShadowInstance, process) -> None:
        instance.process = process
        instance.pid = process.pid
        self._processes[instance.project_id] = process

    def kill(self, project_id: str, record: Optional[Dict[str, Any]]) -> None:
        """Stop the shadow process. Best-effort: a survivor cannot collide
        with the next boot (fresh dirs, fresh port) — it only delays the
        sweep of its own directory."""
        if record and record.get("port"):
            # The shadow on this port is dying — its warm probe page (if
            # any) is now rendering a dead build.
            try:
                from app.agent_app.probe_pool import get_probe_pool

                get_probe_pool().drop(int(record["port"]))
            except Exception:
                pass
        process = self._processes.pop(project_id, None)
        if process is not None and process.poll() is None:
            self._kill(process=process)
        elif record and record.get("pid"):
            self._kill(pid=int(record["pid"]))

    # ── CLI routing (.lui/shadow.json) ─────────────────────────────────────
    # While a shadow is up, ALL agent-facing traffic belongs to it: the lui
    # CLI reads this file to pick its port, mirroring the redirect the host
    # applies to its own HTTP action. Deleted at promote/teardown.
    @staticmethod
    def route_cli(project_path: Path, port: int) -> None:
        try:
            lui = Path(project_path) / ".lui"
            lui.mkdir(parents=True, exist_ok=True)
            (lui / "shadow.json").write_text(
                json.dumps({"port": port}) + "\n", encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[AGENT_APP:SHADOW] could not write CLI route: {e}")

    @staticmethod
    def unroute_cli(project_path: Path) -> None:
        try:
            (Path(project_path) / ".lui" / "shadow.json").unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"[AGENT_APP:SHADOW] could not remove CLI route: {e}")

    # ── destroy / sweep / reap ─────────────────────────────────────────────
    def destroy(self, project_id: str, record: Optional[Dict[str, Any]]) -> None:
        """Kill the shadow process and sweep its state. Idempotent and
        best-effort: a half-dead shadow must never block a promote."""
        self.kill(project_id, record)
        self.sweep(project_id, keep=None)
        logger.info(f"[AGENT_APP:SHADOW] destroyed shadow of {project_id}")

    def sweep(self, project_id: str, keep: Optional[Path]) -> int:
        """Delete boot dirs (except `keep`) and prune old build artifacts.
        Locked entries are skipped without complaint — the next sweep gets
        them. Returns the number of entries removed."""
        project_root = self.root / project_id
        if not project_root.exists():
            return 0
        removed = 0
        builds = self.builds_root(project_id)
        keep_resolved = Path(keep).resolve() if keep is not None else None
        for entry in list(project_root.iterdir()):
            try:
                if entry.resolve() == keep_resolved:
                    continue
                if entry == builds:
                    removed += self._prune_builds(builds)
                    continue
                self._guarded_rmtree(entry)
                removed += 1
            except Exception:
                pass  # locked by a zombie — next sweep
        return removed

    def _prune_builds(self, builds: Path) -> int:
        removed = 0
        try:
            artifacts = sorted(
                (d for d in builds.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return 0
        for stale in artifacts[_KEEP_BUILDS:]:
            try:
                self._guarded_rmtree(stale)
                removed += 1
            except Exception:
                pass
        return removed

    def reap_all(self, records: Dict[str, Dict[str, Any]]) -> int:
        """Startup reaper: no shadow is legitimately alive when CraftBot
        boots (their missions died with the process). Kill every recorded
        pid, sweep the whole shadow root, and sweep the retired dev-copy
        root (`_staging`) left behind by pre-shadow versions."""
        reaped = 0
        for project_id, record in records.items():
            try:
                self.kill(project_id, record)
                reaped += self.sweep(project_id, keep=None)
            except Exception as e:
                logger.warning(f"[AGENT_APP:SHADOW] reap failed for {project_id}: {e}")
        # `_staging/project` was the dev-copy era's root; `_staging/wizard`
        # is the wizard's attachment staging and is NOT ours to touch.
        for root in (self.root, self.agent_app_dir / "_staging" / "project"):
            if not root.exists():
                continue
            for leftover in list(root.iterdir()):
                try:
                    self._guarded_rmtree(leftover)
                    reaped += 1
                    logger.info(f"[AGENT_APP:SHADOW] reaped leftover {leftover.name}")
                except Exception:
                    pass  # locked — next boot
        return reaped

    # ── internals ──────────────────────────────────────────────────────────
    def _guarded_rmtree(self, target: Path) -> None:
        """Only ever delete inside the shadow root or the retired dev-copy
        root — the same strict-ancestor discipline delete_project adopted
        after rmtree wiped the working tree twice (2026-07-25/26). By
        construction the provisioner can never delete a LIVE pb_data: live
        projects do not live under either root."""
        resolved = Path(target).resolve()
        allowed = (
            self.root.resolve(),
            (self.agent_app_dir / "_staging" / "project").resolve(),
        )
        if not any(root == resolved or root in resolved.parents for root in allowed):
            raise ValueError(f"refusing to delete {resolved} — outside {allowed}")
        if resolved in allowed:
            raise ValueError(f"refusing to delete a shadow root itself: {resolved}")
        shutil.rmtree(resolved)

    def _free_port(self) -> int:
        for port in range(SHADOW_PORT_RANGE[0], SHADOW_PORT_RANGE[1] + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
        raise RuntimeError("No free port in the shadow range 3900-3999")

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
            logger.warning(f"[AGENT_APP:SHADOW] kill failed: {e}")
