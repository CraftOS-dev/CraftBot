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

from app.agent_app.lifecycle.environment import ShadowInstance, live_db_exists
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
    ) -> None:
        self.provisioner = ShadowProvisioner(agent_app_dir, runner)
        self.promoter = Promoter(self.provisioner, launch_live)
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

        try:
            instance = self.provisioner.prepare(
                project, host.get_staging_record(project.id)
            )
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

        # Record BEFORE booting: a pipeline failure must still leave the
        # record in place so agent traffic (HTTP action, lui CLI) targets
        # the shadow and the reaper can find its state.
        host.set_staging_record(project.id, instance.to_record())
        self.provisioner.route_cli(Path(project.path), instance.port)

        result = await self._launch_pipeline(
            Path(project.path), instance.port, project.bridge_token, shadow=instance
        )
        if result["status"] != "success":
            return result

        self.provisioner.adopt_process(instance, result.pop("process"))
        host.set_staging_record(project.id, instance.to_record())
        # Old boot dirs (and stale build artifacts) die now that the new
        # boot is up; anything locked waits for the next sweep.
        self.provisioner.sweep(project.id, keep=instance.dir)

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
        # results and the smoke-skip notice (previously dropped here, so
        # dev launches always claimed the smoke walk ran).
        for key in ("op_smoke", "verify_skipped"):
            if key in result:
                envelope[key] = result[key]
        return envelope

    # ── live ───────────────────────────────────────────────────────────────
    async def promote(self, project) -> Dict[str, Any]:
        """Deploy verified code to the live environment (see Promoter)."""
        return await self.promoter.promote(project)

    # ── maintenance ────────────────────────────────────────────────────────
    def reap_dev(self, records: Dict[str, Dict[str, Any]]) -> int:
        """Startup reaper passthrough (see ShadowProvisioner.reap_all)."""
        return self.provisioner.reap_all(records)


__all__ = ["AppLifecycle", "ShadowInstance", "live_db_exists"]
