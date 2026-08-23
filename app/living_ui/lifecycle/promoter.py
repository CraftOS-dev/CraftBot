"""Promoter — the ONLY code path that acts on a LIVE environment.

promote() deploys a verified change: it boots the real project with the new
code (PocketBase applies new migration files to the real pb_data at boot —
or creates pb_data fresh from the whole chain when this is the app's first
delivery), health-checks it, then destroys the dev environment and every
test record in it. Nothing here ever writes, restores or deletes a live
pb_data — the retired baseline-restore path (finalize_first_delivery) is
exactly the machinery this class replaces.

before_live_boot hooks run right before the live boot: the reserved slot
for the future pre-promote backup (deferred issue #1 in the plan). A hook
that raises ABORTS the promote — a data-safety hook that silently failed
would be worse than no deploy; the dev env is kept for the retry.
"""

from typing import Any, Awaitable, Callable, Dict, List

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.living_ui.lifecycle.environment import has_live_env
from app.living_ui.lifecycle.provisioner import DevProvisioner

LaunchLive = Callable[[str], Awaitable[Dict[str, Any]]]
BeforeLiveBoot = Callable[[Any], None]


class Promoter:
    def __init__(self, provisioner: DevProvisioner, launch_live: LaunchLive) -> None:
        self._provisioner = provisioner
        self._launch_live = launch_live
        self._before_live_boot: List[BeforeLiveBoot] = []

    def add_before_live_boot_hook(self, hook: BeforeLiveBoot) -> None:
        """Register a hook run with the project right before the live boot
        (e.g. a pb_data backup). A raising hook aborts the promote."""
        self._before_live_boot.append(hook)

    async def promote(self, project) -> Dict[str, Any]:
        """Deploy the verified code to the live environment.

        Returns the _launch_native result envelope plus `first` (True when
        this boot created the app's live database — its first delivery).
        On failure the dev environment and its record are KEPT: the live
        app is the casualty being repaired, and the next fix iteration
        needs the copy.
        """
        from app.factory.host_craftbot import get_factory_host

        host = get_factory_host()
        is_external = getattr(project, "project_type", "native") == "external"

        # First-vs-update is structural, never a stored flag: does a live
        # environment exist before this boot? (For external apps — no pb/
        # shape — that means a promote succeeded before.)
        first = not has_live_env(project, host)

        for hook in self._before_live_boot:
            try:
                hook(project)
            except Exception as e:
                logger.error(f"[LIVING_UI:PROMOTE] before_live_boot hook failed: {e}")
                return {
                    "status": "error",
                    "step": "before_live_boot",
                    "errors": [f"pre-promote hook failed: {e}"],
                }

        if is_external:
            # External apps run their new code live already (they have no
            # dev copy — notify_ready relaunched them in place); promoting
            # is pure bookkeeping.
            result: Dict[str, Any] = {
                "status": "success",
                "url": project.url or f"http://127.0.0.1:{project.port}",
                "port": project.port,
            }
        else:
            result = await self._launch_live(project.id)
            if result.get("status") != "success":
                return result
            try:
                self._provisioner.destroy(
                    project.id, host.get_staging_record(project.id)
                )
            finally:
                host.clear_staging_record(project.id)

        result["first"] = first
        host.stamp_delivered(project.id)
        # Trigger consent (spec TRIGGERS-PLAN): a supervised build or modify
        # that delivered is first-party work the user asked for in chat —
        # approve its declared triggers. This is also how apps built BEFORE
        # the consent feature get approved (observed live 2026-08-06: a
        # kanban board gained a user-requested trigger via modify and every
        # fire was then consent-blocked, silently).
        try:
            host.set_triggers_approved(project.id)
        except Exception as e:
            logger.warning(f"[LIVING_UI:PROMOTE] trigger approval failed: {e}")

        # A tab still showing the pre-promote app must refetch (realtime
        # keeps old rows painted through a server restart).
        try:
            from app.living_ui.broadcast import dispatch_living_ui_data_changed

            dispatch_living_ui_data_changed(project.id)
        except Exception:
            pass

        logger.info(
            f"[LIVING_UI:PROMOTE] {project.id} promoted "
            f"({'first delivery' if first else 'update'})"
        )
        return result
