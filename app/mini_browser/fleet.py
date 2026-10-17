"""BrowserFleet: one browser per agent session.

Every session (the main session, each chat, each Agent App session) has a
:class:`~app.mini_browser.core.BrowserCore` of its own, with a persistent
Chromium profile of its own (cookies, signed-in sites and storage are never
shared between sessions). The fleet lives on the Mini Browser host loop (see
``host.py``) and:

- creates a session's browser on first use, without starting it: Chromium
  starts when the user opens the chat's browser panel or the session's agent
  first needs it;
- refuses browsers for sessions that no longer exist (a sub-agent still
  running after its chat was deleted never recreates its browser);
- keeps at most ``settings.max_running_browsers`` running at once: starting
  one more closes the browser idle the longest (nobody watching it, no agent
  operation, no download, its session's run over), and is refused with
  MINI_BROWSER_TOO_MANY_BROWSERS when every running browser is in use;
- deletes a session's profile when the session is deleted, and, once per
  process, the profiles of sessions that no longer exist (left behind by a
  crash between a deletion and its cleanup);
- applies settings, network rules and the ad-block switch to every browser;
- shares one tab-id counter between every browser, so a tab id names one tab
  in the whole UI.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

from app.logger import logger
from app.mini_browser import config
from app.mini_browser.core import BrowserCore, delete_profile
from app.mini_browser.errors import MiniBrowserError

# How long after the fleet starts the orphaned-profile sweep runs: the agent
# runtime has restored its sessions by then.
SWEEP_DELAY_S = 30.0
# Room-making rounds before a launch gives up (each closes one idle browser).
_MAX_EVICTIONS = 12

CoreFactory = Callable[[str, "BrowserFleet"], BrowserCore]


class BrowserFleet:
    """Every session's browser (host loop only)."""

    def __init__(
        self,
        settings: Optional[config.MiniBrowserSettings] = None,
        ops_registry: Optional[Mapping[str, Any]] = None,
        *,
        launch_args: Tuple[str, ...] = (),
        core_factory: Optional[CoreFactory] = None,
    ) -> None:
        """``settings`` / ``ops_registry`` / ``launch_args`` are handed to every
        browser (see :class:`BrowserCore`); ``core_factory(key, fleet)`` builds
        a session's browser instead (tests)."""
        self._settings = settings
        self._ops_registry = ops_registry
        self._launch_args = tuple(launch_args)
        self._core_factory = core_factory
        self.cores: Dict[str, BrowserCore] = {}
        self.tab_ids = itertools.count(1)
        # Sessions whose browser is being removed (deleted sessions).
        self._removals: Dict[str, asyncio.Task] = {}
        self._tasks: Set[asyncio.Task] = set()

    # ── browsers ─────────────────────────────────────────────────────────────

    def core(self, key: Any) -> BrowserCore:
        """Session ``key``'s browser, created (not started) on first use.

        Raises MINI_BROWSER_SESSION_GONE for a session that no longer exists
        or is being removed, MINI_BROWSER_INVALID_INPUT without a session.
        """
        if not isinstance(key, str) or not key:
            raise MiniBrowserError("MINI_BROWSER_INVALID_INPUT", detail="No session.")
        core = self.cores.get(key)
        if core is not None and not core.retired:
            return core
        if key in self._removals or config.session_exists(key) is False:
            raise MiniBrowserError("MINI_BROWSER_SESSION_GONE")
        core = self._new_core(key)
        self.cores[key] = core
        return core

    def existing(self, key: Any) -> Optional[BrowserCore]:
        """Session ``key``'s browser if it was ever used, else None (never creates)."""
        core = self.cores.get(key) if isinstance(key, str) else None
        return core if core is not None and not core.retired else None

    def _new_core(self, key: str) -> BrowserCore:
        if self._core_factory is not None:
            return self._core_factory(key, self)
        return BrowserCore(
            self._settings,
            self._ops_registry,
            key=key,
            fleet=self,
            tab_ids=self.tab_ids,
            launch_args=self._launch_args,
        )

    def activity(self) -> List[Dict[str, Any]]:
        """Every session browser's ``mini_browser_activity`` entry."""
        return [
            core.activity() for core in list(self.cores.values()) if not core.retired
        ]

    # ── the running limit ────────────────────────────────────────────────────

    async def make_room(self, core: BrowserCore) -> None:
        """Called by ``core`` right before it launches Chromium.

        At most ``max_running_browsers`` run at once: while there is no room,
        the browser idle the longest is closed (its agents are told on their
        next action that it was closed); when every running browser is
        in use, MINI_BROWSER_TOO_MANY_BROWSERS. ``core`` is marked starting
        the moment there is room, with no await between the count and the
        mark, so concurrent launches can never overshoot the limit.
        """
        for _round in range(_MAX_EVICTIONS):
            limit = max(1, int(core.settings.max_running_browsers))
            running = [
                other
                for other in list(self.cores.values())
                if other is not core and other.is_running()
            ]
            if len(running) < limit:
                core.mark_starting()
                return
            idle = [other for other in running if other.is_idle()]
            if not idle:
                raise MiniBrowserError(
                    "MINI_BROWSER_TOO_MANY_BROWSERS", count=len(running), limit=limit
                )
            victim = min(idle, key=lambda other: other.last_activity)
            logger.info(
                f"[MiniBrowser] Closing the idle browser of {victim.key} to start "
                f"the browser of {core.key} ({limit} run at once)"
            )
            await victim.close()
        raise MiniBrowserError(
            "MINI_BROWSER_TOO_MANY_BROWSERS",
            count=sum(1 for other in self.cores.values() if other.is_running()),
            limit=max(1, int(core.settings.max_running_browsers)),
        )

    # ── deleted sessions ─────────────────────────────────────────────────────

    async def remove(self, key: str) -> bool:
        """Session ``key`` was deleted: close its browser for good and delete
        its profile. Idempotent (concurrent calls share one removal); returns
        whether the profile is gone."""
        if not isinstance(key, str) or not key:
            return False
        task = self._removals.get(key)
        if task is None or task.done():
            task = self._removals[key] = self._spawn(self._remove(key))
        await asyncio.wait({task})
        return bool(not task.cancelled() and task.exception() is None and task.result())

    async def _remove(self, key: str) -> bool:
        core = self.cores.get(key)
        try:
            if core is not None:
                removed = await core.remove_profile()
                core.publish_activity(force=True)  # stopped, for good
            else:
                removed = await asyncio.to_thread(
                    delete_profile, config.profile_dir(key)
                )
            return removed
        finally:
            if self.cores.get(key) is core:
                self.cores.pop(key, None)
            self._removals.pop(key, None)

    def start_background(self) -> None:
        """Start the fleet's housekeeping (the orphaned-profile sweep)."""
        self._spawn(self._sweep_later())

    async def _sweep_later(self) -> None:
        await asyncio.sleep(SWEEP_DELAY_S)
        await self.sweep_orphaned_profiles()

    async def sweep_orphaned_profiles(self) -> List[str]:
        """Delete the profiles of sessions that no longer exist; their names.

        Only when the agent runtime and its session storage both answer: a
        profile is kept whenever its session might still exist (live,
        stored, or with a browser in this fleet), and a profile in use is
        never touched.
        """
        live = config.live_session_ids()
        if live is None:
            return []
        stored = await asyncio.to_thread(config.persisted_session_ids)
        if stored is None:
            return []
        keep: Set[str] = set(live) | set(stored) | set(self.cores) | set(self._removals)
        keep.add(config.MAIN_SESSION_KEY)
        names = frozenset(config.profile_dir_name(key) for key in keep)
        return await asyncio.to_thread(_sweep_profiles, config.profiles_root(), names)

    # ── every browser ────────────────────────────────────────────────────────

    async def close_all(self) -> None:
        """Close every session's browser (app exit). Never raises."""
        cores = list(self.cores.values())
        if not cores:
            return
        results = await asyncio.gather(
            *(core.close() for core in cores), return_exceptions=True
        )
        for core, result in zip(cores, results):
            if isinstance(result, BaseException) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.debug(
                    f"[MiniBrowser] Close of {core.key} failed: {type(result).__name__}"
                )

    async def reload_settings_now(self) -> None:
        """settings.json changed: every browser re-reads the ``mini_browser``
        section (live settings apply now, launch settings at the next start)."""
        await asyncio.gather(
            *(core.reload_settings_now() for core in list(self.cores.values()))
        )

    async def refresh_network_rules(self) -> None:
        """The UI origins changed: every running browser re-applies its blocking."""
        await asyncio.gather(
            *(core.refresh_network_rules() for core in list(self.cores.values()))
        )

    async def set_adblock(self, enabled: bool) -> None:
        """Turn ad blocking on/off in every browser and remember it (saved once)."""
        enabled = bool(enabled)
        try:
            await asyncio.to_thread(config.save_setting, "adblock", enabled)
        except Exception as exc:
            logger.warning(
                f"[MiniBrowser] Could not save the ad-block setting: {type(exc).__name__}"
            )
        await asyncio.gather(
            *(core.apply_adblock(enabled) for core in list(self.cores.values()))
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _spawn(self, coro: Any) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(
                f"[MiniBrowser] Browser housekeeping failed: {type(exc).__name__}"
            )


def _sweep_profiles(root: Path, keep: FrozenSet[str]) -> List[str]:
    """Delete every profile folder in ``root`` not named in ``keep``. Blocking I/O."""
    removed: List[str] = []
    try:
        entries = list(Path(root).iterdir())
    except FileNotFoundError:
        return removed
    except OSError as exc:
        logger.debug(f"[MiniBrowser] Profiles not listed: {type(exc).__name__}")
        return removed
    for entry in entries:
        try:
            if not entry.is_dir() or entry.name in keep:
                continue
        except OSError:
            continue
        if delete_profile(entry):
            removed.append(entry.name)
    if removed:
        logger.info(
            f"[MiniBrowser] Deleted {len(removed)} browser profile(s) of deleted sessions"
        )
    return removed
