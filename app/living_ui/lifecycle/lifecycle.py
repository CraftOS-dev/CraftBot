"""AppLifecycle — the facade the actions layer and manager depend on.

Two operations, one flow for first builds and modifies:

    open_dev(project)  boot the DEV environment: the project's current code
                       on a hidden port with a FRESH schema-only database.
                       The live app (if any) keeps serving the old code.
    promote(project)   after a clean walk_verify: deploy the code to the
                       live environment and destroy the dev copy.

Composed, never inherited: the provisioner owns dev-env mechanics, the
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

from app.living_ui.lifecycle.environment import DevInstance, live_db_exists
from app.living_ui.lifecycle.promoter import Promoter
from app.living_ui.lifecycle.provisioner import DevProvisioner

LaunchPipeline = Callable[[Path, int, str], Awaitable[Dict[str, Any]]]
LaunchLive = Callable[[str], Awaitable[Dict[str, Any]]]


class AppLifecycle:
    def __init__(
        self,
        living_ui_dir: Path,
        runner,
        launch_pipeline: LaunchPipeline,
        launch_live: LaunchLive,
    ) -> None:
        self.provisioner = DevProvisioner(living_ui_dir, runner)
        self.promoter = Promoter(self.provisioner, launch_live)
        self._launch_pipeline = launch_pipeline

    # ── dev ────────────────────────────────────────────────────────────────
    async def open_dev(self, project) -> Dict[str, Any]:
        """Gate + boot the dev environment for `project` (creating or
        refreshing the copy first). The real app is not rebuilt, restarted
        or written to. The dev DB is reset on EVERY call: it boots empty and
        the migration chain replays, so each iteration re-proves the chain
        and starts from the app's true post-migration state.

        Same result envelope as the launch pipeline, plus url/port of the
        dev instance and dev=True on success.
        """
        from app.factory.host_craftbot import get_factory_host

        if getattr(project, "project_type", "native") == "external":
            # Dev envs are pb/-shaped; an external app has no gate or
            # migration chain to replay. Changes to externals run live
            # (EXTERNAL-APPS-PLAN v1) — callers route them there.
            return {
                "status": "error",
                "step": "dev",
                "errors": [
                    "External apps have no dev environment — relaunch live "
                    "via living_ui_notify_ready (changes apply directly)."
                ],
            }

        host = get_factory_host()
        record = host.get_staging_record(project.id)
        try:
            if (
                record
                and Path(record.get("dir", "")).joinpath("manifest.json").exists()
            ):
                instance = DevInstance.from_record(project.id, record)
                self.provisioner.sync_code(project, instance.dir)
                self.provisioner.reset_db(instance.dir)
            else:
                instance = await self.provisioner.create_copy(project)
        except Exception as e:
            # Never fall back to gating/serving the real project dir — the
            # gate's vite build would blank a live app's served UI in place.
            return {
                "status": "error",
                "step": "dev",
                "errors": [f"Could not prepare the dev environment: {e}"],
            }

        # Reuse (never overwrite) the project's bridge token: a running live
        # app carries it in its env, and validate_bridge_token checks the
        # current in-memory value — re-minting would cut the live app off
        # from the bridge mid-modify.
        if not project.bridge_token:
            project.bridge_token = secrets.token_urlsafe(32)

        # Record BEFORE booting: a pipeline failure must still leave the
        # record in place so living_ui_http redirects there and the next
        # open_dev reuses the copy instead of re-cloning.
        host.set_staging_record(project.id, instance.to_record())

        result = await self._launch_pipeline(
            instance.dir, instance.port, project.bridge_token
        )
        if result["status"] != "success":
            return result

        self.provisioner.adopt_process(instance, result.pop("process"))
        host.set_staging_record(project.id, instance.to_record())

        # A change to an app WITH a live database is a modify — re-arm the
        # factory machine so it gets the same supervision as a build: fix
        # missions on defects, caps, machine announcements. Deterministic
        # here, never agent-driven; no-ops when an arc is already in flight.
        # An app with no live DB yet is build-era: its machine already owns
        # the arc (or is virgin, which stays a first delivery).
        if live_db_exists(project.path):
            try:
                host.begin_modify(project.id)
            except Exception as e:
                logger.warning(f"[LIVING_UI:DEV] begin_modify failed: {e}")

        logger.info(f"[LIVING_UI:DEV] {project.id} dev env up at {instance.url}")
        return {
            "status": "success",
            "url": instance.url,
            "backend_url": instance.url,
            "port": instance.port,
            "dir": str(instance.dir),
            "dev": True,
        }

    # ── live ───────────────────────────────────────────────────────────────
    async def promote(self, project) -> Dict[str, Any]:
        """Deploy verified code to the live environment (see Promoter)."""
        return await self.promoter.promote(project)

    # ── maintenance ────────────────────────────────────────────────────────
    def reap_dev(self, records: Dict[str, Dict[str, Any]]) -> int:
        """Startup reaper passthrough (see DevProvisioner.reap_all)."""
        return self.provisioner.reap_all(records)
