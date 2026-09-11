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
this class; it owns only processes and filesystem. The authoritative
"a shadow exists" record is the shadow Instance in the InstanceRegistry
(app.agent_app.instances) — the lifecycle mints it and hands the provisioner
just the boot dir and, for teardown, the Instance to kill.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.agent_app.instances import Instance

# Content-addressed artifacts to keep per project (the newest is usually the
# only one that matters; a couple of spares make flip-flopping edits cheap).
_KEEP_BUILDS = 3

# Same guard the wizard uses for its ids: nothing outside this pattern ever
# becomes part of an rmtree'd path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


@dataclass
class ShadowBoot:
    """A freshly minted per-boot directory. The port and the durable record
    are the InstanceRegistry's job; the provisioner owns only the process and
    the filesystem — it never allocates ports or writes the registry."""

    boot_id: str
    dir: Path


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
    def prepare(self, project, previous: Optional[Instance]) -> ShadowBoot:
        """Kill the previous shadow (best-effort) and mint a FRESH boot dir.
        The port and the registry record are minted by the caller from the
        allocator/registry — the provisioner never touches either. Never
        reuses directories, so a kill that fails cannot block the boot."""
        if not _ID_RE.match(project.id or ""):
            raise ValueError(f"unsafe project id for shadow env: {project.id!r}")
        self.kill(project.id, previous)

        boot_id = f"{int(time.time() * 1000):x}"
        boot_dir = self.root / project.id / boot_id
        (boot_dir / "logs").mkdir(parents=True)
        return ShadowBoot(boot_id=boot_id, dir=boot_dir)

    def builds_root(self, project_id: str) -> Path:
        return self.root / project_id / "builds"

    # ── process bookkeeping ────────────────────────────────────────────────
    def adopt_process(self, project_id: str, process) -> None:
        self._processes[project_id] = process

    def kill(self, project_id: str, previous: Optional[Instance]) -> None:
        """Stop the shadow process. Best-effort: a survivor cannot collide
        with the next boot (fresh dirs, fresh port) — it only delays the
        sweep of its own directory."""
        process = self._processes.pop(project_id, None)
        if process is not None and process.poll() is None:
            self._kill(process=process)
        elif previous is not None and previous.pid:
            self._kill(pid=int(previous.pid))

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
    def destroy(self, project_id: str, instance: Optional[Instance]) -> None:
        """Kill the shadow process and sweep its state. Idempotent and
        best-effort: a half-dead shadow must never block a promote."""
        self.kill(project_id, instance)
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

    def reap_dirs(self) -> int:
        """Startup dir sweep: delete every shadow boot dir/build cache and the
        retired dev-copy root (`_staging/project`). Process kills are NOT done
        here — the manager kills leftovers by the ports it OWNS (both ranges),
        which is verified against its own records instead of a stored pid that
        may have been reused. `_staging/wizard` is the wizard's attachment
        staging and is never ours to touch."""
        reaped = 0
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

    def _kill(self, process=None, pid: Optional[int] = None) -> None:
        target_pid = pid if pid else (process.pid if process is not None else None)
        try:
            if os.name == "nt" and target_pid:
                # PocketBase (and any node child) is a tree; a bare terminate
                # strands grandchildren that keep the port bound.
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(target_pid)],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
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
