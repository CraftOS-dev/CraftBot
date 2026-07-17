"""
Living UI Manager

Manages the lifecycle of Living UI projects:
- Project creation from template
- Project launching and stopping
- Port allocation
- State tracking
- Startup auto-launch
- Task creation with trigger firing
"""

import asyncio
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple, TYPE_CHECKING

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from app.living_ui.ownership import OwnershipMixin
from app.living_ui.ports import PortAllocationMixin
from app.living_ui.tunnels import TunnelMixin

if TYPE_CHECKING:
    from app.task.task_manager import TaskManager
    from app.trigger import TriggerQueue


@dataclass
class LivingUIProject:
    """Represents a Living UI project."""

    id: str
    name: str
    description: str
    path: str
    status: str = "created"  # created, creating, ready, running, stopped, error
    port: Optional[int] = None  # Frontend port
    backend_port: Optional[int] = None  # Backend API port
    url: Optional[str] = None  # Frontend URL
    backend_url: Optional[str] = None  # Backend API URL
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    features: List[str] = field(default_factory=list)
    theme: str = "system"
    # Display icon: "lucide:<IconName>" (predefined picker) or
    # "file:<project-relative path>" (uploaded — lives at public/favicon.*
    # so it doubles as the app's browser-tab favicon; served to the host UI
    # via GET /api/living-ui/icon/<id>). None -> the UI's default cube.
    icon: Optional[str] = None
    error: Optional[str] = None
    task_id: Optional[str] = None
    auto_launch: bool = False  # Auto-launch on CraftBot startup
    log_cleanup: bool = True  # Clean logs on restart
    project_type: str = "native"  # 'native' or 'external'
    app_runtime: Optional[str] = (
        None  # 'go', 'node', 'python', 'rust', 'docker', 'static'
    )
    # Per-project display theme chosen in the UI ({"themeId": ..., "customColors": {...}}).
    # Persisted so the choice survives beyond one browser's localStorage.
    ui_theme: Optional[Dict[str, Any]] = None
    bridge_token: str = ""  # Ephemeral token for integration bridge (NOT serialized)
    tunnel_url: Optional[str] = None  # Public tunnel URL (NOT serialized)
    tunnel_process: Optional[subprocess.Popen] = None  # Tunnel process (NOT serialized)
    process: Optional[subprocess.Popen] = None  # Frontend process
    backend_process: Optional[subprocess.Popen] = None  # Backend process
    app_process: Optional[subprocess.Popen] = None  # Single process for external apps
    # Live Construction View dev preview (Vite dev server shown while the
    # project is still being created). dev_port is persisted so startup
    # cleanup can kill an orphaned dev server after a crash; dev_url and
    # dev_process are runtime-only.
    dev_port: Optional[int] = None
    dev_url: Optional[str] = None  # NOT restored on load
    dev_process: Optional[subprocess.Popen] = None  # NOT serialized
    # Set when the launch pipeline last PASSED, cleared on every new pipeline
    # attempt and on code writes (see construction_events). Gates
    # living_ui_notify_ready: no fresh pass, no ready. Runtime-only — a
    # restart requires re-validation by design.
    validation_passed_at: Optional[float] = None  # NOT serialized

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "status": self.status,
            "port": self.port,
            "backendPort": self.backend_port,
            "url": self.url,
            "backendUrl": self.backend_url,
            "createdAt": int(self.created_at * 1000),  # Convert to JS timestamp
            "features": self.features,
            "theme": self.theme,
            "icon": self.icon,
            "error": self.error,
            "autoLaunch": self.auto_launch,
            "logCleanup": self.log_cleanup,
            "projectType": self.project_type,
            "appRuntime": self.app_runtime,
            "tunnelUrl": self.tunnel_url,
            "uiTheme": self.ui_theme,
            "devPort": self.dev_port,
            "devUrl": self.dev_url,
            # Task linkage MUST survive restarts: the ghost guard, the build
            # director, and the budget-reset hook all match task <-> project
            # by this — without it every restored project looked ownerless.
            "taskId": self.task_id,
        }


class LivingUIManager(OwnershipMixin, PortAllocationMixin, TunnelMixin):
    """Manages Living UI project lifecycle.

    Cohesive concerns live in mixins (each is a facet of this one class,
    not a reusable library): OwnershipMixin (ownership.py — the
    ensure_project_owner funnel), PortAllocationMixin (ports.py — port
    pool + orphan eviction), TunnelMixin (tunnels.py — LAN/tunnel
    sharing). This module keeps the registry, launch/validation pipeline,
    process lifecycle, and watchdog.
    """

    def __init__(self, workspace_root: Path, template_path: Path):
        """
        Initialize the Living UI Manager.

        Args:
            workspace_root: Root directory for Living UI projects
            template_path: Path to the Living UI template
        """
        self.workspace_root = Path(workspace_root)
        self.template_path = Path(template_path)
        self.projects: Dict[str, LivingUIProject] = {}
        self._next_port = 3100
        self._port_range = (3100, 3199)
        self._used_ports: set = set()
        # Guards the check-then-add on _used_ports: allocation happens from the
        # watchdog, auto-launch, WS handlers and agent actions, some of which
        # run on worker threads.
        self._ports_lock = threading.Lock()
        self._projects_file = self.workspace_root / "living_ui_projects.json"

        # Task and trigger management (set via bind_task_manager)
        self._task_manager: Optional["TaskManager"] = None
        self._trigger_queue: Optional["TriggerQueue"] = None
        self._trigger_service = None  # Optional[TriggerService] — durable emit path

        # Watchdog state
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_running: bool = False

        # Per-project launch/stop serialization. Concurrent launch_and_verify
        # runs on the same project stomp each other's processes (the second
        # attempt's "kill leftovers" step kills the first attempt's freshly
        # started backend mid-smoke-test). A queued duplicate waits, then
        # collapses into a no-op via the already-running check.
        self._launch_locks: Dict[str, asyncio.Lock] = {}
        # Serializes start_dev_preview per project: the create-time call and
        # a watchdog retry must never run two npm installs concurrently
        # (concurrent npm corrupts node_modules).
        self._dev_preview_locks: Dict[str, asyncio.Lock] = {}
        # No-change validate guard: project_id -> (source signature at last
        # FAILED validation, its error list). See launch_and_verify.
        self._last_validate_attempt: Dict[str, Tuple[str, tuple]] = {}

        # Ensure workspace directory exists
        self.living_ui_dir = self.workspace_root / "living_ui"
        self.living_ui_dir.mkdir(parents=True, exist_ok=True)

        # Load existing projects
        self._load_projects()

    def bind_task_manager(
        self,
        task_manager: "TaskManager",
        trigger_queue: "TriggerQueue",
        trigger_service=None,
    ) -> None:
        """
        Bind the task manager and trigger queue for creating development tasks.

        Args:
            task_manager: TaskManager instance for creating tasks
            trigger_queue: TriggerQueue instance for firing triggers
            trigger_service: Optional TriggerService for durable emits
                ; falls back to direct queue puts when None.
        """
        self._task_manager = task_manager
        self._trigger_queue = trigger_queue
        self._trigger_service = trigger_service
        logger.info("[LIVING_UI] Task manager and trigger queue bound")
        self.reconcile_interrupted_builds()

    def reconcile_interrupted_builds(self) -> None:
        """Mark orphaned mid-creation projects as errored (boot reconcile).

        Runs once the task manager is bound (AFTER boot restore + the ghost
        guard, which cancels all but the newest creation task). Any project
        still in "creating" whose owning task is not alive-and-running was
        interrupted by a restart and will never be finished by anyone —
        flip it to error with an actionable note instead of letting the
        watchdog nurse it forever. Fail-open."""
        try:
            for project in list(self.projects.values()):
                if project.status != "creating":
                    continue
                task = (
                    self._task_manager.tasks.get(project.task_id)
                    if (self._task_manager and project.task_id)
                    else None
                )
                if task is not None and getattr(task, "status", "") == "running":
                    continue  # legitimate resumed build
                logger.info(
                    f"[LIVING_UI] Reconciling interrupted build: {project.id} "
                    f"('{project.name}') — no live creation task"
                )
                self.update_project_status(
                    project.id,
                    "error",
                    "Build was interrupted by a restart and not resumed — "
                    "ask me to rebuild it.",
                )
            # Invariant check (OBSERVABILITY ONLY — never mutate here): every
            # live owner task must carry the development workflow; the
            # ensure_project_owner funnel installs it on every path. If this
            # fires, an ownership path bypassed the funnel — find and fix
            # that path, don't patch the symptom at restore time.
            for project in list(self.projects.values()):
                task = (
                    self._task_manager.tasks.get(project.task_id)
                    if (self._task_manager and project.task_id)
                    else None
                )
                if (
                    task is not None
                    and getattr(task, "status", "") == "running"
                    and getattr(task, "workflow_id", None)
                    not in ("living_ui_development", "living_ui_creation")
                ):
                    logger.warning(
                        f"[LIVING_UI] INVARIANT LEAK: project {project.id} "
                        f"('{project.name}') is owned by WORKFLOW-LESS task "
                        f"{project.task_id} — an ownership path bypassed "
                        "ensure_project_owner"
                    )
        except Exception as e:
            logger.warning(f"[LIVING_UI] reconcile_interrupted_builds failed: {e}")

    # ========================================================================
    # Watchdog - monitors running projects and restarts crashed processes
    # ========================================================================

    WATCHDOG_INTERVAL = 30  # seconds between checks
    WATCHDOG_RETRY_DELAYS = [5, 15, 30]  # seconds to wait between restart attempts

    def start_watchdog(self) -> None:
        """Start the background watchdog that monitors running projects."""
        if self._watchdog_running:
            logger.warning("[LIVING_UI:WATCHDOG] Already running")
            return

        self._watchdog_running = True
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("[LIVING_UI:WATCHDOG] Started")

        # Declared op schedules ("schedule" key in operations.json) fire
        # alongside the watchdog for running projects.
        from .scheduler import ScheduleRunner

        if not hasattr(self, "_schedule_runner") or self._schedule_runner is None:
            self._schedule_runner = ScheduleRunner(self)
        self._schedule_runner.start()

    async def stop_watchdog(self) -> None:
        """Stop the background watchdog."""
        if not self._watchdog_running:
            return

        self._watchdog_running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        runner = getattr(self, "_schedule_runner", None)
        if runner:
            runner.stop()
        logger.info("[LIVING_UI:WATCHDOG] Stopped")

    async def _watchdog_loop(self) -> None:
        """
        Background loop that checks all running projects for dead processes.

        On detecting a crash:
        1. Attempts silent restart (up to 3 retries with increasing delays)
        2. If all retries fail, sets status to 'error' and creates an agent
           task to investigate and fix the issue
        """
        retry_counts: Dict[str, int] = {}  # project_id -> consecutive failures
        dev_retry_counts: Dict[str, int] = {}  # project_id -> preview retries
        dev_preview_tasks: Dict[str, asyncio.Task] = {}  # in-flight retries

        # Initial delay to let everything settle after startup
        await asyncio.sleep(10)

        while self._watchdog_running:
            try:
                await asyncio.sleep(self.WATCHDOG_INTERVAL)

                for project_id, project in list(self.projects.items()):
                    # -- Live Construction preview recovery: a 'creating'
                    # project with no dev_url means the preview died (e.g.
                    # an npm race corrupted node_modules) and the
                    # construction canvas is blank. Keep retrying with
                    # watchdog spacing — start_dev_preview repairs the
                    # install and is idempotent when a server is already up.
                    if project.status == "creating":
                        if project.dev_url is None and self._dev_preview_eligible(
                            project
                        ):
                            task = dev_preview_tasks.get(project_id)
                            if task is None or task.done():
                                attempts = dev_retry_counts.get(project_id, 0)
                                if attempts < self.DEV_PREVIEW_MAX_RETRIES:
                                    dev_retry_counts[project_id] = attempts + 1
                                    logger.info(
                                        f"[LIVING_UI:WATCHDOG] dev preview down for "
                                        f"{project.name} ({project_id}) — retry "
                                        f"{attempts + 1}/{self.DEV_PREVIEW_MAX_RETRIES}"
                                    )
                                    dev_preview_tasks[project_id] = asyncio.create_task(
                                        self.start_dev_preview(project_id)
                                    )
                        else:
                            dev_retry_counts.pop(project_id, None)
                        retry_counts.pop(project_id, None)
                        continue
                    dev_retry_counts.pop(project_id, None)
                    dev_preview_tasks.pop(project_id, None)

                    if project.status != "running":
                        # Clear retry count if project is no longer running
                        retry_counts.pop(project_id, None)
                        continue

                    backend_dead = (
                        project.backend_process is not None
                        and project.backend_process.poll() is not None
                    )
                    frontend_dead = (
                        project.process is not None
                        and project.process.poll() is not None
                    )

                    # Also check via port if process handles are None
                    # (can happen if manager was reloaded but processes survived)
                    if not backend_dead and project.backend_port:
                        if project.backend_process is None and not self._is_port_in_use(
                            project.backend_port
                        ):
                            backend_dead = True
                    if not frontend_dead and project.port:
                        if project.process is None and not self._is_port_in_use(
                            project.port
                        ):
                            frontend_dead = True

                    if not backend_dead and not frontend_dead:
                        # Everything healthy, reset retry counter
                        if project_id in retry_counts:
                            logger.info(
                                f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) recovered"
                            )
                            retry_counts.pop(project_id)
                        continue

                    # Something is dead
                    retries = retry_counts.get(project_id, 0)
                    crash_target = []
                    if backend_dead:
                        crash_target.append("backend")
                    if frontend_dead:
                        crash_target.append("frontend")
                    crash_str = " + ".join(crash_target)

                    if retries >= len(self.WATCHDOG_RETRY_DELAYS):
                        # Exhausted retries — escalate to agent
                        logger.error(
                            f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) "
                            f"{crash_str} crashed, all {retries} restart attempts failed. Escalating to agent."
                        )
                        await self._escalate_crash(project_id, crash_target)
                        retry_counts.pop(project_id, None)
                        continue

                    delay = self.WATCHDOG_RETRY_DELAYS[retries]
                    retry_counts[project_id] = retries + 1
                    logger.warning(
                        f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) "
                        f"{crash_str} crashed. Restart attempt {retries + 1}/{len(self.WATCHDOG_RETRY_DELAYS)} "
                        f"in {delay}s..."
                    )

                    await asyncio.sleep(delay)

                    # Attempt restart
                    restart_ok = True
                    if backend_dead:
                        project.backend_process = None
                        success = await self.launch_backend(project_id)
                        if not success:
                            logger.error(
                                f"[LIVING_UI:WATCHDOG] Backend restart failed for {project_id}"
                            )
                            restart_ok = False

                    if frontend_dead:
                        project.process = None
                        success = await self._relaunch_frontend(project_id)
                        if not success:
                            logger.error(
                                f"[LIVING_UI:WATCHDOG] Frontend restart failed for {project_id}"
                            )
                            restart_ok = False

                    if restart_ok:
                        logger.info(
                            f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) restarted successfully"
                        )
                        retry_counts.pop(project_id, None)
                        self._save_projects()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LIVING_UI:WATCHDOG] Unexpected error: {e}")
                await asyncio.sleep(self.WATCHDOG_INTERVAL)

    async def _relaunch_frontend(self, project_id: str) -> bool:
        """
        Relaunch just the frontend process for a project.

        Lightweight alternative to launch_project — reuses existing port,
        skips npm install, doesn't touch backend.
        """
        project = self.projects.get(project_id)
        if not project:
            return False

        project_path = Path(project.path)
        port = project.port
        if not port:
            return False

        # Kill anything on the port first
        if self._is_port_in_use(port):
            self._kill_process_on_port(port)
            await asyncio.sleep(1)

        try:
            # Open timestamped log file for subprocess output
            frontend_log = self._create_frontend_log(project_path)
            frontend_log_handle = open(frontend_log, "a", encoding="utf-8")
            frontend_log_handle.write(
                f"\n{'=' * 60}\n[{datetime.now().isoformat()}] "
                f"Relaunching frontend on port {port}\n{'=' * 60}\n"
            )
            frontend_log_handle.flush()

            process = subprocess.Popen(
                ["npm", "run", "preview", "--", "--port", str(port)],
                cwd=str(project_path),
                stdout=frontend_log_handle,
                stderr=frontend_log_handle,
                shell=True if os.name == "nt" else False,
            )
            process._craftbot_log_handle = frontend_log_handle

            project.process = process

            server_ready = await self._wait_for_server(port, timeout=15)
            if not server_ready:
                frontend_log_handle.flush()
                try:
                    recent = frontend_log.read_text(encoding="utf-8")[-500:]
                except Exception:
                    recent = ""
                logger.error(
                    f"[LIVING_UI] Frontend relaunch failed for {project_id}. Log tail:\n{recent}"
                )
                if process.poll() is None:
                    self._terminate_process(process)
                project.process = None
                frontend_log_handle.close()
                return False

            project.url = f"http://localhost:{port}"
            logger.info(
                f"[LIVING_UI] Frontend relaunched for {project_id} on port {port}"
            )
            return True

        except Exception as e:
            logger.error(f"[LIVING_UI] Frontend relaunch error for {project_id}: {e}")
            return False

    async def _escalate_crash(self, project_id: str, crash_targets: List[str]) -> None:
        """
        Escalate a crash to the agent by creating a fix task.

        Called after all silent restart attempts have failed.
        Reads crash logs and creates an agent task with full context.
        """
        project = self.projects.get(project_id)
        if not project:
            return

        # Collect crash log tails
        project_path = Path(project.path)
        log_snippets = []

        # Backend log (the pipeline writes PocketBase output here; the
        # legacy FastAPI path is kept for pre-PocketBase projects)
        for label, log_path in (
            ("Backend log", project_path / "logs" / "backend_output.log"),
            (
                "Backend log (legacy)",
                project_path / "backend" / "logs" / "subprocess_output.log",
            ),
        ):
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding="utf-8")
                    log_snippets.append(
                        f"=== {label} (last 1000 chars) ===\n{content[-1000:]}"
                    )
                    break
                except Exception:
                    pass

        # Frontend console capture (PocketBase system hooks persist it here)
        console_log = project_path / "pb_data" / "craftbot_console.jsonl"
        if console_log.exists():
            try:
                content = console_log.read_text(encoding="utf-8")
                log_snippets.append(
                    f"=== Frontend console (last 1000 chars) ===\n{content[-1000:]}"
                )
            except Exception:
                pass

        # Frontend logs (most recent session)
        frontend_logs_dir = project_path / "logs"
        if frontend_logs_dir.exists():
            frontend_logs = sorted(
                frontend_logs_dir.glob("frontend_*.log"), reverse=True
            )
            if frontend_logs:
                try:
                    content = frontend_logs[0].read_text(encoding="utf-8")
                    log_snippets.append(
                        f"=== Frontend log (last 1000 chars) ===\n{content[-1000:]}"
                    )
                except Exception:
                    pass

        crash_str = " and ".join(crash_targets)
        all_logs = "\n\n".join(log_snippets) if log_snippets else "(no logs found)"

        # Update project status
        project.status = "error"
        project.error = f"{crash_str} crashed after {len(self.WATCHDOG_RETRY_DELAYS)} restart attempts"
        project.process = None
        project.backend_process = None
        self._save_projects()

        # Create agent task to investigate and fix
        if not self._task_manager or not self._trigger_queue:
            logger.error(
                "[LIVING_UI:WATCHDOG] Cannot escalate — task manager or trigger queue not bound"
            )
            return

        from app.trigger import Trigger

        task_instruction = f"""Fix a crashed Living UI application.

Project ID: {project.id}
Project Name: {project.name}
Project Path: {project.path}
Crashed components: {crash_str}

The Living UI {crash_str} process(es) crashed and {len(self.WATCHDOG_RETRY_DELAYS)} automatic restart attempts all failed.
This means the code likely has a bug that prevents the server from running.

CRASH LOGS:
{all_logs}

STEPS:
1. Read the crash logs above to identify the root cause
2. Navigate to the project path and fix the code
3. Use living_ui_restart with project_id="{project.id}" to restart the project
4. Verify the project is running by checking that the restart succeeded

Follow the living-ui-creator skill instructions for the project structure.
The backend is PocketBase (collections in {project.path}/config/schema.json,
custom routes in {project.path}/pb_hooks/)
The frontend is a Vite+React app at {project.path}/frontend/"""

        try:
            task_id = self._task_manager.create_task(
                task_name=f"Fix crashed Living UI: {project.name}",
                task_instruction=task_instruction,
                mode="complex",
                action_sets=["file_operations", "code_execution", "living_ui", "core"],
                # Sub-workflow: purpose-built system prompt replaces the
                # general agent's (skills stay on disk as reference material).
                workflow_id="living_ui_development",
            )

            if self._trigger_service is not None:
                from app.triggers import TriggerSource, TriggerSpec

                await self._trigger_service.emit(
                    TriggerSpec(
                        source=TriggerSource.LIVING_UI_CRASH_FIX,
                        description=f"[Living UI] Fix crash: {project.name}",
                        priority=5,  # beat continuation triggers or the fix never starts
                        session_id=task_id,
                        payload={
                            "type": "living_ui_crash_fix",
                            "project_id": project_id,
                        },
                    )
                )
            else:
                trigger = Trigger(
                    fire_at=time.time(),
                    priority=5,  # beat continuation triggers or the fix never starts
                    next_action_description=f"[Living UI] Fix crash: {project.name}",
                    session_id=task_id,
                    payload={
                        "type": "living_ui_crash_fix",
                        "project_id": project_id,
                    },
                )
                await self._trigger_queue.put(trigger)

            # Ownership funnel: the fix task becomes the owner with a fresh
            # round budget (the crash fix is new work on existing code).
            await self.ensure_project_owner(project_id, task_id, reset_state=True)
            logger.info(
                f"[LIVING_UI:WATCHDOG] Created fix task {task_id} for {project.name} ({project_id})"
            )
        except Exception as e:
            logger.error(f"[LIVING_UI:WATCHDOG] Failed to create fix task: {e}")

    @staticmethod
    def _rewrite_ports_in_manifest(node: Any, port_map: Dict[str, str]) -> Any:
        """Structurally rewrite port numbers inside manifest values.

        Rewrites int values equal to an old port and standalone number tokens
        inside string values (health URLs, start commands) that are not
        adjacent to any word character — so ids like "a3100b" are untouched.
        A single-pass alternation is used so chained mappings like
        {3100: 3101, 3101: 3102} never double-replace. This replaces the old
        whole-file str.replace(), which could corrupt ids, versions, or
        timestamps that happened to contain the port digits.
        """
        if not port_map:
            return node
        pattern = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(p) for p in port_map) + r")(?!\w)"
        )

        def rewrite(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: rewrite(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if isinstance(value, str):
                return pattern.sub(lambda m: port_map[m.group(1)], value)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and str(value) in port_map
            ):
                return int(port_map[str(value)])
            return value

        return rewrite(node)

    def _load_projects(self) -> None:
        """Load projects from persistent storage."""
        if self._projects_file.exists():
            try:
                saved_tunnels: List[Tuple[str, str]] = []
                with open(self._projects_file, "r") as f:
                    data = json.load(f)
                    for project_data in data.get("projects", []):
                        project = LivingUIProject(
                            id=project_data["id"],
                            name=project_data["name"],
                            description=project_data.get("description", ""),
                            path=project_data["path"],
                            status=project_data.get("status", "stopped"),
                            port=project_data.get("port"),
                            backend_port=project_data.get("backendPort"),
                            created_at=project_data.get(
                                "createdAt", datetime.now().timestamp()
                            )
                            / 1000,
                            features=project_data.get("features", []),
                            theme=project_data.get("theme", "system"),
                            icon=project_data.get("icon"),
                            auto_launch=project_data.get("autoLaunch", False),
                            log_cleanup=project_data.get("logCleanup", True),
                            project_type=project_data.get("projectType", "native"),
                            app_runtime=project_data.get("appRuntime"),
                            ui_theme=project_data.get("uiTheme"),
                            # dev_port only — so startup cleanup can kill an
                            # orphaned dev server; dev_url/process are never
                            # valid across restarts.
                            dev_port=project_data.get("devPort"),
                        )
                        # Restore the task linkage (see to_dict note).
                        project.task_id = project_data.get("taskId")
                        # Keep the saved tunnel URL optimistically; reachability
                        # is verified in a background thread below so startup
                        # doesn't block on a HEAD request per tunneled project.
                        saved_tunnel = project_data.get("tunnelUrl")
                        if saved_tunnel:
                            project.tunnel_url = saved_tunnel
                            saved_tunnels.append((project.id, saved_tunnel))
                        # Reset status to stopped for all loaded projects
                        project.status = (
                            "stopped" if project.status == "running" else project.status
                        )
                        self.projects[project.id] = project
                        # Track both frontend and backend ports
                        if project.port:
                            self._used_ports.add(project.port)
                        if project.backend_port:
                            self._used_ports.add(project.backend_port)
                logger.info(f"[LIVING_UI] Loaded {len(self.projects)} projects")
                if saved_tunnels:
                    threading.Thread(
                        target=self._validate_saved_tunnels,
                        args=(saved_tunnels,),
                        daemon=True,
                        name="living-ui-tunnel-check",
                    ).start()
            except Exception as e:
                logger.error(f"[LIVING_UI] Failed to load projects: {e}")

    def _save_projects(self) -> None:
        """Save projects to persistent storage."""
        try:
            data = {"projects": [p.to_dict() for p in self.projects.values()]}
            with open(self._projects_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to save projects: {e}")

    async def _wait_for_server(self, port: int, timeout: int = 10) -> bool:
        """
        Wait for a server to start listening on a port.

        Args:
            port: The port to check
            timeout: Maximum seconds to wait

        Returns:
            True if server is responding, False if timeout
        """
        for _ in range(timeout * 2):
            if self._is_port_in_use(port):
                return True
            await asyncio.sleep(0.5)
        return False

    async def _wait_for_health_check(self, url: str, timeout: int = 15) -> bool:
        """
        Wait for a server's health endpoint to respond.

        Args:
            url: The health check URL (e.g., http://localhost:3101/health)
            timeout: Maximum seconds to wait

        Returns:
            True if health check passes, False if timeout
        """
        import urllib.request
        import urllib.error

        for _ in range(timeout * 2):
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status == 200:
                        return True
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                OSError,
            ):
                pass
            await asyncio.sleep(0.5)
        return False

    def _get_launch_lock(self, project_id: str) -> asyncio.Lock:
        """Per-project lock serializing launch/stop (see __init__ note)."""
        lock = self._launch_locks.get(project_id)
        if lock is None:
            lock = asyncio.Lock()
            self._launch_locks[project_id] = lock
        return lock

    def _already_running_result(self, project) -> Optional[dict]:
        """Success dict for a healthy, already-running, STILL-VALIDATED
        project, else None (= run the real pipeline).

        The validated check is load-bearing: a post-pass code edit clears
        ``validation_passed_at`` (see invalidate_validation), and this fast
        path never sets it — so short-circuiting a running-but-invalidated
        project reports "validation PASSED" while ``is_validated()`` stays
        False, and living_ui_notify_ready refuses forever
        Running but invalidated must fall through to the full pipeline so a
        pass can actually be re-conferred.

        A fast path only — its result still flows through launch_and_verify's
        recording block like any other validate outcome.
        """
        if not (
            project
            and project.status == "running"
            and project.url
            and project.validation_passed_at
        ):
            return None
        backend_ok = (
            project.backend_process is None or project.backend_process.poll() is None
        )
        serving = (
            (project.process is not None and project.process.poll() is None)
            or (project.app_process is not None and project.app_process.poll() is None)
            or (bool(project.port) and self._is_port_in_use(project.port))
        )
        if not (backend_ok and serving):
            return None
        logger.info(
            f"[LIVING_UI:PIPELINE] {project.id} already running — skipping duplicate launch"
        )
        return {
            "status": "success",
            "url": project.url,
            "backend_url": project.backend_url,
            "port": project.port,
            "note": "already running",
        }

    async def launch_and_verify(self, project_id: str) -> dict:
        """
        Launch and verify a Living UI project using its manifest pipeline.

        Serialized per project: concurrent calls (double-click, Settings page
        + tab page, retry while a slow first attempt is still testing) wait
        for the in-flight launch instead of killing its freshly started
        backend mid-pipeline. Once the lock is acquired, an already-running
        healthy project returns success immediately — but ONLY while its
        validation pass is still current; running-but-invalidated re-runs
        the full pipeline.

        Returns:
            {"status": "success", "url": "...", "backend_url": "...", "port": N}
            {"status": "error", "step": "validation", "errors": [...all errors...]}
        """
        lock = self._get_launch_lock(project_id)
        if lock.locked():
            logger.info(
                f"[LIVING_UI:PIPELINE] Launch already in flight for {project_id}; waiting"
            )
        async with lock:
            project = self.projects.get(project_id)
            result = self._already_running_result(project)
            if result is None:
                result = await self._launch_and_verify_impl(project_id)
            # Feed the no-change guard: remember the source signature of a
            # FAILED attempt so an identical retry is refused; a success (or
            # a refusal by the guard itself) clears/keeps state accordingly.
            try:
                if project and project.project_type == "native":
                    if result.get("status") == "success":
                        self._last_validate_attempt.pop(project_id, None)
                    elif result.get("step") != "validation.unchanged":
                        self._last_validate_attempt[project_id] = (
                            self._source_signature(Path(project.path)),
                            tuple(result.get("errors") or [])[:15],
                        )
            except Exception:
                pass
            # Feed the build director. EVERY outcome of EVERY validate must be
            # recorded — post-launch failures and the already-running fast
            # path included — or the build loop's round/launched state
            # silently freezes. This is the wrapper's single exit; nothing
            # above may return early. Fail-open.
            try:
                if project and (
                    project.project_type == "native"
                    or result.get("status") == "success"
                ):
                    from app.workflows.living_ui.steps import record_validate_outcome

                    record_validate_outcome(Path(project.path), result)
            except Exception:
                pass
            return result

    async def _launch_and_verify_impl(self, project_id: str) -> dict:
        """
        The launch pipeline body — an orchestrator over the named stages
        below. Only ever runs under the per-project launch lock (call
        launch_and_verify, never this directly).

        Stage contract: each stage returns an error result dict to stop the
        pipeline, or None to continue; success is produced only by
        _finish_launch at the end. Validation tracks run in parallel to
        collect ALL errors before any server starts.
        """
        setup, err = self._pipeline_setup(project_id)
        if err:
            return err
        project, project_path, pipeline = setup

        logger.info(
            f"[LIVING_UI:PIPELINE] Starting launch pipeline for {project.name} ({project_id})"
        )
        pipeline_started = datetime.now()

        # Ensure index.html has the CraftBot theme sync listener (self-healing for older installs)
        self._patch_theme_listener(project_path)

        # Single-process mode (external apps) has its own pipeline.
        app_cfg = pipeline.get("app")
        if app_cfg:
            return await self._launch_single_process(
                project_id, project, project_path, app_cfg
            )

        await self._prepare_workspace(project, project_path)

        if not self._has_files_changed(project_path):
            logger.info(
                "[LIVING_UI:PIPELINE] No source changes detected — skipping tests/build, starting servers directly"
            )
            return await self._launch_servers_only(
                project_id, project, project_path, pipeline
            )

        # Clean up old log files so each launch starts fresh (if enabled)
        if project.log_cleanup:
            self._cleanup_project_logs(project_path)

        err = await self._run_validation_tracks(project, project_path, pipeline)
        if err:
            return err

        ops_warnings: List[str] = []
        backend_cfg = pipeline.get("backend")
        if backend_cfg:
            err, ops_warnings = await self._start_backend_stage(
                project_id, project, project_path, backend_cfg, pipeline_started
            )
            if err:
                return err

        frontend_cfg = pipeline.get("frontend")
        if frontend_cfg:
            err = await self._start_frontend_stage(
                project_id, project, project_path, frontend_cfg
            )
            if err:
                return err

        return self._finish_launch(project_id, project, project_path, ops_warnings)

    def _pipeline_setup(self, project_id: str):
        """Resolve the project, refuse unchanged retries, load the manifest
        and rewrite its ports to the allocated ones.

        Returns ((project, project_path, pipeline), None) or (None, error).
        """
        project = self.projects.get(project_id)
        if not project:
            return None, {
                "status": "error",
                "step": "setup",
                "errors": [f"Project not found: {project_id}"],
            }

        project_path = Path(project.path)
        if not project_path.exists():
            return None, {
                "status": "error",
                "step": "setup",
                "errors": [f"Project path not found: {project.path}"],
            }

        # No-change guard: re-validating an UNCHANGED project after a failure
        # is pure spin. If nothing in the source tree moved since the last
        # failing attempt, refuse with the same error list instead of
        # re-running the whole pipeline.
        #
        # CREATION-PHASE ONLY BY DESIGN: post-launch, a validate with no source
        # change is a legitimate relaunch (restart a stopped app), not spin —
        # refusing it there would block the relaunch.
        if (
            project.project_type == "native"
            and not (project_path / ".last_launch").exists()
        ):
            try:
                last = self._last_validate_attempt.get(project_id)
                if last is not None and last[0] == self._source_signature(project_path):
                    return None, {
                        "status": "error",
                        "step": "validation.unchanged",
                        "errors": [
                            "NOTHING has changed since the last failed "
                            "validation — running it again cannot pass. Fix "
                            "the previously reported errors (dispatch the "
                            "responsible specialists), then validate once:"
                        ]
                        + list(last[1])[:15],
                    }
            except Exception:
                pass

        # Every pipeline attempt invalidates the previous pass until this
        # attempt succeeds — a stale "validation passed" must never gate-keep
        # notify_ready after the project has demonstrably changed or failed.
        project.validation_passed_at = None

        manifest_path = project_path / "config" / "manifest.json"
        if not manifest_path.exists():
            return None, {
                "status": "error",
                "step": "setup",
                "errors": ["config/manifest.json not found"],
            }

        try:
            # Ensure ports are allocated and available
            if not project.port:
                project.port = self._allocate_port()
            if not project.backend_port:
                project.backend_port = self._allocate_port()

            # Read manifest and resolve ports — always use project's current
            # ports regardless of what's hardcoded in the manifest file
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_ports = manifest.get("ports", {})
            old_frontend = str(old_ports.get("frontend", old_ports.get("app", "")))
            old_backend = str(old_ports.get("backend", ""))

            port_map = {}
            if old_frontend and old_frontend != str(project.port):
                port_map[old_frontend] = str(project.port)
            if old_backend and old_backend != str(project.backend_port):
                port_map[old_backend] = str(project.backend_port)

            # Write updated manifest back to disk so frontend can read correct ports
            if port_map:
                manifest = self._rewrite_ports_in_manifest(manifest, port_map)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2), encoding="utf-8"
                )
                logger.info(
                    f"[LIVING_UI:PIPELINE] Updated manifest ports: frontend={project.port}, backend={project.backend_port}"
                )
        except Exception as e:
            return None, {
                "status": "error",
                "step": "setup",
                "errors": [f"Failed to parse manifest: {e}"],
            }

        pipeline = manifest.get("pipeline", {})
        if not pipeline:
            return None, {
                "status": "error",
                "step": "setup",
                "errors": ["No pipeline defined in manifest"],
            }
        return (project, project_path, pipeline), None

    async def _prepare_workspace(self, project, project_path: Path) -> None:
        """Pre-build hygiene: schema migration, orphan processes, walk DB wipe.
        Every part is best-effort — none of it may block a launch."""
        # Platform-owned additive schema migration: bare create_all never adds
        # columns to existing tables — without this step a model change 500s
        # the routes. Runs for ALL native projects regardless of engine.
        try:
            from .migration import run_migration

            python_exe = ""
            try:
                python_exe = self._find_real_python()
            except Exception:
                pass
            migrate_result = await asyncio.to_thread(
                run_migration, project_path, python_exe
            )
            if migrate_result["added"]:
                logger.info(
                    f"[LIVING_UI:PIPELINE] Migration added columns: {migrate_result['added']}"
                )
            elif migrate_result["status"] == "error":
                logger.warning(
                    f"[LIVING_UI:PIPELINE] Migration failed (continuing): "
                    f"{migrate_result['output'][-300:]}"
                )
        except Exception as e:
            logger.warning(
                f"[LIVING_UI:PIPELINE] Migration step error (continuing): {e}"
            )

        # Stop any existing processes from previous launch attempts so orphan
        # backend/vite processes never accumulate on repeated calls.
        if project.backend_process and project.backend_process.poll() is None:
            logger.info(
                "[LIVING_UI:PIPELINE] Killing existing backend process before relaunch"
            )
            self._terminate_process(project.backend_process)
            project.backend_process = None
        if project.process and project.process.poll() is None:
            logger.info(
                "[LIVING_UI:PIPELINE] Killing existing frontend process before relaunch"
            )
            self._terminate_process(project.process)
            project.process = None

        # Walk hygiene: the browser walk judges first-launch behavior, which
        # is only meaningful against an EMPTY database. Runs AFTER the old
        # servers are killed so no live writer can race the delete.
        #
        # CREATION-PHASE ONLY BY DESIGN (not the .last_launch disease): once
        # the app has launched, its rows are real data — the walk creates them
        # to prove persistence works, and the user's own use creates more.
        # Wiping post-launch would destroy exactly what we asked for.
        if (
            project.project_type == "native"
            and not (project_path / ".last_launch").exists()
        ):
            try:
                from .data_plane import wipe_all_entity_rows

                schema_file = project_path / "config" / "schema.json"
                if schema_file.exists():
                    await asyncio.to_thread(
                        wipe_all_entity_rows,
                        project_path,
                        json.loads(schema_file.read_text(encoding="utf-8")),
                    )
            except Exception as e:
                logger.warning(f"[LIVING_UI:PIPELINE] Walk DB wipe skipped: {e}")

    async def _run_validation_tracks(
        self, project, project_path: Path, pipeline: dict
    ) -> Optional[dict]:
        """Backend and frontend validation in parallel; ALL errors collected
        before any server starts. None = clean."""
        backend_cfg = pipeline.get("backend")
        frontend_cfg = pipeline.get("frontend")

        backend_task = None
        frontend_task = None

        if backend_cfg:
            backend_task = asyncio.create_task(
                self._validate_backend_track(project_path, backend_cfg)
            )

        if frontend_cfg:
            frontend_cwd = project_path / frontend_cfg.get("cwd", ".")
            if str(frontend_cwd) == ".":
                frontend_cwd = project_path
            frontend_task = asyncio.create_task(
                self._validate_frontend_track(project.id, frontend_cfg, frontend_cwd)
            )

        all_errors: List[str] = []
        if backend_task:
            all_errors.extend(await backend_task)
        if frontend_task:
            all_errors.extend(await frontend_task)

        # Exact-normalized dedup: one broken import cascades through several
        # steps as the SAME message — show each distinct failure once.
        all_errors = self._dedupe_errors(all_errors)

        if not all_errors:
            logger.info(
                "[LIVING_UI:PIPELINE] All validation passed, starting servers..."
            )
            return None

        logger.error(
            f"[LIVING_UI:PIPELINE] Validation failed with {len(all_errors)} error(s)"
        )
        for err in all_errors[:10]:
            logger.error(f"[LIVING_UI:PIPELINE]   {err}")
        project.status = "error"
        project.error = f"{len(all_errors)} validation error(s)"
        self._save_projects()
        return {"status": "error", "step": "validation", "errors": all_errors}

    async def _start_and_gate_backend(
        self,
        project_id: str,
        project,
        project_path: Path,
        backend_cfg: dict,
    ) -> Optional[dict]:
        """THE backend start sequence, shared by the full pipeline and the
        fast (no-source-change) relaunch path: allocate/free the port,
        provision + start the process (PocketBase or manifest command),
        gate on health, then import the declared collections.

        Returns an error result dict to stop the caller, or None on success
        (project.backend_process/backend_url are set)."""
        backend_cwd = project_path / backend_cfg.get("cwd", "backend")
        backend_port = project.backend_port
        if not backend_port:
            backend_port = self._allocate_port()
            project.backend_port = backend_port

        if not await self._ensure_port_available(backend_port):
            return {
                "status": "error",
                "step": "backend.port",
                "errors": [f"Port {backend_port} is occupied and could not be freed"],
            }

        # PocketBase: the platform owns the start command — bootstrap the
        # superuser (never serve into PB's browser installer), serve
        # pb_data/pb_hooks, then import the declared collections after health.
        if backend_cfg.get("engine") == "pocketbase":
            from app.living_ui import pocketbase_runtime as pbrt

            backend_cwd = project_path
            # Bootstrap is idempotent; retry once for transient first-boot
            # races before refusing to serve an unprovisioned instance.
            if not (
                pbrt.bootstrap_superuser(project_path)
                or pbrt.bootstrap_superuser(project_path)
            ):
                return {
                    "status": "error",
                    "step": "backend.start",
                    "errors": [
                        "PocketBase superuser bootstrap failed — refusing "
                        "to serve an unprovisioned instance"
                    ],
                }
            start_cmd = pbrt.serve_command(project_path, backend_port)
        else:
            start_cmd = backend_cfg.get("start", "")
            if not start_cmd:
                return {
                    "status": "error",
                    "step": "backend.start",
                    "errors": ["No start command in manifest"],
                }

        logs_dir = project_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "backend_output.log"

        # Generate bridge token for integration proxy
        from uuid import uuid4

        project.bridge_token = str(uuid4())

        backend_process = self._start_process(
            backend_cwd, start_cmd, log_file, port=backend_port, project=project
        )
        project.backend_process = backend_process
        logger.info(f"[LIVING_UI:PIPELINE] Backend starting on port {backend_port}")

        health_url = backend_cfg.get("health")
        if health_url:
            healthy = await self._wait_for_health_check(health_url, timeout=20)
            if not healthy:
                log_tail = self._read_log_tail(log_file, 1000)
                if backend_process.poll() is not None:
                    err = (
                        f"Backend process exited with code {backend_process.returncode}"
                    )
                    self._close_process_log(backend_process)
                else:
                    err = f"Backend not responding at {health_url}"
                    self._terminate_process(backend_process)
                project.backend_process = None
                return {
                    "status": "error",
                    "step": "backend.health",
                    "errors": [err, log_tail],
                }

        project.backend_url = f"http://localhost:{backend_port}"
        logger.info(f"[LIVING_UI:PIPELINE] Backend healthy on port {backend_port}")

        # PocketBase: import the declared collections (idempotent — also
        # covers a wiped/replaced pb_data since the last full launch).
        if backend_cfg.get("engine") == "pocketbase":
            from app.living_ui import pocketbase_runtime as pbrt

            import_err = await asyncio.to_thread(
                pbrt.import_collections, project_path, backend_port
            )
            if import_err:
                await self.stop_backend(project_id)
                return {
                    "status": "error",
                    "step": "backend.schema",
                    "errors": [import_err],
                }
        return None

    async def _start_backend_stage(
        self,
        project_id: str,
        project,
        project_path: Path,
        backend_cfg: dict,
        pipeline_started,
    ):
        """Start + gate the backend. Returns (error_or_None, ops_warnings)."""
        err = await self._start_and_gate_backend(
            project_id, project, project_path, backend_cfg
        )
        if err:
            return err, []
        backend_port = project.backend_port

        # PocketBase: regenerate the typed frontend surface before anything
        # tests or walks the app (the collections themselves were imported
        # by _start_and_gate_backend).
        if backend_cfg.get("engine") == "pocketbase":
            from .typegen import regenerate_types

            regenerate_types(project_path)

        # Dirty-DB guard: the walk's first-launch criteria require an empty
        # database and the wipe ran earlier in this pipeline — rows here mean
        # the wipe regressed or something seeded data between wipe and boot.
        #
        # CREATION-PHASE ONLY BY DESIGN: it is paired with the wipe in
        # _prepare_workspace, and post-launch rows are expected (real data).
        if (
            project.project_type == "native"
            and not (project_path / ".last_launch").exists()
        ):
            dirty = await self._dirty_db_rows(project.backend_url, project_path)
            if dirty:
                await self.stop_backend(project_id)
                return {
                    "status": "error",
                    "step": "walk.dirty_db",
                    "errors": [
                        "The database is NOT empty at launch — the walk's "
                        "first-launch checks would report false failures. "
                        "This is a platform hygiene problem, not an app "
                        f"bug. Rows found: {dirty}"
                    ],
                }, []

        # Runtime-log review: fatal failures (sections crashing at render,
        # unhandled 500s) are RECORDED in logs — read them and fail the
        # validate they belong to. Runs for EVERY validate of a native
        # project: _review_runtime_logs only counts entries from THIS
        # validation window and fails open on unreadable logs.
        if project.project_type == "native":
            log_errors = await asyncio.to_thread(
                self._review_runtime_logs, project_path, pipeline_started
            )
            if log_errors:
                logger.error(
                    f"[LIVING_UI:PIPELINE] [runtime.logs] "
                    f"{len(log_errors)} runtime error(s) recorded during "
                    f"validation for {project_id}"
                )
                await self.stop_backend(project_id)
                return {
                    "status": "error",
                    "step": "runtime.logs",
                    "errors": log_errors,
                }, []

        # Validate the operations manifest against the live OpenAPI:
        # structural errors (dead routes, undeclared path params, broken
        # templates) block the launch with precise fixes; coverage gaps
        # are warnings so heuristics can't brick a launch.
        ops_warnings: List[str] = []
        try:
            from .ops_analyzer import check_manifest, fetch_openapi

            spec = await asyncio.to_thread(
                fetch_openapi, f"http://localhost:{backend_port}"
            )
            findings = await asyncio.to_thread(check_manifest, project_path, spec)
            ops_errors = [
                f"{f['message']} — fix: {f['fix']}"
                for f in findings
                if f["level"] == "error"
            ]
            ops_warnings = [
                f"{f['message']} — fix: {f['fix']}"
                for f in findings
                if f["level"] == "warning"
            ]
            if ops_errors:
                await self.stop_backend(project_id)
                return {
                    "status": "error",
                    "step": "operations.check",
                    "errors": ops_errors,
                }, []
            for warning in ops_warnings:
                logger.warning(f"[LIVING_UI:PIPELINE] ops manifest: {warning}")
        except Exception as e:
            logger.warning(f"[LIVING_UI:PIPELINE] ops manifest check skipped: {e}")
            ops_warnings = []

        return None, ops_warnings

    async def _start_frontend_stage(
        self, project_id: str, project, project_path: Path, frontend_cfg: dict
    ) -> Optional[dict]:
        """Start + health-check the frontend server. None = ready."""
        frontend_cwd = project_path / frontend_cfg.get("cwd", ".")
        if str(frontend_cwd) == ".":
            frontend_cwd = project_path

        frontend_port = project.port
        if not frontend_port:
            frontend_port = self._allocate_port()
            project.port = frontend_port

        if not await self._ensure_port_available(frontend_port):
            await self.stop_backend(project_id)
            return {
                "status": "error",
                "step": "frontend.port",
                "errors": [f"Port {frontend_port} is occupied and could not be freed"],
            }

        start_cmd = frontend_cfg.get("start", "")
        if not start_cmd:
            await self.stop_backend(project_id)
            return {
                "status": "error",
                "step": "frontend.start",
                "errors": ["No start command in manifest"],
            }

        frontend_log = self._create_frontend_log(project_path)
        frontend_process = self._start_process(
            frontend_cwd, start_cmd, frontend_log, port=frontend_port
        )
        project.process = frontend_process
        project.port = frontend_port
        logger.info(f"[LIVING_UI:PIPELINE] Frontend starting on port {frontend_port}")

        server_ready = await self._wait_for_server(frontend_port, timeout=15)
        if not server_ready:
            log_tail = self._read_log_tail(frontend_log, 1000)
            if frontend_process.poll() is not None:
                err = f"Frontend process exited with code {frontend_process.returncode}"
                self._close_process_log(frontend_process)
            else:
                err = f"Frontend not responding on port {frontend_port}"
                self._terminate_process(frontend_process)
            project.process = None
            await self.stop_backend(project_id)
            return {
                "status": "error",
                "step": "frontend.health",
                "errors": [err, log_tail],
            }

        project.url = f"http://localhost:{frontend_port}"
        logger.info(f"[LIVING_UI:PIPELINE] Frontend ready on port {frontend_port}")
        return None

    def _finish_launch(
        self, project_id: str, project, project_path: Path, ops_warnings: List[str]
    ) -> dict:
        """Record the successful launch. Success means the app is RUNNING —
        not yet "done"; the independent walk_verify gate sets
        validation_passed_at once it confirms the features actually work."""
        # The production preview is up — the Live Construction View's dev
        # server has served its purpose. (Killing it doesn't blank the dev
        # iframe: the page persists visually until the host swaps to the
        # production URL on living_ui_ready.)
        self.stop_dev_preview(project_id)
        project.status = "running"
        project.error = None
        self._save_projects()
        self._save_launch_timestamp(project_path)

        logger.info(
            f"[LIVING_UI:PIPELINE] Launch complete for {project.name} ({project_id})"
        )
        if project.url:
            logger.info(f"[LIVING_UI:PIPELINE]   Frontend: {project.url}")
        if project.backend_url:
            logger.info(f"[LIVING_UI:PIPELINE]   Backend: {project.backend_url}")

        success_result = {
            "status": "success",
            "url": project.url,
            "backend_url": project.backend_url,
            "port": project.port,
        }
        if ops_warnings:
            success_result["ops_warnings"] = ops_warnings
        return success_result

    async def _launch_servers_only(
        self,
        project_id: str,
        project: "LivingUIProject",
        project_path: Path,
        pipeline: dict,
    ) -> dict:
        """Fast path: start servers without running tests/build (no source changes detected)."""
        backend_cfg = pipeline.get("backend")
        frontend_cfg = pipeline.get("frontend")

        # Start backend — the SAME start/gate sequence as the full pipeline
        # (one implementation; only tests/build are skipped on this path).
        if backend_cfg:
            err = await self._start_and_gate_backend(
                project_id, project, project_path, backend_cfg
            )
            if err:
                return err

        # Start frontend
        if frontend_cfg:
            frontend_cwd = project_path / frontend_cfg.get("cwd", ".")
            if str(frontend_cwd) == ".":
                frontend_cwd = project_path

            frontend_port = project.port
            if not frontend_port:
                frontend_port = self._allocate_port()
                project.port = frontend_port

            if not await self._ensure_port_available(frontend_port):
                await self.stop_backend(project_id)
                return {
                    "status": "error",
                    "step": "frontend.port",
                    "errors": [f"Port {frontend_port} occupied"],
                }

            start_cmd = frontend_cfg.get("start", "")
            if start_cmd:
                frontend_log = self._create_frontend_log(project_path)
                frontend_process = self._start_process(
                    frontend_cwd, start_cmd, frontend_log, port=frontend_port
                )
                project.process = frontend_process
                project.port = frontend_port
                logger.info(
                    f"[LIVING_UI:PIPELINE] Frontend starting on port {frontend_port} (fast)"
                )

                server_ready = await self._wait_for_server(frontend_port, timeout=15)
                if not server_ready:
                    log_tail = self._read_log_tail(frontend_log, 1000)
                    if frontend_process.poll() is not None:
                        err = f"Frontend process exited with code {frontend_process.returncode}"
                        self._close_process_log(frontend_process)
                    else:
                        err = f"Frontend not responding on port {frontend_port}"
                        self._terminate_process(frontend_process)
                    project.process = None
                    await self.stop_backend(project_id)
                    return {
                        "status": "error",
                        "step": "frontend.health",
                        "errors": [err, log_tail],
                    }

                project.url = f"http://localhost:{frontend_port}"
                logger.info(
                    f"[LIVING_UI:PIPELINE] Frontend ready on port {frontend_port}"
                )

        project.status = "running"
        project.error = None
        self._save_projects()
        self._save_launch_timestamp(project_path)

        logger.info(
            f"[LIVING_UI:PIPELINE] Fast launch complete for {project.name} ({project_id})"
        )
        return {
            "status": "success",
            "url": project.url,
            "backend_url": project.backend_url,
            "port": project.port,
        }

    async def _validate_backend_track(
        self, project_path: Path, backend_cfg: dict
    ) -> List[str]:
        """PocketBase pre-start checks: binary availability + a parseable
        collections declaration. CRUD needs no tests (PB is trusted like
        shadcn); custom pb_hooks routes are smoked post-start.

        Returns list of error strings (empty = all passed).
        """
        errors: List[str] = []
        if backend_cfg.get("engine") != "pocketbase":
            # Legacy FastAPI manifests are no longer validated (the Python
            # backend pipeline was removed with the PocketBase pivot).
            logger.warning(
                "[LIVING_UI:PIPELINE] Unsupported backend engine "
                f"{backend_cfg.get('engine')!r} — skipping backend validation"
            )
            return errors

        from app.living_ui import pocketbase_runtime as pbrt

        try:
            await asyncio.to_thread(pbrt.ensure_binary)
        except Exception as e:
            errors.append(f"[backend.pocketbase] {e}")
            return errors
        try:
            pbrt.load_schema(project_path)
        except FileNotFoundError:
            pass  # no schema yet — PB still serves (empty app)
        except Exception as e:
            errors.append(
                "[backend.schema] config/schema.json is not valid "
                f"PocketBase collections JSON: {e}"
            )
        return errors

    async def _validate_frontend_track(
        self, project_id: str, frontend_cfg: dict, frontend_cwd: Path
    ) -> List[str]:
        """
        Run frontend validation: install → build.
        Returns list of error strings (empty = all passed).
        """
        errors: List[str] = []

        # 1. Install
        install_cmd = frontend_cfg.get("install")
        if install_cmd:
            needs_install = not (frontend_cwd / "node_modules").exists()
            if needs_install:
                result = await self._run_pipeline_command(
                    frontend_cwd, install_cmd, step_name="frontend.install"
                )
                if result["status"] == "error":
                    errors.append(
                        f"[frontend.install] {result['errors'][0] if result.get('errors') else 'install failed'}"
                    )
                    return errors  # Can't build without dependencies

        # (Coding Agent pivot: shadcn/ui is VENDORED in the template — plain
        # editable files, already wired. No install step to half-fail.)

        # 2. Build
        build_cmd = frontend_cfg.get("build")
        if build_cmd:
            result = await self._run_pipeline_command(
                frontend_cwd, build_cmd, step_name="frontend.build", timeout=240
            )
            if result["status"] == "error":
                build_errors = result.get("errors", ["build failed"])
                for err in build_errors:
                    errors.append(f"[frontend.build] {err}")

        return errors

    @staticmethod
    def _certifi_ssl_env() -> dict:
        """SSL CA bundle env for project subprocesses (shared impl in
        app.workflows.living_ui.workspace — Workspace.run injects the same
        vars, so pipeline and verify_build subprocesses can't drift)."""
        from app.workflows.living_ui.workspace import certifi_ssl_env

        return certifi_ssl_env()

    def _review_runtime_logs(self, project_path: Path, since: "datetime") -> List[str]:
        """Runtime-error evidence the platform records but nothing used to
        read: the app's own backend log (unhandled 500s, tracebacks) and the
        captured frontend console (runtime crashes, failed requests). Only
        entries from the current validation window count, so errors the
        agent already caused and fixed mid-build never re-fail a pass.
        Fail-open: unreadable/absent logs contribute nothing."""
        errors: List[str] = []
        seen = set()

        def add(source: str, line: str) -> None:
            key = " ".join(line.split())
            if key and key not in seen:
                seen.add(key)
                errors.append(f"[{source}] {line.strip()[:400]}")

        logs_dir = Path(project_path) / "backend" / "logs"
        # Backend logs: one file per run, timestamped name — only files from
        # THIS launch window.
        stamp = since.strftime("%Y%m%d_%H%M%S")
        try:
            for log_file in sorted(logs_dir.glob("backend_*.log")):
                if log_file.stem.replace("backend_", "") < stamp:
                    continue
                for line in log_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    if "| ERROR" in line:
                        add("backend", line)
        except OSError:
            pass
        # Frontend console capture: ISO-UTC timestamps, appended across runs
        # — filter to the window, keep crash-like lines and client-error
        # responses (transient 5xx during restarts is the backend log's job).
        try:
            console = logs_dir / "frontend_console.log"
            if console.exists():
                from datetime import timezone

                since_epoch = since.timestamp()
                for line in console.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    parts = line.split(" | ", 2)
                    if len(parts) != 3 or parts[1].strip() != "ERROR":
                        continue
                    try:
                        ts = datetime.fromisoformat(
                            parts[0].strip().replace("Z", "+00:00")
                        )
                        if ts.tzinfo is not None:
                            ts_epoch = ts.timestamp()
                        else:
                            ts_epoch = ts.replace(tzinfo=timezone.utc).timestamp()
                    except ValueError:
                        continue
                    if ts_epoch < since_epoch:
                        continue
                    msg = parts[2]
                    crashy = (
                        "Unhandled" in msg
                        or "Error" in msg
                        or "rejection" in msg
                        or "\u2192 404" in msg
                        or "\u2192 422" in msg
                        or "-> 404" in msg
                        or "-> 422" in msg
                    )
                    if crashy:
                        add("frontend console", msg)
        except OSError:
            pass
        return errors

    async def _run_pipeline_command(
        self, cwd: Path, command: str, step_name: str, timeout: int = 1200
    ) -> dict:
        """Run a single pipeline command. Returns {"status": "success"} or {"status": "error", ...}."""
        command = self._resolve_python_in_command(command)

        logger.info(f"[LIVING_UI:PIPELINE] [{step_name}] Running: {command}")

        try:
            cmd_env = os.environ.copy()
            cmd_env.update(self._certifi_ssl_env())
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                env=cmd_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                logger.info(f"[LIVING_UI:PIPELINE] [{step_name}] OK")
                return {"status": "success"}
            else:
                # COMPLETE output, both streams — never truncate. Compilers
                # (tsc) list every error at once; cutting to a tail turned
                # multi-error failures into one-error-per-validation cycles
                # (observed: cycles whose only "error" was the npm banner).
                output = "\n".join(s for s in (stdout_str, stderr_str) if s)
                logger.error(
                    f"[LIVING_UI:PIPELINE] [{step_name}] FAILED (exit code {proc.returncode})"
                )
                return {
                    "status": "error",
                    "step": step_name,
                    "errors": [output]
                    if output
                    else [f"Command failed with exit code {proc.returncode}"],
                }
        except asyncio.TimeoutError:
            logger.error(f"[LIVING_UI:PIPELINE] [{step_name}] TIMEOUT ({timeout}s)")
            return {
                "status": "error",
                "step": step_name,
                "errors": [f"Command timed out after {timeout}s"],
            }
        except Exception as e:
            logger.error(f"[LIVING_UI:PIPELINE] [{step_name}] ERROR: {e}")
            return {"status": "error", "step": step_name, "errors": [str(e)]}

    _python_path_cache: Optional[str] = None

    @classmethod
    def _find_real_python(cls) -> str:
        """Find a usable system Python interpreter, skipping the Microsoft
        Store stub alias.

        On Windows, `%LocalAppData%\\Microsoft\\WindowsApps\\python.exe` is
        an "App Execution Alias" stub that prints "Python was not found;
        run without arguments to install from the Microsoft Store..." and
        exits non-zero — even when the user HAS python.org's Python
        installed elsewhere. The stub is high on PATH so a naive
        `shutil.which("python")` returns it, leading to silent failures.

        Strategy:
          1. Walk every entry returned by `shutil.which`-style PATH lookup
             (using PATHEXT-aware multi-candidate search) for both
             `python3` and `python`.
          2. Skip anything in WindowsApps (the Store-stub directory).
          3. Validate each remaining candidate by running it with
             `--version` and checking it actually printed "Python".
          4. Fall back to the well-known python.org install locations.
        Cached after first hit because shelling out to test takes a few ms.
        """
        if cls._python_path_cache:
            return cls._python_path_cache

        seen = set()

        def _candidates_via_path():
            # shutil.which returns ONLY the first match. We want to walk
            # every PATH entry so a Store stub doesn't shadow a real Python.
            path_dirs = os.environ.get("PATH", "").split(os.pathsep)
            exts = [""] + os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(os.pathsep)
            for d in path_dirs:
                if not d:
                    continue
                for name in ("python3", "python"):
                    for ext in exts:
                        full = os.path.join(d, name + ext)
                        if os.path.isfile(full):
                            yield full

        def _candidates_well_known():
            user = os.path.expanduser("~")
            for ver in ("313", "312", "311", "310"):
                yield rf"C:\Python{ver}\python.exe"
                yield os.path.join(
                    user,
                    "AppData",
                    "Local",
                    "Programs",
                    "Python",
                    f"Python{ver}",
                    "python.exe",
                )

        for path in list(_candidates_via_path()) + list(_candidates_well_known()):
            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            # Microsoft Store App Execution Alias stub — never works.
            if "\\windowsapps\\" in key.replace("/", "\\"):
                continue
            if not os.path.isfile(path):
                continue
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except Exception:
                continue
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode == 0 and "Python" in output:
                cls._python_path_cache = path
                logger.info(
                    f"[LIVING_UI] Resolved system Python: {path} ({output.strip()})"
                )
                return path
        return ""

    @classmethod
    def _resolve_python_in_command(cls, command: str) -> str:
        """Replace a leading `pip`/`python`/`python3` token with a real
        interpreter path.

        In source mode `sys.executable` is the running Python — correct.

        In a PyInstaller-frozen agent (`sys.frozen == True`),
        `sys.executable` is the agent EXE itself, not a Python interpreter.
        Substituting it would spawn the entire agent again with junk args,
        which used to crash (run.py treats `-m pip install ...` as agent
        CLI flags and falls into print_step → OSError 22). Find a real
        system Python via `_find_real_python` (which skips the Microsoft
        Store stub alias). Log loudly if absent so the failure mode is
        "command not found" rather than "agent recursion crash".
        """
        if not (
            command.startswith("pip ")
            or command.startswith("python3 ")
            or command.startswith("python ")
        ):
            return command

        py = sys.executable
        if getattr(sys, "frozen", False):
            py = cls._find_real_python()
            if not py:
                logger.error(
                    "[LIVING_UI] Project needs python/pip but no real system "
                    "Python was found. The Microsoft Store stub at "
                    "%LocalAppData%\\Microsoft\\WindowsApps doesn't count — "
                    "install Python 3.10+ from python.org. Command was: %s",
                    command,
                )
                py = "python"  # will raise FileNotFoundError at spawn time
        if command.startswith("pip "):
            return f'"{py}" -m pip {command[4:]}'
        if command.startswith("python3 "):
            return f'"{py}" {command[8:]}'
        if command.startswith("python "):
            return f'"{py}" {command[7:]}'
        return command

    # ========================================================================
    # Live Construction View dev preview
    #
    # While a project is being created, a Vite dev server (npm run dev) serves
    # the real frontend with hot-module-reload so the user watches the app
    # grow as the agent writes files. It runs on its OWN allocated port —
    # never the project's frontend port — so it can stay alive through the
    # entire launch pipeline and is killed only once the production preview
    # is up (or the project is stopped/deleted). Purely cosmetic: every
    # failure degrades to today's progress-bar experience, never blocks a
    # build.
    # ========================================================================

    DEV_PREVIEW_INSTALL_TIMEOUT = 420  # seconds for npm install
    DEV_PREVIEW_START_TIMEOUT = 45  # seconds for the dev server to respond
    DEV_PREVIEW_MAX_RETRIES = 5  # watchdog re-attempts while status=creating

    @staticmethod
    def _npm_install_marker(project_path: Path) -> Path:
        """Marker held for the duration of the platform's npm install.
        type_check.py fails open while it exists, so write-time tsc never
        reports phantom module errors against a half-extracted
        node_modules (which steers the agent into a second, racing npm)."""
        return project_path / "logs" / ".npm-installing"

    @staticmethod
    def _node_modules_healthy(project_path: Path) -> bool:
        """True when npm install COMPLETED here: npm writes
        node_modules/.package-lock.json last, and the vite shim is what
        `npm run dev` actually needs. Either missing => install never
        finished or was corrupted by a concurrent npm process."""
        nm = project_path / "node_modules"
        if not (nm / ".package-lock.json").is_file():
            return False
        shim = nm / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
        return shim.exists()

    async def _dev_preview_install(
        self, project_path: Path, dev_log: Path, project: "LivingUIProject"
    ) -> bool:
        """Run npm install for the dev preview, holding the install marker."""
        marker = self._npm_install_marker(project_path)
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        try:
            install = self._start_process(
                project_path, "npm install", dev_log, project=project
            )
            waited = 0.0
            while install.poll() is None:
                if waited >= self.DEV_PREVIEW_INSTALL_TIMEOUT:
                    self._terminate_process(install)
                    logger.warning(
                        "[LIVING_UI:DEV_PREVIEW] npm install timed out "
                        f"in {project_path}"
                    )
                    return False
                await asyncio.sleep(2)
                waited += 2
            self._close_process_log(install)
            if install.returncode != 0:
                logger.warning(
                    f"[LIVING_UI:DEV_PREVIEW] npm install failed "
                    f"(exit {install.returncode}) in {project_path}"
                )
                return False
            # (Coding Agent pivot: shadcn/ui is VENDORED in the template — no
            # install step.)
            return True
        finally:
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                pass

    def _dev_preview_eligible(self, project: "LivingUIProject") -> bool:
        if project.project_type != "native" or not project.path:
            return False
        project_path = Path(project.path)
        return (project_path / "package.json").exists() and (
            project_path / "frontend"
        ).exists()

    async def start_dev_preview(self, project_id: str) -> bool:
        """Start the dev preview for a project that is being created.

        Installs npm dependencies if needed (overlaps the Phase 0 interview),
        starts `npm run dev` on a freshly allocated port, and broadcasts the
        URL so the Live Construction View can mount its iframe. Idempotent;
        returns True when a dev server is (already) up. Serialized per
        project so the create-time call and watchdog retries can never run
        two npm installs concurrently.
        """
        lock = self._dev_preview_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            return await self._start_dev_preview_impl(project_id)

    async def _start_dev_preview_impl(self, project_id: str) -> bool:
        project = self.projects.get(project_id)
        if not project or project.status != "creating":
            return False
        if not self._dev_preview_eligible(project):
            return False
        if project.dev_process and project.dev_process.poll() is None:
            return True

        project_path = Path(project.path)
        dev_log = project_path / "logs" / "dev_preview.log"

        try:
            # -- npm install: run when node_modules is missing OR unhealthy
            # (a concurrent npm process can corrupt an install — missing
            # .package-lock.json / vite shim — in which case `npm run dev`
            # dies instantly with "'vite' is not recognized"). npm install
            # over an existing tree is a cheap no-op repair.
            if not self._node_modules_healthy(project_path):
                logger.info(f"[LIVING_UI:DEV_PREVIEW] npm install for {project_id}...")
                if not await self._dev_preview_install(project_path, dev_log, project):
                    return False
                if not self._node_modules_healthy(project_path):
                    logger.warning(
                        f"[LIVING_UI:DEV_PREVIEW] node_modules still unhealthy "
                        f"after install for {project_id}"
                    )
                    return False

            # The project may have been deleted/finished during the install.
            project = self.projects.get(project_id)
            if not project or project.status != "creating":
                return False

            dev_port = self._allocate_port()
            project.dev_port = dev_port
            dev_process = self._start_process(
                project_path,
                # --strictPort: fail rather than silently drift to another
                # port, which would make dev_url point at nothing.
                f"npm run dev -- --port {dev_port} --strictPort",
                dev_log,
                port=dev_port,
                project=project,
            )
            project.dev_process = dev_process

            ready = await self._wait_for_server(
                dev_port, timeout=self.DEV_PREVIEW_START_TIMEOUT
            )
            if not ready:
                self._terminate_process(dev_process)
                project.dev_process = None
                project.dev_port = None
                self._release_port(dev_port)
                logger.warning(
                    f"[LIVING_UI:DEV_PREVIEW] dev server never became ready for {project_id}"
                )
                return False

            project.dev_url = f"http://localhost:{dev_port}"
            self._save_projects()
            logger.info(
                f"[LIVING_UI:DEV_PREVIEW] Live at {project.dev_url} for {project_id}"
            )
            # PocketBase also runs DURING construction — it's the
            # platform binary (always healthy), so builders and the live
            # preview get real data/CRUD from the first minute (the vite
            # proxy forwards /api to it).
            try:
                if (Path(project.path) / "pb_hooks").exists() and not (
                    project.backend_process and project.backend_process.poll() is None
                ):
                    await self.launch_backend(project_id)
            except Exception as e:
                logger.warning(f"[LIVING_UI:DEV_PREVIEW] PocketBase start: {e}")
            from .broadcast import broadcast_living_ui_dev_preview

            await broadcast_living_ui_dev_preview(project_id, project.dev_url)
            return True
        except Exception as e:
            logger.warning(
                f"[LIVING_UI:DEV_PREVIEW] start failed for {project_id}: {e}"
            )
            return False

    def stop_dev_preview(self, project_id: str) -> None:
        """Tear down a project's dev preview (process, port, url). Safe to
        call when none is running."""
        project = self.projects.get(project_id)
        if not project:
            return
        had_preview = bool(project.dev_process or project.dev_port or project.dev_url)
        if project.dev_process:
            self._terminate_process(project.dev_process)
            project.dev_process = None
        if project.dev_port:
            if self._is_port_in_use(project.dev_port):
                self._kill_process_on_port(project.dev_port)
            self._release_port(project.dev_port)
            project.dev_port = None
        project.dev_url = None
        if had_preview:
            self._save_projects()
            logger.info(f"[LIVING_UI:DEV_PREVIEW] Stopped for {project_id}")

    def _start_process(
        self,
        cwd: Path,
        command: str,
        log_file: Path,
        port: int = 0,
        project: "LivingUIProject" = None,
        extra_env: dict = None,
    ) -> subprocess.Popen:
        """Start a background process with output redirected to a log file."""
        command = self._resolve_python_in_command(command)

        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "a", encoding="utf-8")
        log_handle.write(
            f"\n{'=' * 60}\n[{datetime.now().isoformat()}] Starting: {command}\n{'=' * 60}\n"
        )
        log_handle.flush()

        # Build env with integration bridge vars if project provided
        env = os.environ.copy()
        env.update(self._certifi_ssl_env())
        if extra_env:
            env.update(extra_env)
        if project and project.bridge_token:
            bridge_port = int(os.environ.get("BROWSER_PORT", "7926"))
            env["CRAFTBOT_BRIDGE_URL"] = f"http://localhost:{bridge_port}"
            env["CRAFTBOT_BRIDGE_TOKEN"] = project.bridge_token
            logger.info(
                f"[LIVING_UI] Bridge env injected: URL=http://localhost:{bridge_port}, token={project.bridge_token[:8]}..."
            )
        else:
            logger.warning(
                f"[LIVING_UI] No bridge token for process: project={'yes' if project else 'no'}, token={'yes' if project and project.bridge_token else 'no'}"
            )
        try:
            if os.name == "nt":
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    env=env,
                    stdout=log_handle,
                    stderr=log_handle,
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
            else:
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    env=env,
                    stdout=log_handle,
                    stderr=log_handle,
                    shell=True,
                )
        except Exception:
            log_handle.close()
            raise
        # Track the handle on the process so _terminate_process / stop paths
        # can close it — otherwise handles leak across relaunches.
        process._craftbot_log_handle = log_handle
        return process

    @staticmethod
    def _dedupe_errors(errors: List[str]) -> List[str]:
        """Drop repeats that are byte-identical after stripping a leading
        [step] tag and collapsing whitespace. Order preserved; first wins."""
        seen = set()
        out: List[str] = []
        for err in errors:
            normalized = re.sub(r"^\[[^\]]*\]\s*", "", err)
            normalized = " ".join(normalized.split())
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(err)
        return out

    @staticmethod
    def _cleanup_project_logs(project_path: Path) -> None:
        """Clean up old log files so each launch/restart starts fresh."""
        legacy_log = project_path / "logs" / "frontend_output.log"
        try:
            if legacy_log.exists():
                legacy_log.unlink()
        except Exception:
            pass
        # Clean up old session logs — keep only the 5 most recent
        frontend_logs_dir = project_path / "logs"
        if frontend_logs_dir.exists():
            session_logs = sorted(
                frontend_logs_dir.glob("frontend_*.log"), reverse=True
            )
            for old_log in session_logs[5:]:
                try:
                    old_log.unlink()
                except Exception:
                    pass

        logger.debug("[LIVING_UI:PIPELINE] Cleaned up old log files")

    @staticmethod
    def _create_frontend_log(project_path: Path) -> Path:
        """Create a timestamped frontend log file path."""
        logs_dir = project_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"frontend_{timestamp}.log"

    @staticmethod
    def _has_files_changed(project_path: Path) -> bool:
        """Check if any source files changed since last successful launch."""
        last_launch_file = project_path / ".last_launch"
        if not last_launch_file.exists():
            return True  # No record = assume changed

        try:
            last_launch_time = last_launch_file.stat().st_mtime
        except Exception:
            return True

        source_extensions = {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
            ".html",
            ".css",
            ".md",
        }
        skip_dirs = {"node_modules", "__pycache__", "dist", "logs", ".git"}

        for filepath in project_path.rglob("*"):
            if filepath.is_file() and filepath.suffix in source_extensions:
                if any(skip in filepath.parts for skip in skip_dirs):
                    continue
                if filepath.stat().st_mtime > last_launch_time:
                    return True
        return False

    # Matches the CraftBot theme-sync block in a project's index.html: the
    # optional marker comment plus the ONE <script> that mentions
    # 'craftbot-theme'. Older apps carry pre-style versions of this script
    # (no data-style handling at all), so a line-level patch can't heal
    # them — the whole block is replaced from the template.
    _THEME_SYNC_BLOCK_RE = re.compile(
        r"(?:<!--\s*CraftBot theme sync.*?-->\s*)?"
        r"<script>(?:(?!</script>).)*craftbot-theme(?:(?!</script>).)*</script>",
        re.S,
    )

    def _sync_style_packs(self, project_path: Path) -> None:
        """Self-healing for older apps: style packs are PROJECT-resident —
        the CSS lives in the app's themes.css and the <html data-style>
        attribute is set by the app's own index.html sync script. An app
        copied from the template before a pack existed has neither (the
        oldest scripts ignore the style field entirely), so the host sets a
        theme and nothing changes. Both artifacts are SYSTEM-managed
        (agents never edit them), so overwriting from the current template
        is safe by contract. Runs before the frontend build so the rebuild
        bundles the new CSS. Fail-silent: a launch must never break over
        cosmetics.
        """
        try:
            styles_dir = project_path / "frontend" / "styles"
            if not styles_dir.exists():
                return  # not a template-structured (native) project
            src = self.template_path / "frontend" / "styles" / "themes.css"
            if src.exists():
                dst = styles_dir / "themes.css"
                content = src.read_text(encoding="utf-8")
                if not dst.exists() or dst.read_text(encoding="utf-8") != content:
                    dst.write_text(content, encoding="utf-8")
                    logger.info(
                        f"[LIVING_UI] Synced style packs into {project_path.name}"
                    )
            # Vite only bundles CSS that something imports, and the
            # themes.css import in main.tsx postdates the oldest apps —
            # without it the synced packs are dead CSS on disk. main.tsx is
            # SYSTEM-managed (agents never touch it) and every era imports
            # global.css, so a one-line additive insert is era-safe.
            main_tsx = project_path / "frontend" / "main.tsx"
            if main_tsx.exists():
                main_src = main_tsx.read_text(encoding="utf-8")
                if (
                    "styles/themes.css" not in main_src
                    and "import './styles/global.css'" in main_src
                ):
                    main_tsx.write_text(
                        main_src.replace(
                            "import './styles/global.css'",
                            "import './styles/global.css'\n"
                            "import './styles/themes.css'",
                            1,
                        ),
                        encoding="utf-8",
                    )
                    logger.info(
                        f"[LIVING_UI] Injected themes.css import into "
                        f"{project_path.name}"
                    )
            # Replace the project's ENTIRE theme-sync script with the
            # template's current one (mode + style + palette handling).
            tpl_index = self.template_path / "index.html"
            prj_index = project_path / "index.html"
            if tpl_index.exists() and prj_index.exists():
                tpl_block = self._THEME_SYNC_BLOCK_RE.search(
                    tpl_index.read_text(encoding="utf-8")
                )
                if tpl_block:
                    current = prj_index.read_text(encoding="utf-8")
                    updated = self._THEME_SYNC_BLOCK_RE.sub(
                        lambda _m: tpl_block.group(0), current, count=1
                    )
                    if updated == current and "craftbot-theme" not in current:
                        # No sync script at all — inject before </body>.
                        updated = current.replace(
                            "</body>", tpl_block.group(0) + "\n  </body>", 1
                        )
                    if updated != current:
                        prj_index.write_text(updated, encoding="utf-8")
                        logger.info(
                            f"[LIVING_UI] Synced theme-sync script into "
                            f"{project_path.name}"
                        )
        except Exception as e:
            logger.debug(f"[LIVING_UI] style pack sync skipped: {e}")

    @staticmethod
    def _patch_theme_listener(project_path: Path) -> None:
        """Inject CraftBot theme-sync listener into index.html if not already present."""
        index_html = project_path / "index.html"
        if not index_html.exists():
            return
        try:
            content = index_html.read_text(encoding="utf-8")
            if "craftbot-theme-request" in content:
                return  # Already patched
            snippet = (
                "\n    <!-- CraftBot theme sync -->\n"
                "    <script>\n"
                "    (function(){\n"
                "      function applyTheme(t,v){\n"
                '        document.documentElement.setAttribute("data-theme",t||"dark");\n'
                '        if(v&&typeof v==="object"){\n'
                '          var el=document.getElementById("craftbot-theme-vars")||document.createElement("style");\n'
                '          el.id="craftbot-theme-vars";\n'
                '          el.textContent=":root{"+Object.keys(v).map(function(k){return k+":"+v[k];}).join(";")+"}";'
                '\n          if(!document.getElementById("craftbot-theme-vars"))document.head.appendChild(el);\n'
                "        }\n"
                "      }\n"
                '      window.addEventListener("load",function(){\n'
                '        try{window.parent.postMessage({type:"craftbot-theme-request"},"*");}catch(e){}\n'
                "      });\n"
                '      window.addEventListener("message",function(e){\n'
                '        if(e.data&&e.data.type==="craftbot-theme")applyTheme(e.data.theme,e.data.cssVars);\n'
                "      });\n"
                '      var _t="dark";try{var _s=window.parent.localStorage.getItem("craftbot-theme");'
                'if(_s==="light"||_s==="dark")_t=_s;}catch(e){}document.documentElement.setAttribute("data-theme",_t);\n'
                "    })();\n"
                "    </script>\n"
            )
            patched = content.replace("</body>", snippet + "</body>", 1)
            index_html.write_text(patched, encoding="utf-8")
            logger.info(f"[LIVING_UI] Patched theme listener into {index_html}")
        except Exception as e:
            logger.warning(f"[LIVING_UI] Could not patch index.html: {e}")

    async def _dirty_db_rows(
        self, backend_url: str, project_path: Path
    ) -> Dict[str, int]:
        """Entity tables that still contain rows (creation-phase guard).

        Reads the sqlite file directly (read-only) — no HTTP, no shape
        assumptions. Empty dict = clean. Fail-open on any error (a broken
        check must not block a launch; the wipe already ran)."""
        try:
            schema_file = Path(project_path) / "config" / "schema.json"
            db_path = Path(project_path) / "pb_data" / "data.db"
            if not db_path.exists():
                db_path = Path(project_path) / "backend" / "living_ui.db"  # legacy
            if not schema_file.exists() or not db_path.exists():
                return {}
            import sqlite3 as _sqlite3

            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            # PocketBase table names are EXACTLY the collection names.
            cols = schema.get("collections") if isinstance(schema, dict) else schema
            tables = [
                c["name"] for c in (cols or []) if isinstance(c, dict) and c.get("name")
            ]

            def _count() -> Dict[str, int]:
                found: Dict[str, int] = {}
                conn = _sqlite3.connect(
                    f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0
                )
                try:
                    existing = {
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    for table in tables:
                        if table not in existing:
                            continue
                        n = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[
                            0
                        ]
                        if n:
                            found[table] = n
                finally:
                    conn.close()
                return found

            return await asyncio.to_thread(_count)
        except Exception as e:
            logger.debug(f"[LIVING_UI:PIPELINE] dirty-db check skipped: {e}")
            return {}

    def _source_signature(project_path: Path) -> str:
        """Cheap fingerprint of the project's editable source tree.

        (path, mtime_ns, size) over backend/frontend/config, skipping
        node_modules/__pycache__/logs. Two identical signatures mean no
        agent edit happened between validation attempts — re-validating
        cannot produce a different outcome.
        """
        import hashlib

        h = hashlib.sha256()
        # `pb_hooks` is the PocketBase project's BACKEND (custom
        # routes). It was missing here (a pre-R20 list), so a repair that
        # only edited pb_hooks read as "no change" → the loop falsely
        # reported validation.unchanged and escalated to the user after ~2
        # rounds despite real backend fixes. `backend` stays for legacy
        # FastAPI projects.
        skip_dirs = {"node_modules", "__pycache__", "logs"}
        for sub in ("pb_hooks", "backend", "frontend", "config"):
            base = project_path / sub
            if not base.is_dir():
                continue
            # os.walk with in-place dirs pruning: rglob would descend into
            # node_modules (tens of thousands of files) only to filter them
            # afterwards — per validate, on the pipeline's hot path.
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
                for fname in sorted(filenames):
                    p = Path(dirpath) / fname
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        return h.hexdigest()

    @staticmethod
    def _save_launch_timestamp(project_path: Path) -> None:
        """Save current time as last successful launch timestamp."""
        last_launch_file = project_path / ".last_launch"
        try:
            last_launch_file.write_text(datetime.now().isoformat(), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _read_log_tail(log_file: Path, chars: int = 1000) -> str:
        """Read the last N characters of a log file."""
        try:
            content = log_file.read_text(encoding="utf-8")
            return content[-chars:] if len(content) > chars else content
        except Exception:
            return "(could not read log)"

    async def launch_backend(self, project_id: str) -> bool:
        """
        Launch the backend (PocketBase) server for a Living UI project.

        PocketBase holds all state (pb_data/, SQLite) and serves CRUD +
        the app's custom pb_hooks routes. Launched before the frontend.

        Args:
            project_id: Project ID to launch backend for

        Returns:
            True if backend launch was successful
        """
        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return False

        project_path = Path(project.path)

        if (
            not (project_path / "pb_hooks").exists()
            and (project_path / "backend").exists()
        ):
            # Pre-Round-20 project (FastAPI backend) — leave it alone.
            logger.warning(
                f"[LIVING_UI] {project_id} is a legacy FastAPI project; "
                "PocketBase launch skipped"
            )
            return True

        # If backend port is occupied, allocate a new one instead of killing
        backend_port = project.backend_port
        if backend_port and self._is_port_in_use(backend_port):
            logger.info(
                f"[LIVING_UI] Port {backend_port} occupied, allocating a new port..."
            )
            self._release_port(backend_port)
            backend_port = self._allocate_port()
            project.backend_port = backend_port
            logger.info(f"[LIVING_UI] Allocated new backend port: {backend_port}")

        # Allocate port if needed
        if not backend_port:
            backend_port = self._allocate_port()
            project.backend_port = backend_port

        try:
            # Start the PocketBase backend (the data layer is
            # PocketBase — single pinned binary, pb_data/ + pb_hooks/).
            logger.info(
                f"[LIVING_UI] Starting PocketBase for {project_id} on port {backend_port}"
            )
            from app.living_ui import pocketbase_runtime as pbrt

            logs_dir = project_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            subprocess_log = logs_dir / "backend_output.log"
            subprocess_log_handle = open(subprocess_log, "a", encoding="utf-8")
            subprocess_log_handle.write(
                f"\n{'=' * 60}\n[{datetime.now().isoformat()}] Starting PocketBase on port {backend_port}\n{'=' * 60}\n"
            )
            subprocess_log_handle.flush()

            # Generate bridge token for integration proxy
            from uuid import uuid4

            bridge_token = str(uuid4())
            project.bridge_token = bridge_token

            # Build env with integration bridge vars (pb_hooks callLLM
            # reads CRAFTBOT_BRIDGE_URL via $os.getenv)
            bridge_port = int(os.environ.get("BROWSER_PORT", "7926"))
            backend_env = os.environ.copy()
            backend_env["CRAFTBOT_BRIDGE_URL"] = f"http://localhost:{bridge_port}"
            backend_env["CRAFTBOT_BRIDGE_TOKEN"] = bridge_token

            # Superuser MUST exist before serve — otherwise PocketBase
            # boots into its browser installer, which no user or agent
            # should ever see. Retry once, then fail the launch loudly.
            if not pbrt.bootstrap_superuser(project_path):
                if not pbrt.bootstrap_superuser(project_path):
                    logger.error(
                        f"[LIVING_UI] PocketBase superuser bootstrap failed "
                        f"twice for {project_id} — refusing to serve an "
                        "unprovisioned instance (browser installer)."
                    )
                    subprocess_log_handle.close()
                    return False
            backend_process = subprocess.Popen(
                pbrt.serve_command(project_path, backend_port),
                cwd=str(project_path),
                env=backend_env,
                stdout=subprocess_log_handle,
                stderr=subprocess_log_handle,
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )

            backend_process._craftbot_log_handle = subprocess_log_handle
            project.backend_process = backend_process

            # Wait for health check to pass (PB native health; the legacy
            # /health path is also served by pb_hooks/_craftbot.pb.js)
            health_url = f"http://localhost:{backend_port}/api/health"
            logger.info(
                f"[LIVING_UI] Waiting for backend health check at {health_url}..."
            )
            backend_ready = await self._wait_for_health_check(health_url, timeout=20)

            if not backend_ready:
                # Backend didn't start - read the subprocess log for diagnostics
                subprocess_log_handle.flush()
                try:
                    recent_output = subprocess_log.read_text(encoding="utf-8")[-1000:]
                except Exception:
                    recent_output = "(could not read subprocess log)"
                if backend_process.poll() is not None:
                    logger.error(
                        f"[LIVING_UI] Backend process exited with code {backend_process.returncode}. Log tail:\n{recent_output}"
                    )
                else:
                    logger.error(
                        f"[LIVING_UI] Backend not responding on port {backend_port}. Log tail:\n{recent_output}"
                    )
                    self._terminate_process(backend_process)
                project.backend_process = None
                subprocess_log_handle.close()
                return False

            project.backend_url = f"http://localhost:{backend_port}"
            # Import the declared collections (idempotent; deleteMissing
            # stays False so system collections survive) + regenerate the
            # typed frontend surface.
            import_err = await asyncio.to_thread(
                pbrt.import_collections, project_path, backend_port
            )
            if import_err:
                logger.error(f"[LIVING_UI] collections import: {import_err}")
            else:
                from .typegen import regenerate_types

                regenerate_types(project_path)
            logger.info(
                f"[LIVING_UI] PocketBase started successfully on port {backend_port}"
            )
            return True

        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to launch backend: {e}")
            return False

    async def stop_backend(self, project_id: str) -> bool:
        """
        Stop the backend server for a Living UI project.

        Args:
            project_id: Project ID to stop backend for

        Returns:
            True if stop was successful
        """
        project = self.projects.get(project_id)
        if not project:
            return False

        if project.backend_process:
            self._terminate_process(project.backend_process)
            project.backend_process = None

        # Also try to kill by port in case process reference is stale
        if project.backend_port and self._is_port_in_use(project.backend_port):
            self._kill_process_on_port(project.backend_port)

        project.backend_url = None
        logger.info(f"[LIVING_UI] Stopped backend for {project_id}")
        return True

    @staticmethod
    def _close_process_log(process: Optional[subprocess.Popen]) -> None:
        """Close the log file handle attached to a spawned process, if any.

        Long-lived server processes redirect stdout/stderr to a log handle we
        open at spawn time; without an explicit close, handles accumulate
        across watchdog relaunches and restarts.
        """
        handle = getattr(process, "_craftbot_log_handle", None) if process else None
        if handle:
            try:
                handle.close()
            except Exception:
                pass

    def _terminate_process(self, process: subprocess.Popen) -> None:
        """Terminate a subprocess, killing the entire process tree on Windows."""
        try:
            if os.name == "nt":
                # On Windows with shell=True, terminate() only kills cmd.exe,
                # not the child python/uvicorn. Kill the whole tree via taskkill.
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    capture_output=True,
                    shell=True,
                )
            else:
                process.terminate()
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, Exception):
            try:
                process.kill()
            except Exception:
                pass
        finally:
            self._close_process_log(process)

    def cleanup_on_startup(self) -> None:
        """
        Clean up orphan processes and folders on startup.

        This should be called after loading projects to:
        1. Kill any orphan Living UI server processes on tracked ports (frontend + backend)
        2. Delete project folders not tracked in the registry
        3. Reset all project statuses to 'stopped'

        Optimized to:
        - Only check ports that are tracked in projects (not all 100 ports)
        - Use a single netstat call to get all port info at once
        """
        logger.info("[LIVING_UI] Running startup cleanup...")

        # 1. Kill orphan processes - on both frontend and backend ports
        killed_count = 0
        tracked_ports = set()
        for p in self.projects.values():
            if p.port:
                tracked_ports.add(p.port)
            if p.backend_port:
                tracked_ports.add(p.backend_port)
            # Orphaned Live Construction dev server from a previous session
            if p.dev_port:
                tracked_ports.add(p.dev_port)
                p.dev_port = None
                p.dev_url = None

        if tracked_ports:
            # Get all port -> PID mappings with a single system call
            port_pids = self._get_pids_on_ports(tracked_ports)

            # Kill processes on tracked ports
            for port, pid in port_pids.items():
                if self._kill_process_by_pid(pid):
                    killed_count += 1
                    logger.info(f"[LIVING_UI] Killed process {pid} on port {port}")

        if killed_count > 0:
            logger.info(f"[LIVING_UI] Killed {killed_count} orphan process(es)")

        # 2. Clean up orphan project folders
        orphan_count = self._cleanup_orphan_folders()
        if orphan_count > 0:
            logger.info(f"[LIVING_UI] Removed {orphan_count} orphan folder(s)")

        # 3. Reset all project statuses to 'stopped' and clear process references
        for project in self.projects.values():
            if project.status == "running":
                project.status = "stopped"
                project.process = None
                project.backend_process = None
                project.url = None
                project.backend_url = None
        self._save_projects()

        logger.info("[LIVING_UI] Startup cleanup complete")

    def _cleanup_orphan_folders(self) -> int:
        """
        Delete project folders that are not tracked in the registry.

        Returns:
            Number of orphan folders deleted
        """
        if not self.living_ui_dir.exists():
            return 0

        tracked_paths = {Path(p.path) for p in self.projects.values()}
        orphan_count = 0

        for folder in self.living_ui_dir.iterdir():
            if folder.is_dir() and folder not in tracked_paths:
                try:
                    shutil.rmtree(folder)
                    logger.info(f"[LIVING_UI] Deleted orphan folder: {folder.name}")
                    orphan_count += 1
                except Exception as e:
                    logger.warning(
                        f"[LIVING_UI] Failed to delete orphan folder {folder}: {e}"
                    )

        return orphan_count

    def _generate_id(self) -> str:
        """Generate a unique project ID."""
        return str(uuid.uuid4())[:8]

    def _sanitize_name(self, name: str) -> str:
        """Sanitize project name for use in file paths."""
        # Replace spaces and special characters
        sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return sanitized.lower()

    async def create_project(
        self,
        name: str,
        description: str,
        features: List[str] = None,
        data_source: Optional[str] = None,
        theme: str = "system",
        icon: Optional[str] = None,
    ) -> LivingUIProject:
        """
        Create a new Living UI project from template.

        Args:
            name: Project name
            description: Project description
            features: List of requested features
            data_source: Optional API URL or data source description
            theme: UI theme (light, dark, system)
            icon: Display icon ("lucide:<Name>" or "file:<filename>")

        Returns:
            Created LivingUIProject instance
        """
        project_id = self._generate_id()
        sanitized_name = self._sanitize_name(name)
        project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

        # Allocate ports
        frontend_port = self._allocate_port()
        backend_port = self._allocate_port()

        # Copy template
        try:
            shutil.copytree(self.template_path, project_path)
            logger.info(f"[LIVING_UI] Copied template to {project_path}")
        except Exception as e:
            self._release_port(frontend_port)
            self._release_port(backend_port)
            raise RuntimeError(f"Failed to copy template: {e}")

        # Replace template placeholders (including ports for source code)
        self._replace_placeholders(
            project_path,
            {
                "{{PROJECT_ID}}": project_id,
                "{{PROJECT_NAME}}": name,
                "{{PROJECT_DESCRIPTION}}": description,
                "{{PORT}}": str(frontend_port),
                "{{BACKEND_PORT}}": str(backend_port),
                "{{THEME}}": theme,
                "{{CREATED_AT}}": datetime.now().isoformat(),
                "{{FEATURES}}": ", ".join(features or []),
            },
        )

        # Provision the PocketBase superuser AT BIRTH: every project's
        # pb_data ships with the local admin already created, so no serve
        # — platform-launched or manual — can ever hit PB's browser
        # installer. Fail-open (launch_backend bootstraps again anyway).
        try:
            from app.living_ui import pocketbase_runtime as pbrt

            if not pbrt.bootstrap_superuser(project_path):
                logger.warning(
                    f"[LIVING_UI] scaffold-time PocketBase bootstrap failed "
                    f"for {project_id} (will retry at launch)"
                )
        except Exception as e:
            logger.warning(f"[LIVING_UI] scaffold-time PB bootstrap skipped: {e}")

        # Create project instance
        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(project_path),
            status="created",
            port=frontend_port,
            backend_port=backend_port,
            features=features or [],
            theme=theme,
            icon=icon,
        )

        self.projects[project_id] = project
        self._save_projects()

        logger.info(f"[LIVING_UI] Created project: {name} ({project_id})")
        return project

    def create_placeholder_project(
        self, name: str, description: str = ""
    ) -> LivingUIProject:
        """Register a lightweight "creating" project so a tab/progress screen
        appears immediately, before the real import/install populates it.

        Used by the import (ZIP/GitHub) and marketplace flows so they behave
        like the form-create flow (which registers its project synchronously).
        The actual importer — import_project_zip / import_external_app /
        install_from_marketplace — must adopt this id (pass project_id=...) so
        it overwrites this entry instead of creating a second tab.

        Intentionally NOT persisted to disk: a placeholder that never gets
        adopted (e.g. the import task fails) is dropped on the next restart
        rather than leaving a broken "creating" tab behind. The adopting
        importer calls _save_projects() once it fills in the real fields.
        """
        project_id = self._generate_id()
        project = LivingUIProject(
            id=project_id,
            name=name or "Importing…",
            description=description,
            path="",  # filled in when the real import adopts this id
            status="creating",
        )
        self.projects[project_id] = project
        logger.info(
            f"[LIVING_UI] Registered placeholder project: {name} ({project_id})"
        )
        return project

    def _replace_placeholders(
        self, directory: Path, replacements: Dict[str, str]
    ) -> None:
        """Replace placeholders in all text files in directory."""
        text_extensions = {
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
            ".html",
            ".css",
            ".md",
            ".py",
            ".txt",
            ".env",
        }

        for filepath in directory.rglob("*"):
            if filepath.is_file() and filepath.suffix in text_extensions:
                try:
                    content = filepath.read_text(encoding="utf-8")
                    modified = False
                    for placeholder, value in replacements.items():
                        if placeholder in content:
                            content = content.replace(placeholder, value)
                            modified = True
                    if modified:
                        filepath.write_text(content, encoding="utf-8")
                except Exception as e:
                    logger.warning(f"[LIVING_UI] Failed to process {filepath}: {e}")

    async def install_from_marketplace(
        self,
        app_id: str,
        app_name: str,
        app_description: str,
        custom_fields: Optional[Dict[str, str]] = None,
        repo_url: str = "https://github.com/CraftOS-dev/living-ui-marketplace",
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Install a pre-built Living UI app from the marketplace.

        Downloads the app from a GitHub repo, sets up the project,
        and runs the launch pipeline.

        Args:
            app_id: The app folder name in the marketplace repo
            custom_fields: Optional dict of custom placeholder replacements (e.g., {"APP_TITLE": "My Board"})
            app_name: Display name for the project
            app_description: App description
            repo_url: GitHub repo URL

        Returns:
            Dict with status, project info, or error
        """
        import urllib.request
        import zipfile
        import io

        # Adopt a pre-created placeholder id when provided (so the tab spawned
        # at request time becomes this project), else allocate a fresh one.
        project_id = project_id or self._generate_id()
        sanitized_name = self._sanitize_name(app_name)
        project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

        try:
            # Download the repo as a zip
            # GitHub API: /{owner}/{repo}/zipball/main
            parts = repo_url.rstrip("/").split("/")
            owner = parts[-2]
            repo = parts[-1]
            zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"

            logger.info(f"[LIVING_UI:MARKETPLACE] Downloading {app_id} from {zip_url}")

            import ssl
            import certifi

            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(zip_url, headers={"User-Agent": "CraftBot"})
            response = urllib.request.urlopen(req, timeout=60, context=ssl_ctx)
            zip_data = response.read()

            # Extract just the app folder from the zip
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                # GitHub zips have a root folder like "repo-main/"
                root_prefix = None
                app_prefix = None

                for name in zf.namelist():
                    if root_prefix is None:
                        root_prefix = name.split("/")[0] + "/"
                    # Look for the app folder: root/{app_id}/
                    if f"/{app_id}/" in name:
                        if app_prefix is None:
                            # Find the prefix up to and including the app folder
                            idx = name.index(f"{app_id}/")
                            app_prefix = name[: idx + len(app_id) + 1]
                        break

                if not app_prefix:
                    return {
                        "status": "error",
                        "error": f"App '{app_id}' not found in marketplace repo",
                    }

                # Extract app files to project path
                project_path.mkdir(parents=True, exist_ok=True)
                project_root = project_path.resolve()
                for member in zf.namelist():
                    if member.startswith(app_prefix) and not member.endswith("/"):
                        # Get the relative path within the app folder
                        rel_path = member[len(app_prefix) :]
                        if rel_path:
                            target = (project_path / rel_path).resolve()
                            # Zip-slip guard: refuse members that escape the
                            # project dir via ".." or absolute path segments.
                            try:
                                target.relative_to(project_root)
                            except ValueError:
                                logger.warning(
                                    f"[LIVING_UI:MARKETPLACE] Skipping unsafe zip member: {member}"
                                )
                                continue
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(target, "wb") as dst:
                                dst.write(src.read())

            logger.info(f"[LIVING_UI:MARKETPLACE] Extracted {app_id} to {project_path}")

            # Allocate ports
            frontend_port = self._allocate_port()
            backend_port = self._allocate_port()

            # Replace placeholders (marketplace apps use the same template placeholders)
            # Build replacements — system placeholders + custom fields
            replacements = {
                "{{PROJECT_ID}}": project_id,
                "{{PROJECT_NAME}}": app_name,
                "{{PROJECT_DESCRIPTION}}": app_description,
                "{{PORT}}": str(frontend_port),
                "{{BACKEND_PORT}}": str(backend_port),
                "{{THEME}}": "system",
                "{{CREATED_AT}}": datetime.now().isoformat(),
                "{{FEATURES}}": "",
            }
            # Add custom fields from marketplace template (e.g., APP_TITLE)
            if custom_fields:
                for key, value in custom_fields.items():
                    replacements[f"{{{{{key}}}}}"] = value

            self._replace_placeholders(project_path, replacements)

            # Create project instance
            project = LivingUIProject(
                id=project_id,
                name=app_name,
                description=app_description,
                path=str(project_path),
                status="created",
                port=frontend_port,
                backend_port=backend_port,
            )

            self.projects[project_id] = project
            self._save_projects()

            logger.info(
                f"[LIVING_UI:MARKETPLACE] Created project: {app_name} ({project_id})"
            )

            # Run the launch pipeline
            result = await self.launch_and_verify(project_id)

            if result["status"] == "success":
                return {
                    "status": "success",
                    "project": project.to_dict(),
                    "url": result.get("url"),
                    "backend_url": result.get("backend_url"),
                }
            else:
                return {
                    "status": "error",
                    "error": f"Launch failed at {result.get('step', 'unknown')}: {'; '.join(result.get('errors', [])[:3])}",
                    "project": project.to_dict(),
                }

        except urllib.error.URLError as e:
            logger.error(f"[LIVING_UI:MARKETPLACE] Download failed: {e}")
            return {
                "status": "error",
                "error": f"Failed to download from marketplace: {e}",
            }
        except Exception as e:
            logger.error(f"[LIVING_UI:MARKETPLACE] Install failed: {e}")
            # Clean up on failure
            if project_path.exists():
                try:
                    shutil.rmtree(project_path)
                except Exception:
                    pass
            return {"status": "error", "error": f"Installation failed: {e}"}

    def update_project_status(
        self, project_id: str, status: str, error: Optional[str] = None
    ) -> None:
        """Update project status."""
        if project_id in self.projects:
            self.projects[project_id].status = status
            if error:
                self.projects[project_id].error = error
            self._save_projects()

    # ────────────────────────────────────────────────────────────────────
    # Design review (Live Construction View feeds this)
    #
    def is_validated(self, project_id: str) -> bool:
        """True when the full launch pipeline has passed for this project and
        nothing has invalidated the pass since (code write, failed attempt,
        restart). Gates living_ui_notify_ready."""
        project = self.projects.get(project_id)
        return bool(project and project.validation_passed_at)

    def invalidate_validation(self, project_id: str) -> None:
        """Clear a project's validation pass. Called when project code
        changes after a pass — the changed code has not been validated."""
        project = self.projects.get(project_id)
        if project and project.validation_passed_at:
            project.validation_passed_at = None
            logger.info(
                f"[LIVING_UI] Validation invalidated for {project_id} (code changed)"
            )

    def set_project_ui_theme(self, project_id: str, theme: Dict[str, Any]) -> bool:
        """Persist the per-project display theme chosen in the UI.

        Expects {"themeId": str, "customColors": {...}?}. Returns False for an
        unknown project or malformed payload.
        """
        project = self.projects.get(project_id)
        if not project or not isinstance(theme, dict):
            return False
        theme_id = theme.get("themeId")
        if not isinstance(theme_id, str) or not theme_id:
            return False
        stored: Dict[str, Any] = {"themeId": theme_id}
        custom = theme.get("customColors")
        if isinstance(custom, dict):
            stored["customColors"] = {
                k: v for k, v in custom.items() if isinstance(v, str)
            }
        project.ui_theme = stored
        self._save_projects()
        return True

    def get_project_by_task_id(self, task_id: str) -> Optional["LivingUIProject"]:
        """Return the Living UI project linked to a given task_id, or None."""
        if not task_id:
            return None
        for project in self.projects.values():
            if project.task_id == task_id:
                return project
        return None

    async def create_development_task(self, project_id: str) -> Optional[str]:
        """
        Create a task for the agent to develop a Living UI and fire the trigger.

        This creates the task and immediately fires a trigger to start execution.
        The pattern follows how memory processing and scheduled tasks work.

        Args:
            project_id: The Living UI project ID to develop

        Returns:
            The task ID if successful, None otherwise
        """
        from app.trigger import Trigger

        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return None

        if not self._task_manager:
            logger.error("[LIVING_UI] Task manager not bound")
            return None

        if not self._trigger_queue:
            logger.error("[LIVING_UI] Trigger queue not bound")
            return None

        # Build the task instruction. The requirements document is the
        # complete specification: the creation wizard writes it to
        # reference/requirements.md (synthesized from the user's config +
        # interview BEFORE the task exists). Projects created without the
        # wizard (living_ui_scaffold from chat) specify via description +
        # features instead.
        from agent_core.core.prompts.application import LIVING_UI_TASK_INSTRUCTION

        reference_dir = Path(project.path) / "reference"
        requirements_file = reference_dir / "requirements.md"
        if requirements_file.exists():
            requirements = requirements_file.read_text(
                encoding="utf-8", errors="replace"
            )
        else:
            features_str = (
                ", ".join(project.features) if project.features else "None specified"
            )
            requirements = (
                f"{project.description}\n\nRequested features: {features_str}"
            )

        reference_files = []
        if reference_dir.is_dir():
            reference_files = sorted(
                f.name
                for f in reference_dir.iterdir()
                if f.is_file() and f.name != "requirements.md"
            )
        reference_files_str = (
            "\n".join(f"- {project.path}/reference/{name}" for name in reference_files)
            if reference_files
            else "None"
        )

        task_instruction = LIVING_UI_TASK_INSTRUCTION.format(
            project_id=project.id,
            project_name=project.name,
            requirements=requirements,
            reference_files=reference_files_str,
            theme=project.theme,
            project_path=project.path,
        )

        try:
            # Create the task (synchronous method)
            # Include living_ui action set so agent can call living_ui_notify_ready
            task_id = self._task_manager.create_task(
                task_name=f"Create Living UI: {project.name}",
                task_instruction=task_instruction,
                mode="complex",
                action_sets=["file_operations", "code_execution", "living_ui", "core"],
                # Sub-workflow: purpose-built system prompt replaces the
                # general agent's (skills stay on disk as reference material).
                workflow_id="living_ui_development",
            )

            # Associate task with project (the ownership funnel; fresh
            # scaffold → state is already clean, no reset needed)
            await self.ensure_project_owner(project_id, task_id, reset_state=False)

            # Update project status
            self.update_project_status(project_id, "creating")

            # Create and fire the trigger to start execution
            if self._trigger_service is not None:
                from app.triggers import TriggerSource, TriggerSpec

                await self._trigger_service.emit(
                    TriggerSpec(
                        source=TriggerSource.LIVING_UI_DEV,
                        description=f"[Living UI] Create: {project.name}",
                        # Must BEAT running tasks' continuation triggers
                        # (priority 7): the queue serves ready triggers
                        # lowest-priority-number first, and 50 starved a
                        # new creation task forever while restored tasks
                        # kept the consumer busy.
                        priority=5,
                        session_id=task_id,
                        payload={
                            "type": "living_ui_development",
                            "project_id": project_id,
                        },
                    )
                )
            else:
                trigger = Trigger(
                    fire_at=time.time(),
                    priority=5,  # beat continuation triggers (see above)
                    next_action_description=f"[Living UI] Create: {project.name}",
                    session_id=task_id,
                    payload={
                        "type": "living_ui_development",
                        "project_id": project_id,
                    },
                )
                await self._trigger_queue.put(trigger)

            logger.info(
                f"[LIVING_UI] Created task {task_id} and fired trigger for project {project_id}"
            )
            return task_id

        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to create development task: {e}")
            self.update_project_status(project_id, "error", str(e))
            return None

    async def launch_project(self, project_id: str) -> bool:
        """
        Launch a Living UI project.

        Thin wrapper around launch_and_verify() that returns bool for
        backwards compatibility (watchdog, auto_launch_projects, restart).
        Includes stale status detection.
        """
        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return False

        if project.status == "running":
            # Verify processes are actually alive before trusting the stored status
            actually_alive = True

            if project.process is not None and project.process.poll() is not None:
                logger.warning(
                    f"[LIVING_UI] Frontend process dead for {project_id} (stale status)"
                )
                self._close_process_log(project.process)
                project.process = None
                actually_alive = False

            if (
                project.backend_process is not None
                and project.backend_process.poll() is not None
            ):
                logger.warning(
                    f"[LIVING_UI] Backend process dead for {project_id} (stale status)"
                )
                self._close_process_log(project.backend_process)
                project.backend_process = None
                actually_alive = False

            if (
                actually_alive
                and project.port
                and not self._is_port_in_use(project.port)
            ):
                logger.warning(
                    f"[LIVING_UI] Frontend port {project.port} not responding for {project_id}"
                )
                actually_alive = False

            if actually_alive:
                logger.info(f"[LIVING_UI] Project already running: {project_id}")
                return True

            # Status was stale — reset and fall through to full launch
            logger.info(
                f"[LIVING_UI] Project {project_id} status was stale, relaunching..."
            )
            project.status = "stopped"
            project.url = None
            project.backend_url = None

        result = await self.launch_and_verify(project_id)
        return result["status"] == "success"

    # ------------------------------------------------------------------
    # Integration bridge helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # External app support
    # ------------------------------------------------------------------

    async def _launch_single_process(
        self,
        project_id: str,
        project: "LivingUIProject",
        project_path: Path,
        app_cfg: dict,
    ) -> dict:
        """Launch a single-process app with sidecar proxy for logging/health."""
        # Allocate two ports: proxy (user-facing) and app (internal)
        proxy_port = project.port
        if not proxy_port:
            proxy_port = self._allocate_port()
            project.port = proxy_port

        app_port = project.backend_port
        if not app_port:
            app_port = self._allocate_port()
            project.backend_port = app_port

        if not await self._ensure_port_available(proxy_port):
            return {
                "status": "error",
                "step": "app.port",
                "errors": [f"Port {proxy_port} occupied"],
            }
        if not await self._ensure_port_available(app_port):
            return {
                "status": "error",
                "step": "app.port",
                "errors": [f"Port {app_port} occupied"],
            }

        cwd = project_path / app_cfg.get("cwd", ".")

        # Install step (optional)
        install_cmd = app_cfg.get("install", "")
        if install_cmd:
            logger.info(f"[LIVING_UI:PIPELINE] [app.install] Running: {install_cmd}")
            result = await self._run_pipeline_command(cwd, install_cmd, "app.install")
            if result["status"] == "error":
                return result

        # Start the app on the internal port
        start_cmd = app_cfg.get("start", "")
        if not start_cmd:
            return {
                "status": "error",
                "step": "app.start",
                "errors": ["No start command in manifest"],
            }

        logs_dir = project_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "app_output.log"

        # Build extra env vars — use app_port for the app itself
        extra_env = {}
        for k, v in app_cfg.get("env", {}).items():
            extra_env[k] = (
                str(v)
                .replace("{{PORT}}", str(app_port))
                .replace("{{BACKEND_PORT}}", str(app_port))
            )
        # Always override PORT with the internal app port — manifest may have a stale hardcoded value
        extra_env["PORT"] = str(app_port)

        # Replace port placeholders in start command with internal app port
        start_cmd = start_cmd.replace("{{PORT}}", str(app_port)).replace(
            "{{BACKEND_PORT}}", str(app_port)
        )

        # Generate bridge token
        from uuid import uuid4

        project.bridge_token = str(uuid4())

        app_process = self._start_process(
            cwd,
            start_cmd,
            log_file,
            port=app_port,
            project=project,
            extra_env=extra_env,
        )
        project.app_process = app_process
        logger.info(f"[LIVING_UI:PIPELINE] App starting on internal port {app_port}")

        # Health check on the app's internal port
        health_cfg = app_cfg.get("health", {})
        # Replace port placeholders in health URL with app_port
        if isinstance(health_cfg, dict) and "url" in health_cfg:
            health_cfg = dict(health_cfg)
            health_cfg["url"] = (
                health_cfg["url"]
                .replace("{{PORT}}", str(app_port))
                .replace("{{BACKEND_PORT}}", str(app_port))
            )
        elif isinstance(health_cfg, str):
            health_cfg = health_cfg.replace("{{PORT}}", str(app_port)).replace(
                "{{BACKEND_PORT}}", str(app_port)
            )

        healthy = await self._check_health_with_strategy(
            health_cfg, app_port, app_process
        )
        if not healthy:
            log_tail = self._read_log_tail(log_file, 1000)
            if app_process.poll() is not None:
                err = f"App process exited with code {app_process.returncode}"
                self._close_process_log(app_process)
            else:
                err = f"App not responding on port {app_port}"
                self._terminate_process(app_process)
            project.app_process = None
            return {"status": "error", "step": "app.health", "errors": [err, log_tail]}

        logger.info(f"[LIVING_UI:PIPELINE] App healthy on internal port {app_port}")

        # Start the sidecar proxy on the user-facing port
        sidecar_path = (
            Path(__file__).parent.parent / "data" / "living_ui_sidecar" / "proxy.py"
        )
        if sidecar_path.exists():
            sidecar_cmd = f'python "{sidecar_path}" --app-port {app_port} --proxy-port {proxy_port}'
            sidecar_log = logs_dir / "sidecar_output.log"
            sidecar_process = self._start_process(
                project_path, sidecar_cmd, sidecar_log, port=proxy_port, project=project
            )
            project.process = sidecar_process  # Store sidecar as frontend process (gets stopped with stop_project)
            logger.info(
                f"[LIVING_UI:PIPELINE] Sidecar proxy starting: port {proxy_port} → app port {app_port}"
            )

            # Wait for sidecar to be ready
            sidecar_healthy = await self._wait_for_health_check(
                f"http://localhost:{proxy_port}/health", timeout=15
            )
            if not sidecar_healthy:
                logger.warning(
                    f"[LIVING_UI:PIPELINE] Sidecar not responding, app still accessible directly on port {app_port}"
                )
                project.url = f"http://localhost:{app_port}"
            else:
                project.url = f"http://localhost:{proxy_port}"
                logger.info(f"[LIVING_UI:PIPELINE] Sidecar ready on port {proxy_port}")
        else:
            logger.warning(
                "[LIVING_UI:PIPELINE] Sidecar proxy not found, running app without proxy"
            )
            project.url = f"http://localhost:{app_port}"

        project.backend_url = f"http://localhost:{app_port}"

        # Import adoption gates (creation-time only): an imported app the
        # agent can't operate is a failed import. Existing projects
        # relaunch without re-gating.
        if project.status in ("creating", "created"):
            gate_errors = await asyncio.to_thread(
                self._check_external_adoption, project, project_path
            )
            if gate_errors:
                logger.error(
                    f"[LIVING_UI:PIPELINE] [import.adoption] "
                    f"{len(gate_errors)} gate failure(s) for {project_id}"
                )
                if project.process is not None:
                    self._terminate_process(project.process)
                    project.process = None
                self._terminate_process(app_process)
                project.app_process = None
                project.url = None
                project.backend_url = None
                return {
                    "status": "error",
                    "step": "import.adoption",
                    "errors": gate_errors,
                }

        project.status = "running"
        project.validation_passed_at = time.time()
        self._save_projects()

        logger.info(f"[LIVING_UI:PIPELINE] App ready: {project.url}")
        return {
            "status": "success",
            "url": project.url,
            "port": proxy_port,
        }

    def _check_external_adoption(
        self, project: "LivingUIProject", project_path: Path
    ) -> List[str]:
        """Creation-time contract for imported apps.

        The declared operations ARE an imported app's control surface — an
        undeclared capability doesn't exist for any future agent. This gate
        makes the importer skill's step 6 mechanical: no operations, no
        docs, or a failing safe op refuses the import. Runs with the app
        healthy so ops can be exercised for real.
        """
        from . import operations as ops_module
        from .ops_analyzer import check_manifest
        from .scheduler import execute_op

        errors: List[str] = []

        if not (project_path / "LIVING_UI.md").exists():
            errors.append(
                "LIVING_UI.md missing — document what the app does, its key "
                "files, configuration and endpoints (importer skill step 5)."
            )

        try:
            ops = ops_module.load_operations(project)
        except ops_module.OperationError as e:
            errors.append(f"config/operations.json is broken: {e}")
            return errors
        if not ops:
            errors.append(
                "config/operations.json declares no operations — declared "
                "ops ARE an imported app's control surface; without them no "
                "agent can ever operate it (importer skill step 6). Fix: "
                "livingui <project> ops-sync --write (if the app serves an "
                "OpenAPI spec) or declare http/shell ops by hand, then mark "
                'the read-only ones "safe": true.'
            )
            return errors

        findings = check_manifest(project_path, None)
        errors.extend(
            f"{f['message']} — fix: {f['fix']}"
            for f in findings
            if f["level"] == "error"
        )

        safe_ops = {
            name: op_def for name, op_def in ops.items() if op_def.get("safe") is True
        }
        if not safe_ops:
            errors.append(
                'no operation is marked "safe": true — mark the read-only '
                "ops safe so validation can prove the control surface "
                "actually works (a status/list/read op always qualifies; "
                "never mark ops with side effects)."
            )
        for name, op_def in safe_ops.items():
            try:
                ok, summary = execute_op(project, name, op_def)
            except Exception as e:
                ok, summary = False, str(e)
            if not ok:
                errors.append(
                    f'safe op "{name}" failed end-to-end: {summary} — every '
                    "op marked safe must work against the running app "
                    "(defaults must satisfy its params)."
                )
        return errors

    @staticmethod
    def _append_node_args(command: str, extra_args: str) -> str:
        """Append CLI args to an npm/pnpm/yarn run command using `--`, or to a direct binary call."""
        if re.match(r"^\s*(?:npm|pnpm|yarn)\s+run\s+\S+", command):
            return (
                f"{command} {extra_args}"
                if " -- " in command
                else f"{command} -- {extra_args}"
            )
        return f"{command} {extra_args}"

    def _normalize_node_start_command(
        self, project_path: Path, start_command: str, env: Dict[str, str]
    ) -> Tuple[str, Dict[str, str]]:
        """
        Adjust an imported Node.js project's start command + env so it embeds cleanly
        in CraftBot's iframe:
          - bind to the allocated PORT (config-file ports often override env vars)
          - suppress system-browser auto-open (Vite/CRA's default behavior)

        Returns (start_command, env) — possibly modified. Falls back to the inputs
        on any parse error.
        """
        new_env = dict(env) if env else {}
        new_start = start_command

        pkg_json_path = project_path / "package.json"
        if not pkg_json_path.exists():
            return new_start, new_env

        try:
            pkg = json.loads(pkg_json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(
                f"[LIVING_UI] Could not parse {pkg_json_path}, skipping start-command normalization: {e}"
            )
            return new_start, new_env

        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        scripts = pkg.get("scripts", {})

        # If start_command is `npm/pnpm/yarn run X`, look up what X actually invokes
        underlying = start_command
        run_match = re.match(r"^\s*(?:npm|pnpm|yarn)\s+run\s+(\S+)", start_command)
        if run_match:
            underlying = scripts.get(run_match.group(1), "")

        def uses(name: str) -> bool:
            return name in deps or bool(
                re.search(rf"\b{re.escape(name)}\b", underlying)
            )

        already_has_port = bool(re.search(r"(--port|-p\s|--hostname|-H\s)", new_start))

        if uses("vite"):
            # Vite: CLI --port overrides server.port; BROWSER=none suppresses server.open auto-open
            new_env.setdefault("BROWSER", "none")
            if not already_has_port:
                new_start = self._append_node_args(
                    new_start, "--port {{PORT}} --host 127.0.0.1 --strictPort"
                )
        elif uses("next"):
            # Next.js: -p PORT, -H HOST. Doesn't auto-open by default.
            if not already_has_port:
                new_start = self._append_node_args(
                    new_start, "-p {{PORT}} -H 127.0.0.1"
                )
        elif uses("react-scripts") or uses("webpack-dev-server"):
            # CRA / webpack-dev-server: respect PORT env, BROWSER=none disables auto-open
            new_env.setdefault("BROWSER", "none")
        elif uses("@vue/cli-service") or uses("vue-cli-service"):
            new_env.setdefault("BROWSER", "none")
            if not already_has_port:
                new_start = self._append_node_args(
                    new_start, "--port {{PORT}} --host 127.0.0.1"
                )
        else:
            # Generic Node app — defensively suppress browser auto-open
            new_env.setdefault("BROWSER", "none")

        if new_start != start_command or new_env != env:
            logger.info(
                f"[LIVING_UI] Normalized Node start command: '{start_command}' -> '{new_start}' "
                f"(env additions: {set(new_env) - set(env or {})})"
            )

        return new_start, new_env

    async def import_external_app(
        self,
        name: str,
        description: str,
        source_path: str,
        app_runtime: str = "unknown",
        install_command: str = "",
        start_command: str = "",
        health_strategy: str = "tcp",
        health_url: str = "",
        port_env_var: str = "PORT",
        project_id: Optional[str] = None,
        data_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Import an external app as a Living UI project.

        ``data_config`` declares where the app stores its data so the CLI's
        data commands work on it: {"sqlite": "relative/path.db"} or
        {"url": "postgresql://..."}, optionally {"writable": true} (defaults
        to read-only — see data_plane.manifest_data_config).
        """
        # Adopt the placeholder id when provided so the tab spawned at request
        # time becomes this project instead of a second tab appearing.
        project_id = project_id or self._generate_id()
        sanitized_name = self._sanitize_name(name)
        project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

        try:
            # Copy source to workspace
            shutil.copytree(source_path, project_path)
            logger.info(f"[LIVING_UI] Copied external app to {project_path}")
        except Exception as e:
            return {"status": "error", "error": f"Failed to copy app: {e}"}

        # Allocate two ports: proxy (user-facing) and app (internal)
        proxy_port = self._allocate_port()
        app_port = self._allocate_port()

        # Create config directory and manifest
        config_dir = project_path / "config"
        config_dir.mkdir(exist_ok=True)
        logs_dir = project_path / "logs"
        logs_dir.mkdir(exist_ok=True)

        # Build health config — uses app_port (internal)
        health_cfg: Any = {"strategy": health_strategy}
        if health_strategy == "http_get":
            health_cfg["url"] = health_url or "http://localhost:{{PORT}}"
            health_cfg["timeout"] = 30

        env_dict: Dict[str, str] = {port_env_var: "{{PORT}}"} if port_env_var else {}

        # Auto-normalize Node.js dev-server start commands so the app binds to
        # CraftBot's allocated port and doesn't pop a system browser tab.
        if app_runtime == "node":
            start_command, env_dict = self._normalize_node_start_command(
                project_path, start_command, env_dict
            )

        # Generate manifest
        manifest = {
            "id": project_id,
            "name": name,
            "version": "1.0.0",
            "description": description,
            "projectType": "external",
            "appRuntime": app_runtime,
            "livingUIVersion": "1.0",
            "ports": {"frontend": proxy_port, "backend": app_port},
            "pipeline": {
                "app": {
                    "cwd": ".",
                    "install": install_command,
                    "start": start_command,
                    "env": env_dict,
                    "health": health_cfg,
                }
            },
            "agentAwareness": {"enabled": True, "observationMode": "sidecar"},
        }
        if isinstance(data_config, dict) and (
            data_config.get("sqlite") or data_config.get("url")
        ):
            manifest["data"] = data_config

        manifest_path = config_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(project_path),
            status="created",
            port=proxy_port,
            backend_port=app_port,
            project_type="external",
            app_runtime=app_runtime,
        )

        # Preserve the task link from an adopted placeholder so todo/question
        # broadcasts (keyed by task id) keep targeting this tab.
        existing = self.projects.get(project_id)
        if existing and existing.task_id:
            project.task_id = existing.task_id
        self.projects[project_id] = project
        self._save_projects()

        logger.info(f"[LIVING_UI] Imported external app: {name} ({project_id})")
        return {
            "status": "success",
            "project": project.to_dict(),
        }

    async def _check_health_with_strategy(
        self, health_cfg, port: int, process, timeout: int = 30
    ) -> bool:
        """Check health using configured strategy (http_get, tcp, process_alive, or URL string)."""
        if isinstance(health_cfg, str):
            # Backward compat: plain URL string
            return await self._wait_for_health_check(health_cfg, timeout=timeout)

        if not isinstance(health_cfg, dict):
            # No health config — just check if port is listening
            return await self._wait_for_server(port, timeout=timeout)

        strategy = health_cfg.get("strategy", "tcp")
        timeout = health_cfg.get("timeout", timeout)

        if strategy == "http_get":
            url = health_cfg.get("url", f"http://localhost:{port}")
            url = url.replace("{{PORT}}", str(port))
            return await self._wait_for_health_check(url, timeout=timeout)
        elif strategy == "tcp":
            return await self._wait_for_server(port, timeout=timeout)
        elif strategy == "process_alive":
            await asyncio.sleep(2)
            return process.poll() is None

        return await self._wait_for_server(port, timeout=timeout)

    def validate_bridge_token(self, token: str) -> Optional[str]:
        """
        Validate a bridge token and return the associated project ID.

        Returns:
            project_id if token is valid, None otherwise.
        """
        if not token:
            return None
        for project_id, project in self.projects.items():
            if project.bridge_token and hmac.compare_digest(
                project.bridge_token, token
            ):
                return project_id
        return None

    async def stop_all_projects(self) -> None:
        """Stop all running Living UI projects. Called during agent shutdown."""
        running = [pid for pid, p in self.projects.items() if p.status == "running"]
        if not running:
            return
        logger.info(f"[LIVING_UI] Shutting down {len(running)} running project(s)...")
        for project_id in running:
            try:
                await self.stop_project(project_id)
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Error stopping {project_id} during shutdown: {e}"
                )
        logger.info("[LIVING_UI] All projects stopped")

    async def stop_project(self, project_id: str, stop_backend: bool = True) -> bool:
        """
        Stop a running Living UI project (frontend and optionally backend).

        Serialized with launch_and_verify on the per-project lock so a stop
        can't tear down a launch pipeline mid-flight (it waits, then stops
        the fully started stack).

        Args:
            project_id: Project ID to stop
            stop_backend: Whether to also stop the backend (default: True)

        Returns:
            True if stop was successful
        """
        async with self._get_launch_lock(project_id):
            project = self.projects.get(project_id)
            if not project:
                logger.error(f"[LIVING_UI] Project not found: {project_id}")
                return False

            # Stop the Live Construction dev preview if one is running
            self.stop_dev_preview(project_id)

            # Stop app process (external/single-process apps)
            if project.app_process:
                self._terminate_process(project.app_process)
                project.app_process = None

            # Stop frontend process
            if project.process:
                self._terminate_process(project.process)
                project.process = None

            # Also kill by port in case process reference is stale
            if project.port and self._is_port_in_use(project.port):
                self._kill_process_on_port(project.port)

            project.url = None

            # Stop backend if requested
            if stop_backend:
                await self.stop_backend(project_id)

            project.status = "stopped"
            self._save_projects()

            logger.info(f"[LIVING_UI] Stopped project: {project_id}")
            return True

    async def delete_project(self, project_id: str) -> bool:
        """
        Delete a Living UI project.

        Args:
            project_id: Project ID to delete

        Returns:
            True if deletion was successful
        """
        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return False

        # Stop tunnel if active
        await self.stop_tunnel(project_id)

        # Stop the Live Construction dev preview and drop its event feed
        self.stop_dev_preview(project_id)
        try:
            from .construction_events import clear_buffer

            clear_buffer(project_id)
        except Exception:
            pass

        # Stop if running
        if project.status == "running":
            await self.stop_project(project_id)

        # Release ports
        if project.port:
            self._release_port(project.port)
        if project.backend_port:
            self._release_port(project.backend_port)

        # Delete project directory
        project_path = Path(project.path)
        if project_path.exists():
            try:
                shutil.rmtree(project_path)
            except Exception as e:
                logger.error(f"[LIVING_UI] Failed to delete project directory: {e}")

        # Delete the project's workspace uploads dir (legacy FastAPI-era
        # projects only; PocketBase apps store uploads in pb_data/storage)
        files_dir = self.workspace_root / "living_ui_files" / project_id
        if files_dir.exists():
            try:
                shutil.rmtree(files_dir)
            except Exception as e:
                logger.error(f"[LIVING_UI] Failed to delete files dir: {e}")

        # Remove from registry
        del self.projects[project_id]
        self._save_projects()

        logger.info(f"[LIVING_UI] Deleted project: {project_id}")
        return True

    def get_project(self, project_id: str) -> Optional[LivingUIProject]:
        """Get a project by ID."""
        return self.projects.get(project_id)

    def list_projects(self) -> List[LivingUIProject]:
        """List all projects."""
        return list(self.projects.values())

    def export_project_zip(self, project_id: str) -> Path:
        """Export a Living UI project as a ZIP file.

        Returns the path to the temporary ZIP file. Caller is responsible
        for cleanup after serving the file.
        """
        project = self.projects.get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        project_path = Path(project.path)
        if not project_path.exists():
            raise FileNotFoundError(f"Project directory not found: {project_path}")

        # Create a temp ZIP
        tmp = tempfile.NamedTemporaryFile(
            suffix=".zip",
            prefix=f"livingui_{self._sanitize_name(project.name)}_",
            delete=False,
        )
        tmp.close()
        zip_path = Path(tmp.name)

        skip_dirs = {
            "node_modules",
            "__pycache__",
            ".git",
            "dist",
            "build",
            "logs",
            ".venv",
            "venv",
        }
        skip_suffixes = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}
        skip_names = {
            ".env",
            ".env.local",
            ".env.production",
            ".last_launch",
            "credentials.json",
            "token.json",
            ".jwt_secret",
        }

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for f in files:
                    file_path = Path(root) / f
                    if (
                        file_path.suffix in skip_suffixes
                        or file_path.name in skip_names
                    ):
                        continue
                    zf.write(file_path, file_path.relative_to(project_path))

        logger.info(f"[LIVING_UI] Exported project '{project.name}' to {zip_path}")
        return zip_path

    async def import_project_zip(
        self, zip_path: str, name: str = "", project_id: Optional[str] = None
    ) -> "LivingUIProject":
        """Import a Living UI project from a ZIP file.

        The ZIP should contain a project directory structure with at least
        a config/manifest.json. Ports are allocated automatically. When
        project_id is provided, the import adopts that id (overwriting the
        placeholder tab spawned at request time) instead of generating a new
        one — preventing a duplicate tab.
        """
        zip_file = Path(zip_path)
        if not zip_file.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        # Extract to a temp directory first to inspect contents
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_file, "r") as zf:
                zf.extractall(tmp_dir)

            tmp_path = Path(tmp_dir)

            # Check if files are nested inside a single directory
            entries = list(tmp_path.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                extracted_root = entries[0]
            else:
                extracted_root = tmp_path

            # Read manifest if it exists
            manifest_path = extracted_root / "config" / "manifest.json"
            manifest = {}
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Determine project name
            if not name:
                name = manifest.get(
                    "name", zip_file.stem.replace("livingui_", "").rsplit("_", 1)[0]
                )
            if not name:
                name = "imported_project"

            # Adopt the placeholder id when provided, else generate a new one
            project_id = project_id or self._generate_id()
            sanitized_name = self._sanitize_name(name)
            project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

            # Copy to Living UI workspace
            shutil.copytree(extracted_root, project_path)

        # Allocate new ports
        frontend_port = self._allocate_port()
        backend_port = self._allocate_port()

        # Update manifest with new ID and ports
        manifest_path = project_path / "config" / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                old_port = str(
                    manifest.get("ports", {}).get(
                        "frontend", manifest.get("ports", {}).get("app", "")
                    )
                )
                old_backend = str(manifest.get("ports", {}).get("backend", ""))

                # Set the id field structurally — a whole-file text replace of
                # the old id can corrupt unrelated strings containing it.
                manifest["id"] = project_id
                port_map = {}
                if old_port and old_port != str(frontend_port):
                    port_map[old_port] = str(frontend_port)
                if old_backend and old_backend != str(backend_port):
                    port_map[old_backend] = str(backend_port)
                manifest = self._rewrite_ports_in_manifest(manifest, port_map)

                manifest_path.write_text(
                    json.dumps(manifest, indent=2), encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"[LIVING_UI] Could not update imported manifest: {e}")

        # Determine project type from manifest
        project_type = manifest.get("projectType", "native")
        app_runtime = manifest.get("appRuntime")
        description = manifest.get("description", "")

        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(project_path),
            status="ready",
            port=frontend_port,
            backend_port=backend_port,
            project_type=project_type,
            app_runtime=app_runtime,
        )

        # Preserve the task link from an adopted placeholder so todo/question
        # broadcasts (keyed by task id) keep targeting this tab.
        existing = self.projects.get(project_id)
        if existing and existing.task_id:
            project.task_id = existing.task_id
        self.projects[project_id] = project
        self._save_projects()

        logger.info(f"[LIVING_UI] Imported project '{name}' ({project_id}) from ZIP")
        return project

    async def auto_launch_projects(self, project_ids: List[str] = None) -> None:
        """Auto-launch projects on startup.

        If project_ids provided, launches those. Otherwise launches all
        projects with auto_launch=True.
        """
        if project_ids is None:
            # Launch all projects with auto_launch enabled
            project_ids = [p.id for p in self.projects.values() if p.auto_launch]

        for project_id in project_ids:
            project = self.projects.get(project_id)
            if project and project.status != "error":
                logger.info(
                    f"[LIVING_UI] Auto-launching: {project.name} ({project_id})"
                )
                project.status = "launching"
                self._save_projects()
                await self.launch_project(project_id)
