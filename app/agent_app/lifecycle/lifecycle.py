"""AppLifecycle — the facade the actions layer and manager depend on.

Two operations, one flow for first builds and modifies:

    open_dev(project)  boot the SHADOW environment: the project's OWN code
                       tree on a hidden port with a FRESH database and a
                       content-addressed build artifact. Nothing is copied;
                       the tree's hooks/migrations/source ARE the candidate.
                       The live app (if any) keeps serving the promoted
                       build untouched.
    promote(project)   after a clean walk_verify: rebuild + boot the live
                       environment and tear the shadow down.

Composed, never inherited: the provisioner owns shadow mechanics, the
promoter owns the live boot, and the launch pipeline is injected from the
manager (the same gate/boot pipeline both environments share).
"""

import secrets
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.agent_app.lifecycle.environment import live_db_exists
from app.agent_app.lifecycle.promoter import Promoter
from app.agent_app.lifecycle.provisioner import ShadowProvisioner

LaunchPipeline = Callable[..., Awaitable[Dict[str, Any]]]
LaunchLive = Callable[[str], Awaitable[Dict[str, Any]]]


class AppLifecycle:
    def __init__(
        self,
        agent_app_dir: Path,
        runner,
        launch_pipeline: LaunchPipeline,
        launch_live: LaunchLive,
        registry,
    ) -> None:
        self.provisioner = ShadowProvisioner(agent_app_dir, runner)
        self.registry = registry
        self.promoter = Promoter(self.provisioner, launch_live, registry)
        self._launch_pipeline = launch_pipeline

    # ── shadow ─────────────────────────────────────────────────────────────
    async def open_dev(self, project) -> Dict[str, Any]:
        """Gate + boot the SHADOW environment for `project`. The live app is
        not rebuilt, restarted or written to. Every call is a FRESH boot:
        new state directory, new hidden port, database recreated from the
        migration chain — each iteration re-proves the chain and starts
        from the app's true post-migration state. The previous shadow is
        killed best-effort; a survivor cannot collide (fresh dirs + port)
        and is swept later.

        Same result envelope as the launch pipeline, plus url/port of the
        shadow instance and dev=True on success.
        """
        from app.factory.host_craftbot import get_factory_host

        if getattr(project, "project_type", "native") == "external":
            # Shadow envs need data/artifact redirection; an external app
            # declares no such contract. Changes to externals run live
            # (EXTERNAL-APPS-PLAN v1) — callers route them there.
            return {
                "status": "error",
                "step": "dev",
                "errors": [
                    "External apps have no shadow environment — relaunch live "
                    "via agent_app_notify_ready (changes apply directly)."
                ],
            }

        host = get_factory_host()

        # Supervision arms AT INTENT, before the first gate attempt, so work
        # that never gets past the gate is still supervised. Kind is
        # structural: an app that ever DELIVERED (promoted, or arrived
        # finished) is being modified; one that never delivered is (still)
        # being built — a scaffold's bootstrap pb_data must not read as a
        # live deployment. Re-entry into an open arc is a no-op that clears
        # a pause.
        try:
            if host.delivered_at(project.id) is not None:
                host.begin_modify(project.id)
            else:
                from app.factory.engine import ARC_BUILD

                host.open_arc(project.id, ARC_BUILD)
        except Exception as e:
            logger.warning(f"[AGENT_APP:SHADOW] arc arm failed: {e}")

        previous = self.registry.shadow(project.id)
        try:
            boot = self.provisioner.prepare(project, previous)
        except Exception as e:
            return {
                "status": "error",
                "step": "dev",
                "errors": [f"Could not prepare the shadow environment: {e}"],
            }

        # Reuse (never overwrite) the project's bridge token: a running live
        # app carries it in its env, and validate_bridge_token checks the
        # current in-memory value — re-minting would cut the live app off
        # from the bridge mid-modify.
        if not project.bridge_token:
            project.bridge_token = secrets.token_urlsafe(32)

        # Register the shadow instance BEFORE booting (reserves its port and
        # evicts any prior shadow): a pipeline failure must still leave the
        # instance so agent traffic (HTTP action, lui CLI) targets the shadow
        # and startup reconciliation can find and reclaim its port.
        instance = self.registry.create_shadow(
            project.id,
            token=project.bridge_token,
            boot_id=boot.boot_id,
            dir=str(boot.dir),
        )
        self.provisioner.route_cli(Path(project.path), instance.port)

        result = await self._launch_pipeline(
            Path(project.path), instance.port, project.bridge_token, shadow=instance
        )
        if result["status"] != "success":
            return result

        process = result.pop("process")
        self.provisioner.adopt_process(project.id, process)
        # The pipeline set instance.public_dir on the same object the registry
        # holds; adopt_pid persists both the pid and that artifact path.
        self.registry.adopt_pid(instance.instance_id, process.pid)
        # Old boot dirs (and stale build artifacts) die now that the new
        # boot is up; anything locked waits for the next sweep.
        self.provisioner.sweep(project.id, keep=Path(instance.dir))

        logger.info(f"[AGENT_APP:SHADOW] {project.id} shadow up at {instance.url}")
        envelope = {
            "status": "success",
            "url": instance.url,
            "backend_url": instance.url,
            "port": instance.port,
            "dir": str(instance.dir),
            "dev": True,
        }
        # Pipeline evidence travels with the launch: the changed-op smoke
        # results (previously dropped here, so dev launches lost them).
        if "op_smoke" in result:
            envelope["op_smoke"] = result["op_smoke"]
        return envelope

    # ── live ───────────────────────────────────────────────────────────────
    async def promote(self, project) -> Dict[str, Any]:
        """Deploy verified code to the live environment (see Promoter)."""
        return await self.promoter.promote(project)

    # ── maintenance ────────────────────────────────────────────────────────
    def reap_dirs(self) -> int:
        """Startup dir sweep passthrough (see ShadowProvisioner.reap_dirs).
        Process kills are the manager's owned-port job, not this sweep."""
        return self.provisioner.reap_dirs()


__all__ = ["AppLifecycle", "live_db_exists"]
