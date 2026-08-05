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
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
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

if TYPE_CHECKING:
    from app.session.session_manager import SessionManager
    from app.triggers import TriggerService


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
    error: Optional[str] = None
    # The project's dedicated agent session (persisted — every Living UI
    # project owns one standalone session for its builds, fixes and chat).
    session_id: Optional[str] = None
    auto_launch: bool = False  # Auto-launch on CraftBot startup
    log_cleanup: bool = True  # Clean logs on restart
    style_pack: str = ""  # wizard-chosen default style pack (host may override)
    # Display icon: "lucide:<name>" (picker) or "file:<relpath>" (uploaded,
    # doubles as the app's favicon).
    icon: Optional[str] = None
    # Server-side theme persistence: {"themeId": ..., "customColors": {...}}.
    # The host adopts this absent a local (per-browser) override.
    ui_theme: Optional[Dict[str, Any]] = None
    project_type: str = "native"  # 'native' or 'external'
    app_runtime: Optional[str] = (
        None  # 'go', 'node', 'python', 'rust', 'docker', 'static'
    )
    bridge_token: str = ""  # Ephemeral token for integration bridge (NOT serialized)
    tunnel_url: Optional[str] = None  # Public tunnel URL (NOT serialized)
    tunnel_process: Optional[subprocess.Popen] = None  # Tunnel process (NOT serialized)
    process: Optional[subprocess.Popen] = None  # Frontend process

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
            "error": self.error,
            "sessionId": self.session_id,
            "autoLaunch": self.auto_launch,
            "logCleanup": self.log_cleanup,
            "stylePack": self.style_pack,
            "icon": self.icon,
            "uiTheme": self.ui_theme,
            "projectType": self.project_type,
            "appRuntime": self.app_runtime,
            "livingUIVersion": 2,
            "tunnelUrl": self.tunnel_url,
        }


class LivingUIManager:
    """Manages Living UI project lifecycle."""

    def __init__(self, workspace_root: Path):
        """
        Initialize the Living UI Manager.

        Args:
            workspace_root: Root directory for Living UI projects
        """
        self.workspace_root = Path(workspace_root)
        self.projects: Dict[str, LivingUIProject] = {}
        self._next_port = 3100
        self._port_range = (3100, 3199)
        self._used_ports: set = set()
        self._projects_file = self.workspace_root / "living_ui_projects.json"

        # Session and trigger management (set via bind_session_manager)
        self._session_manager: Optional["SessionManager"] = None
        self._trigger_service: Optional["TriggerService"] = None

        # Watchdog state
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_running: bool = False

        # Ensure workspace directory exists
        self.living_ui_dir = self.workspace_root / "living_ui"
        self.living_ui_dir.mkdir(parents=True, exist_ok=True)

        # V2 runner (PocketBase single-process projects). New projects are V2;
        # V1 projects keep launching through the legacy pipeline.
        from app.config import PROJECT_ROOT
        from app.living_ui.v2_runner import V2Runner

        self.v2_runner = V2Runner(Path(PROJECT_ROOT) / "living-ui-v2")

        # Staging copies of delivered apps (modify-era data safety). Composed
        # like v2_runner: the supervisor never reaches back into the manager.
        from app.living_ui.staging import StagingSupervisor

        self.staging = StagingSupervisor(self.living_ui_dir, self.v2_runner)

        # Load existing projects
        self._load_projects()

    def bind_session_manager(
        self,
        session_manager: "SessionManager",
        trigger_service: "TriggerService",
    ) -> None:
        """
        Bind the session manager and trigger service for driving project sessions.

        Args:
            session_manager: SessionManager owning every project's session
            trigger_service: TriggerService for durable emits into a session
        """
        self._session_manager = session_manager
        self._trigger_service = trigger_service
        logger.info("[LIVING_UI] Session manager and trigger service bound")

        # Backfill: every project gets its dedicated chat session. Projects
        # created before the session-native redesign (or whose session was
        # lost) would otherwise have no sessionId, which hides their chat
        # panel in the UI.
        for project in list(self.projects.values()):
            try:
                self.ensure_project_session(project)
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Could not ensure session for project {project.id}: {e}"
                )

    def ensure_project_session(self, project: "LivingUIProject"):
        """Ensure the project's dedicated session exists and return it.

        NO Living UI skill is preloaded. Which skill a run needs depends on
        what is being ASKED, not on how the project arrived, so the agent picks
        one per run. Ordinary data work needs none at all — the interaction
        note carries the data model and the exact commands, and the app itself
        publishes how to drive it at GET /api/_a2app/describe, which is also
        the only copy an agent outside CraftBot can read.

        System-dispatched runs whose purpose IS known (crash repair, a
        development run) still declare their skill on the trigger via
        `workflow_skills`, loaded at run start and unloaded at run end —
        nothing has to infer what those runs are for.

        This used to preload living-ui-creator unconditionally, because
        originally every Living UI was one the agent had just written. Install
        and import were added later and reused this helper, so an app that
        arrived fully built still got a BUILD session — and the creator skill's
        "Finish: launch, then verify" recipe permanently in its prompt. The
        observed cost: asking a freshly installed habit tracker to record one
        habit relaunched the app twice, re-ran the validation gate, and drove a
        headless browser that clicked "Add habit" ten times against real data.
        """
        if not self._session_manager:
            return None

        session = (
            self._session_manager.get(project.session_id)
            if project.session_id
            else None
        )
        if session:
            return session

        from agent_core.core.session import SessionType

        session = self._session_manager.create_session(
            session_type=SessionType.LIVING_UI,
            title=project.name,
            session_id=project.session_id or f"lui_{project.id}",
            action_sets=["file_operations", "code_execution", "living_ui"],
            selected_skills=[],
            living_ui_project_id=project.id,
        )
        project.session_id = session.id
        self._save_projects()
        return session

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

        # Initial delay to let everything settle after startup
        await asyncio.sleep(10)

        while self._watchdog_running:
            try:
                await asyncio.sleep(self.WATCHDOG_INTERVAL)

                for project_id, project in list(self.projects.items()):
                    if project.status != "running":
                        # Clear retry count if project is no longer running
                        retry_counts.pop(project_id, None)
                        continue

                    frontend_dead = (
                        project.process is not None
                        and project.process.poll() is not None
                    )
                    if not frontend_dead and project.port:
                        if project.process is None and not self._is_port_in_use(
                            project.port
                        ):
                            frontend_dead = True

                    if not frontend_dead:
                        # Everything healthy, reset retry counter
                        if project_id in retry_counts:
                            logger.info(
                                f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) recovered"
                            )
                            retry_counts.pop(project_id)
                        continue

                    # Something is dead
                    retries = retry_counts.get(project_id, 0)
                    crash_target = ["app"]
                    crash_str = "app"

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

                    # Attempt restart — TYPE-dispatched: an external app must
                    # restart via its own pipeline, not as PocketBase (the
                    # orphaned V1 machinery's sharpest bug: this call used to
                    # hardcode v2_runner.start for every project type).
                    restart_ok = True
                    project.process = None
                    try:
                        if not project.bridge_token:
                            project.bridge_token = secrets.token_urlsafe(32)
                        if getattr(project, "project_type", "native") == "external":
                            _res = await self._run_external_pipeline(
                                Path(project.path),
                                project.port,
                                project.bridge_token,
                            )
                            restart_ok = _res.get("status") == "success"
                            if restart_ok:
                                project.process = _res.pop("process")
                        else:
                            project.process = await self.v2_runner.start(
                                Path(project.path),
                                project.port,
                                bridge_token=project.bridge_token,
                            )
                            restart_ok = await self.v2_runner.wait_healthy(project.port)
                    except Exception as e:
                        logger.error(
                            f"[LIVING_UI:WATCHDOG] restart failed for {project_id}: {e}"
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

        # Backend logs
        backend_subprocess_log = (
            project_path / "backend" / "logs" / "subprocess_output.log"
        )
        if backend_subprocess_log.exists():
            try:
                content = backend_subprocess_log.read_text(encoding="utf-8")
                log_snippets.append(
                    f"=== Backend subprocess log (last 1000 chars) ===\n{content[-1000:]}"
                )
            except Exception:
                pass

        # Backend app-level logs (most recent session)
        backend_logs_dir = project_path / "backend" / "logs"
        if backend_logs_dir.exists():
            session_logs = sorted(backend_logs_dir.glob("backend_*.log"), reverse=True)
            if session_logs:
                try:
                    content = session_logs[0].read_text(encoding="utf-8")
                    log_snippets.append(
                        f"=== Backend session log (last 1000 chars) ===\n{content[-1000:]}"
                    )
                except Exception:
                    pass

        # Health status
        health_status_file = project_path / "backend" / "logs" / "health_status.json"
        if health_status_file.exists():
            try:
                log_snippets.append(
                    f"=== Health status ===\n{health_status_file.read_text(encoding='utf-8')}"
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
        self._save_projects()

        # Wake the project's session to investigate and fix
        if not self._session_manager or not self._trigger_service:
            logger.error(
                "[LIVING_UI:WATCHDOG] Cannot escalate — session manager or trigger service not bound"
            )
            return

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
The app is a single PocketBase process; its log is {project.path}/logs/pocketbase.log
and frontend console errors are in {project.path}/logs/frontend_console.log.
Schema is in {project.path}/pb/pb_migrations/, hooks in {project.path}/pb/pb_hooks/,
UI in {project.path}/frontend/src/app/."""

        try:
            session = self.ensure_project_session(project)
            if not session:
                logger.error("[LIVING_UI:WATCHDOG] Could not resolve project session")
                return

            from app.triggers import TriggerSource, TriggerSpec

            await self._trigger_service.emit(
                TriggerSpec(
                    source=TriggerSource.LIVING_UI_CRASH_FIX,
                    description=task_instruction,
                    priority=30,  # Higher priority than normal creation runs
                    session_id=session.id,
                    payload={
                        "project_id": project_id,
                        # This run writes code, so it needs the build skill —
                        # loaded now, unloaded when the run ends.
                        "workflow_skills": ["living-ui-creator"],
                    },
                )
            )

            logger.info(
                f"[LIVING_UI:WATCHDOG] Queued crash-fix run in session {session.id} "
                f"for {project.name} ({project_id})"
            )
        except Exception as e:
            logger.error(f"[LIVING_UI:WATCHDOG] Failed to queue crash-fix run: {e}")

    def _load_projects(self) -> None:
        """Load projects from persistent storage."""
        if self._projects_file.exists():
            try:
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
                            session_id=project_data.get("sessionId"),
                            auto_launch=project_data.get("autoLaunch", False),
                            log_cleanup=project_data.get("logCleanup", True),
                            style_pack=project_data.get("stylePack", ""),
                            icon=project_data.get("icon"),
                            ui_theme=project_data.get("uiTheme"),
                            project_type=project_data.get("projectType", "native"),
                            app_runtime=project_data.get("appRuntime"),
                        )
                        # Check if saved tunnel URL is still reachable
                        saved_tunnel = project_data.get("tunnelUrl")
                        if saved_tunnel:
                            try:
                                import urllib.request

                                req = urllib.request.Request(
                                    saved_tunnel, method="HEAD"
                                )
                                urllib.request.urlopen(req, timeout=3)
                                project.tunnel_url = saved_tunnel
                                logger.info(
                                    f"[LIVING_UI] Tunnel still active for '{project.name}': {saved_tunnel}"
                                )
                            except Exception:
                                logger.info(
                                    f"[LIVING_UI] Tunnel expired for '{project.name}', clearing"
                                )
                                project.tunnel_url = None
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

    def _allocate_port(self) -> int:
        """Allocate a free port for a Living UI project.

        Checks both the internal tracking set AND actual system port usage
        to avoid conflicts with orphan processes.
        """
        for port in range(self._port_range[0], self._port_range[1] + 1):
            # Skip if tracked as used
            if port in self._used_ports:
                continue
            # Skip if actually in use on the system
            if self._is_port_in_use(port):
                logger.warning(
                    f"[LIVING_UI] Port {port} in use by external process, skipping"
                )
                continue
            self._used_ports.add(port)
            return port
        raise RuntimeError("No available ports in the Living UI port range")

    def _release_port(self, port: int) -> None:
        """Release a port back to the pool."""
        self._used_ports.discard(port)

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is actually in use on the system."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("localhost", port)) == 0

    def _get_pids_on_ports(
        self, ports_to_check: Optional[Set[int]] = None
    ) -> Dict[int, str]:
        """
        Get PIDs of processes listening on ports in the Living UI range.
        Uses a single system call for efficiency.

        Args:
            ports_to_check: Optional set of specific ports to check.
                           If None, checks all ports in the Living UI range.

        Returns:
            Dict mapping port numbers to PIDs
        """
        port_pids = {}

        if os.name == "nt":
            # Windows: run netstat once and parse all results
            try:
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                    shell=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
                for line in result.stdout.split("\n"):
                    if "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            addr = parts[1]
                            pid = parts[-1]
                            if ":" in addr:
                                try:
                                    port = int(addr.split(":")[-1])
                                    # Check if port is in range and optionally in the filter set
                                    if (
                                        self._port_range[0]
                                        <= port
                                        <= self._port_range[1]
                                    ):
                                        if (
                                            ports_to_check is None
                                            or port in ports_to_check
                                        ):
                                            port_pids[port] = pid
                                except ValueError:
                                    pass
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to get ports via netstat: {e}")
        else:
            # Linux/Mac: use lsof
            try:
                result = subprocess.run(
                    ["lsof", "-i", "-P", "-n"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.split("\n"):
                    if "LISTEN" in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            # PID is typically the second column
                            pid = parts[1]
                            # Find the port in the line
                            for part in parts:
                                if ":" in part:
                                    try:
                                        port = int(part.split(":")[-1])
                                        if (
                                            self._port_range[0]
                                            <= port
                                            <= self._port_range[1]
                                        ):
                                            if (
                                                ports_to_check is None
                                                or port in ports_to_check
                                            ):
                                                port_pids[port] = pid
                                                break
                                    except ValueError:
                                        pass
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to get ports via lsof: {e}")

        return port_pids

    def _kill_process_by_pid(self, pid: str) -> bool:
        """
        Kill a process by its PID.

        Args:
            pid: Process ID to kill

        Returns:
            True if process was killed, False otherwise
        """
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True,
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
            else:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            return True
        except Exception as e:
            logger.warning(f"[LIVING_UI] Failed to kill process {pid}: {e}")
            return False

    # ========================================================================
    # Manifest-driven launch pipeline
    # ========================================================================

    def _check_migration_divergence(self, project_path: Path) -> Optional[str]:
        """A migration recorded as applied in the LIVE pb_data but missing
        from pb_migrations/ bricks the app: at boot PocketBase re-runs the
        renamed file as "new", collides with the existing schema ("Collection
        name must be unique") and EXITS before serving /api/health. The gate
        cannot see this — it migrates a fresh temp DB, where a rename is
        harmless. Compare live history against the directory BEFORE boot.

        Observed live (weather_tracker_4453c73c): 1700000001_weather_schema.js
        renamed to ...0002 after a successful launch had applied it; every
        boot after that died with only "/api/health not responding" surfaced.
        """
        import sqlite3 as _sqlite3

        db = project_path / "pb" / "pb_data" / "data.db"
        mig_dir = project_path / "pb" / "pb_migrations"
        if not db.exists() or not mig_dir.is_dir():
            return None  # fresh project — nothing applied yet
        try:
            conn = _sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute("SELECT file FROM _migrations").fetchall()
            finally:
                conn.close()
        except Exception as e:
            # Fail OPEN: this check exists to explain a brick, never to cause
            # a launch failure of its own.
            logger.debug(f"[LIVING_UI:V2] migration-history check skipped: {e}")
            return None
        applied_js = {str(r[0]) for r in rows if str(r[0]).endswith(".js")}
        on_disk = {p.name for p in mig_dir.glob("*.js")}
        missing = sorted(applied_js - on_disk)
        if not missing:
            return None
        return (
            "Applied migration(s) missing from pb_migrations/: "
            + ", ".join(missing)
            + ". These already ran against this app's LIVE data — the filename "
            "is the identity. Renaming or deleting an applied migration makes "
            "every boot re-run its replacement into the existing schema, and "
            "PocketBase exits before serving anything. Restore the original "
            "filename(s) exactly as listed, and put schema changes in a NEW "
            "migration file."
        )

    async def _run_launch_pipeline(
        self, project_dir: Path, port: int, bridge_token: str
    ) -> dict:
        """The V2 launch pipeline against an ARBITRARY project directory:
        install → validation gate → serve → health → hook-load scan → smoke.

        Registry-free on purpose: `_launch_v2` runs it on the real project
        and adds status/persistence around it; `launch_staging` runs the SAME
        pipeline on a staging copy — one definition means fix missions get
        identical evidence quality (boot-log excerpts, hook-load failures)
        in both eras.

        Returns {"status": "success", "process": Popen} — caller owns the
        process — or {"status": "error", "step": ..., "errors": [...]}.
        """
        from app.living_ui.v2_runner import V2RunnerUnavailable

        def _fail(step: str, errors: list) -> dict:
            return {"status": "error", "step": step, "errors": errors}

        try:
            self.v2_runner.ensure_available()
        except V2RunnerUnavailable as e:
            return _fail("setup", [str(e)])

        # Clear any stale listener before binding the port.
        self._kill_process_on_port(port)

        # Renamed/deleted APPLIED migrations brick the boot with an error only
        # pocketbase.log ever sees — catch them here, before any process spawns.
        divergence = self._check_migration_divergence(project_dir)
        if divergence:
            return _fail("validation", [divergence])

        try:
            await self.v2_runner.install(project_dir)
        except Exception as e:
            return _fail("install", [str(e)])

        gate = await self.v2_runner.gate(project_dir)
        if not gate.passed:
            return _fail("validation", [gate.output])

        # pocketbase.log is append-mode across launches: remember where THIS
        # boot starts so failures below can quote only their own boot's lines.
        pb_log_path = project_dir / "logs" / "pocketbase.log"
        pb_log_offset = pb_log_path.stat().st_size if pb_log_path.exists() else 0

        def _pb_log_since_boot(limit_lines: int = 30) -> str:
            """Errors FIRST, then the newest lines. A naive tail once shipped
            30 lines of realtime-subscription chatter while the actual
            'cannot be blank' errors sat just above the window."""
            try:
                with open(pb_log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pb_log_offset)
                    lines = f.read().splitlines()
                error_lines = [
                    ln
                    for ln in lines
                    if any(
                        k in ln.lower()
                        for k in ("error", "failed", "panic", "cannot be")
                    )
                ][-limit_lines:]
                tail = [ln for ln in lines[-10:] if ln not in error_lines]
                picked = error_lines + tail
                return "\n".join(picked[-(limit_lines + 10) :])
            except Exception:
                return ""

        try:
            process = await self.v2_runner.start(
                project_dir, port, bridge_token=bridge_token
            )
        except Exception as e:
            return _fail("start", [str(e)])

        if not await self.v2_runner.wait_healthy(port):
            self._terminate_process(process)
            # A dead health check with no cause starved the agent before —
            # the boot abort (bad migration, hook panic) is in pocketbase.log
            # and nowhere else. Ship this boot's lines with the failure.
            errors = [f"/api/health not responding on :{port}"]
            boot_log = _pb_log_since_boot()
            if boot_log:
                errors.append("pocketbase.log (this boot):\n" + boot_log)
            return _fail("health", errors)

        # A hook file that fails to load is a CORRUPT app, not a healthy one:
        # every route/cron below the throwing line silently does not exist.
        # Observed live: top-level setTimeout() killed ops.pb.js at line 57,
        # health passed, and the app shipped with half its routes missing.
        boot_log = _pb_log_since_boot(200)
        load_failures = [
            line for line in boot_log.splitlines() if "failed to execute" in line
        ]
        if load_failures:
            self._terminate_process(process)
            return _fail(
                "hooks",
                [
                    "A hook file failed to load — every route and cron job "
                    "defined after the throwing line DOES NOT EXIST in the "
                    "running app:\n" + "\n".join(load_failures[:5]),
                ],
            )

        # Walk-verify smoke pass (headless, invisible): app must mount with
        # zero console errors. 'skipped' (no browser) never blocks a launch.
        url = f"http://127.0.0.1:{port}"
        verify_status, verify_detail = await self.v2_runner.verify(project_dir, url)
        if verify_status == "fail":
            self._terminate_process(process)
            # The browser sees only status codes; the CAUSE (hook exception,
            # bad query) is server-side. Ship this boot's log lines so the
            # agent debugs evidence instead of inventing explanations.
            errors = [verify_detail]
            boot_log = _pb_log_since_boot()
            if boot_log:
                errors.append("pocketbase.log (this boot):\n" + boot_log)
            return _fail("verify", errors)
        if verify_status == "skipped":
            logger.warning(
                f"[LIVING_UI:V2] verify skipped for {project_dir.name}: {verify_detail}"
            )

        return {"status": "success", "process": process}

    def _external_config(self, project_dir: Path) -> Dict[str, Any]:
        """craftbot.json for an external project ({} when unreadable)."""
        try:
            return json.loads(
                (Path(project_dir) / "craftbot.json").read_text(encoding="utf-8")
            )
        except Exception:
            return {}

    async def _run_external_pipeline(
        self, project_dir: Path, port: int, bridge_token: str
    ) -> dict:
        """Launch an EXTERNAL app via its craftbot.json pipeline verbs —
        the first real consumer of the M3/M4 four-verb contract
        (EXTERNAL-APPS-PLAN Phase A). Reduced gate per WORKFLOWS I-R2:
        install/build (when declared) + start + health. No kit, no lui gate,
        no PocketBase anything. Same result envelope as the V2 pipeline.
        """
        project_dir = Path(project_dir)

        def _fail(step: str, errors: list) -> dict:
            return {"status": "error", "step": step, "errors": errors}

        pipeline = self._external_config(project_dir).get("pipeline") or {}
        start_cmd = str(pipeline.get("start") or "").strip()
        if not start_cmd:
            return _fail(
                "adopt",
                [
                    "No start command yet: write the pipeline verbs "
                    '("install", "build", "start", "health") into '
                    f"{project_dir}/craftbot.json for this app's stack — use "
                    "{{PORT}} where the port belongs — then call "
                    "living_ui_notify_ready again.",
                ],
            )

        self._kill_process_on_port(port)

        # app.log is append-mode across launches (same idiom as
        # pocketbase.log): remember where THIS boot starts so failures quote
        # only their own lines, errors first.
        log_path = project_dir / "logs" / "app.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_offset = log_path.stat().st_size if log_path.exists() else 0

        def _log_since_boot(limit_lines: int = 30) -> str:
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(log_offset)
                    lines = f.read().splitlines()
                error_lines = [
                    ln
                    for ln in lines
                    if any(
                        k in ln.lower()
                        for k in ("error", "failed", "panic", "traceback", "cannot")
                    )
                ][-limit_lines:]
                tail = [ln for ln in lines[-10:] if ln not in error_lines]
                picked = error_lines + tail
                return "\n".join(picked[-(limit_lines + 10) :])
            except Exception:
                return ""

        bridge_env = {}
        if bridge_token:
            bridge_port = int(os.environ.get("BROWSER_PORT", "7926"))
            bridge_env = {
                "CRAFTBOT_BRIDGE_URL": f"http://localhost:{bridge_port}",
                "CRAFTBOT_BRIDGE_TOKEN": bridge_token,
            }

        # install / build: declared-only, logged, hard-timeboxed.
        for step in ("install", "build"):
            cmd = str(pipeline.get(step) or "").strip()
            if not cmd:
                continue
            cmd = self._resolve_python_in_command(cmd.replace("{{PORT}}", str(port)))
            try:
                with open(log_path, "a", encoding="utf-8") as lh:
                    lh.write(f"\n[{step}] {cmd}\n")
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        cwd=str(project_dir),
                        env={**os.environ, **bridge_env},
                        stdout=lh,
                        stderr=lh,
                    )
                    code = await asyncio.wait_for(proc.wait(), timeout=600)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return _fail(step, [f"{step} timed out after 600s", _log_since_boot()])
            except Exception as e:
                return _fail(step, [f"{step} failed to run: {e}"])
            if code != 0:
                return _fail(
                    step,
                    [f"{step} exited with {code}", "app.log:\n" + _log_since_boot()],
                )

        start_cmd = start_cmd.replace("{{PORT}}", str(port))
        try:
            process = self._start_process(
                cwd=project_dir,
                command=start_cmd,
                log_file=log_path,
                port=port,
                extra_env=bridge_env,
            )
        except Exception as e:
            return _fail("start", [str(e)])

        healthy = await self._check_health_with_strategy(
            pipeline.get("health"), port, process, timeout=45
        )
        if not healthy:
            self._terminate_process(process)
            errors = [
                f"App not healthy on :{port} (health config: "
                f"{pipeline.get('health')!r})"
            ]
            boot_log = _log_since_boot()
            if boot_log:
                errors.append("app.log (this boot):\n" + boot_log)
            return _fail("health", errors)

        return {"status": "success", "process": process}

    async def _launch_v2(self, project: LivingUIProject) -> dict:
        """V2 launch of the REAL project: the shared pipeline plus registry
        state (status, url, persistence) and the pristine-baseline hook.

        One PocketBase process serves both the API and the built frontend
        (living-ui-v2 spec D5); errors come back machine-readable so the
        building agent can fix and retry. EXTERNAL projects dispatch to
        their own pipeline executor — same registry handling around it.
        """
        project_path = Path(project.path)

        # Clear any stale process before relaunching (the pipeline also kills
        # by port — this drops our own stale handle).
        if project.process and project.process.poll() is None:
            self._terminate_process(project.process)
        project.process = None
        if not project.port:
            project.port = self._allocate_port()

        if not project.bridge_token:
            project.bridge_token = secrets.token_urlsafe(32)

        if getattr(project, "project_type", "native") == "external":
            result = await self._run_external_pipeline(
                project_path, project.port, project.bridge_token
            )
        else:
            result = await self._run_launch_pipeline(
                project_path, project.port, project.bridge_token
            )
        if result["status"] != "success":
            project.status = "error"
            project.error = "; ".join(str(e)[:500] for e in result["errors"])
            self._save_projects()
            return result

        project.process = result.pop("process")

        project.status = "running"
        project.url = f"http://127.0.0.1:{project.port}"
        project.backend_url = project.url
        project.error = None
        self._save_projects()

        # Pristine-baseline snapshot: taken ONCE, at the first successful
        # launch of a never-delivered app — before the agent or verifier has
        # created any test records. finalize_first_delivery() restores it
        # right before the delivery announce so the user's first sight of the
        # app is junk-free. Best-effort by design: a failed snapshot must
        # never block a launch (worst case the app delivers with test data,
        # which is today's behavior).
        try:
            from app.factory.host_craftbot import get_factory_host
            from app.living_ui.pb_data_io import snapshot_pb_data

            baseline = project_path / ".snapshots" / "baseline"
            if (
                getattr(project, "project_type", "native") != "external"
                and not baseline.exists()
                and not get_factory_host().is_delivered(project.id)
            ):
                snapshot_pb_data(
                    project_path / "pb" / "pb_data", baseline, self.living_ui_dir
                )
        except Exception as e:
            logger.warning(f"[LIVING_UI:V2] baseline snapshot skipped: {e}")

        logger.info(f"[LIVING_UI:V2] {project.name} running at {project.url}")
        return {
            "status": "success",
            "url": project.url,
            "backend_url": project.url,
            "port": project.port,
        }

    async def finalize_first_delivery(self, project_id: str) -> dict:
        """Restore the pristine pb_data baseline and relaunch, so the app the
        user is about to be handed contains no agent/verifier test records.

        Called from walk_verify's clean branch, on a never-delivered app,
        AFTER the verifier passed against the live (junk-filled) DB and
        BEFORE the delivery announce. Migration files written during the
        build re-apply on the restored DB at boot (they are absent from its
        _migrations table), so the delivered schema is current — the gate
        proves the full migration chain replays cleanly on every validate.

        A missing baseline (legacy project, snapshot failure at first launch)
        is NOT an error: we skip the restore and deliver as today, never
        guess-wipe. Returns {"status": "success"} or an error dict in the
        _launch_v2 envelope.
        """
        project = self.projects.get(project_id)
        if not project:
            return {
                "status": "error",
                "step": "finalize",
                "errors": [f"Unknown project: {project_id}"],
            }
        project_path = Path(project.path)
        baseline = project_path / ".snapshots" / "baseline"
        if not (baseline / "data.db").exists():
            logger.info(
                f"[LIVING_UI:V2] no baseline for {project_id} — delivering without restore"
            )
            return {"status": "success", "restored": False}

        from app.living_ui.pb_data_io import restore_pb_data

        # Stop the server before touching pb_data (a live writer during the
        # restore corrupts both sides). Don't flip status mid-sequence — the
        # watchdog restarts anything still marked "running" with a dead port,
        # and a half-finalized app must not be relaunched under our feet.
        project.status = "stopped"
        if project.process:
            self._terminate_process(project.process)
            project.process = None
        if project.port and self._is_port_in_use(project.port):
            self._kill_process_on_port(project.port)

        try:
            restore_pb_data(
                baseline, project_path / "pb" / "pb_data", self.living_ui_dir
            )
        except Exception as e:
            # pb_data may now be gone/partial — a plain start would boot an
            # empty DB. Fall through to the full pipeline, which re-applies
            # migrations and re-verifies before anyone is told "ready".
            logger.error(f"[LIVING_UI:V2] baseline restore failed: {e}")
            return await self._launch_v2(project)

        try:
            project.process = await self.v2_runner.start(
                project_path, project.port, bridge_token=project.bridge_token
            )
            if not await self.v2_runner.wait_healthy(project.port):
                raise RuntimeError(f"/api/health not responding on :{project.port}")
        except Exception as e:
            logger.warning(
                f"[LIVING_UI:V2] slim relaunch after restore failed ({e}) — "
                "falling back to the full pipeline"
            )
            return await self._launch_v2(project)

        project.status = "running"
        project.url = f"http://127.0.0.1:{project.port}"
        project.backend_url = project.url
        project.error = None
        self._save_projects()
        logger.info(f"[LIVING_UI:V2] {project_id} finalized for first delivery")
        return {"status": "success", "restored": True}

    async def launch_staging(self, project_id: str) -> dict:
        """Gate + boot the STAGING copy of a delivered app (creating or
        refreshing it first). The real app is not rebuilt, restarted or
        written to — it keeps serving the old working code while the change
        is developed and verified in the copy.

        Same result envelope as _launch_v2, plus url/port of the staging
        instance on success.
        """
        from app.factory.host_craftbot import get_factory_host
        from app.living_ui.staging import StagingInstance

        project = self.projects.get(project_id)
        if not project:
            return {
                "status": "error",
                "step": "staging",
                "errors": [f"Unknown project: {project_id}"],
            }
        if getattr(project, "project_type", "native") == "external":
            # Staging is pb/-shaped; an external app has no clonable DB or
            # gate. Changes to externals run live (EXTERNAL-APPS-PLAN v1).
            return {
                "status": "error",
                "step": "staging",
                "errors": [
                    "External apps have no staging mode — relaunch live via "
                    "living_ui_notify_ready (changes apply directly)."
                ],
            }

        host = get_factory_host()
        record = host.get_staging_record(project_id)
        try:
            if (
                record
                and Path(record.get("dir", "")).joinpath("manifest.json").exists()
            ):
                instance = StagingInstance.from_record(project_id, record)
                self.staging.sync_code(project, instance.dir)
            else:
                instance = await self.staging.create_copy(project)
        except Exception as e:
            # Never fall back to gating/serving the real project dir — that
            # is exactly the live-UI blanking this mode exists to prevent.
            return {
                "status": "error",
                "step": "staging",
                "errors": [f"Could not prepare the staging copy: {e}"],
            }

        # Reuse (never overwrite) the project's bridge token: the live app's
        # running process carries it in its env, and validate_bridge_token
        # checks the current in-memory value — re-minting would cut the live
        # app off from the bridge mid-modify.
        if not project.bridge_token:
            project.bridge_token = secrets.token_urlsafe(32)

        # Record BEFORE booting: a pipeline failure must still leave the
        # record in place so living_ui_http redirects there and the next
        # notify_ready reuses the copy instead of re-cloning.
        host.set_staging_record(project_id, instance.to_record())

        result = await self._run_launch_pipeline(
            instance.dir, instance.port, project.bridge_token
        )
        if result["status"] != "success":
            return result

        self.staging.adopt_process(instance, result.pop("process"))
        host.set_staging_record(project_id, instance.to_record())

        # A modify is now demonstrably in progress (staging is up) — re-arm
        # the factory machine so the modify gets the same supervision as a
        # build: fix missions on defects, caps, machine announcements
        # (LIFECYCLE-PLAN Phase 2). Deterministic here, never agent-driven;
        # no-ops when a modify/fix arc is already in flight.
        try:
            host.begin_modify(project_id)
        except Exception as e:
            logger.warning(f"[LIVING_UI:STAGING] begin_modify failed: {e}")

        logger.info(f"[LIVING_UI:STAGING] {project_id} staging up at {instance.url}")
        return {
            "status": "success",
            "url": instance.url,
            "backend_url": instance.url,
            "port": instance.port,
            "staging": True,
        }

    async def finalize_modify(self, project_id: str) -> dict:
        """The flip, after a clean staging verify: relaunch the REAL project
        (the gate rebuilds its pb_public; new migration files apply to the
        real pb_data at boot — user data stays in place), then destroy the
        staging copy and every test record with it.

        On failure the staging copy and its record are KEPT — the real app
        is the casualty being repaired, and the next fix iteration needs the
        copy.
        """
        from app.factory.host_craftbot import get_factory_host

        result = await self.launch_and_verify(project_id)
        if result["status"] != "success":
            return result

        host = get_factory_host()
        try:
            self.staging.destroy(project_id, host.get_staging_record(project_id))
        finally:
            host.clear_staging_record(project_id)
        return result

    async def launch_and_verify(self, project_id: str) -> dict:
        """
        Launch and verify a Living UI project using its manifest pipeline.

        Runs backend and frontend tracks in parallel to collect all errors at once.
        Only starts servers if all pre-start checks pass.

        Dependency graph:
            pip install ──→ internal tests ──→ unit + compatibility tests (parallel)
            npm install ──→ npm run build
            Both tracks run in parallel. If ANY errors, return all without starting servers.
            If clean: start backend → health check → external tests → start frontend.

        Returns:
            {"status": "success", "url": "...", "backend_url": "...", "port": N}
            {"status": "error", "step": "validation", "errors": [...all errors...]}
        """
        project = self.projects.get(project_id)
        if not project:
            return {
                "status": "error",
                "step": "setup",
                "errors": [f"Project not found: {project_id}"],
            }

        project_path = Path(project.path)
        if not project_path.exists():
            return {
                "status": "error",
                "step": "setup",
                "errors": [f"Project path not found: {project.path}"],
            }

        return await self._launch_v2(project)

    async def _ensure_port_available(self, port: int) -> bool:
        """Ensure a port is available, killing orphan processes if needed."""
        if not self._is_port_in_use(port):
            return True

        logger.warning(f"[LIVING_UI:PIPELINE] Port {port} in use, attempting to free")
        self._kill_process_on_port(port)
        await asyncio.sleep(1)

        if self._is_port_in_use(port):
            logger.error(f"[LIVING_UI:PIPELINE] Could not free port {port}")
            return False
        return True

    _python_path_cache: Optional[str] = None

    @classmethod
    def _find_real_python(cls) -> str:
        """Find a usable system Python interpreter, skipping the Microsoft
        Store stub alias.

        On Windows, `%LocalAppData%\\Microsoft\\WindowsApps\\python.exe` is
        an "App Execution Alias" stub that prints "Python was not found..."
        and exits non-zero — even when the user HAS python.org's Python
        installed elsewhere. The stub is high on PATH so a naive
        `shutil.which("python")` returns it, leading to silent failures.

        Strategy: walk every PATH entry (PATHEXT-aware) for python3/python,
        skip WindowsApps, validate candidates with `--version`, then fall
        back to well-known python.org install locations. Cached after the
        first hit.
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
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
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
        `sys.executable` is the agent EXE itself, not a Python interpreter —
        substituting it would spawn the entire agent again with junk args.
        Find a real system Python via `_find_real_python` instead.
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

    @classmethod
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
        return process

    def _create_frontend_log(project_path: Path) -> Path:
        """Create a timestamped frontend log file path."""
        logs_dir = project_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"frontend_{timestamp}.log"

    @staticmethod
    def _read_log_tail(log_file: Path, chars: int = 1000) -> str:
        """Read the last N characters of a log file."""
        try:
            content = log_file.read_text(encoding="utf-8")
            return content[-chars:] if len(content) > chars else content
        except Exception:
            return "(could not read log)"

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
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
            else:
                process.terminate()
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, Exception):
            try:
                process.kill()
            except Exception:
                pass

    def _kill_process_on_port(self, port: int) -> bool:
        """
        Kill any process listening on the specified port (Windows-specific).

        Args:
            port: The port to free

        Returns:
            True if a process was killed, False otherwise
        """
        if os.name != "nt":
            # Linux/Mac: use lsof and kill
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"], capture_output=True, text=True
                )
                if result.stdout.strip():
                    pids = result.stdout.strip().split("\n")
                    for pid in pids:
                        subprocess.run(["kill", "-9", pid], capture_output=True)
                    logger.info(f"[LIVING_UI] Killed process(es) on port {port}")
                    return True
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Failed to kill process on port {port}: {e}"
                )
            return False
        else:
            # Windows: use netstat and taskkill
            try:
                no_window = (
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                )
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                    shell=True,
                    creationflags=no_window,
                )
                killed = False
                for line in result.stdout.split("\n"):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            # /T kills entire process tree (shell + child processes)
                            subprocess.run(
                                ["taskkill", "/T", "/F", "/PID", pid],
                                capture_output=True,
                                shell=True,
                                creationflags=no_window,
                            )
                            logger.info(
                                f"[LIVING_UI] Killed process tree {pid} on port {port}"
                            )
                            killed = True
                if killed:
                    return True
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Failed to kill process on port {port}: {e}"
                )
            return False

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

        # 2b. Reap staging copies. None is legitimately alive at boot (their
        # modify missions died with the previous process), but their
        # PocketBase instances outlive us — kill by recorded pid, delete the
        # copies, clear the records so nothing redirects to a dead port.
        try:
            from app.factory.host_craftbot import get_factory_host

            host = get_factory_host()
            records = {}
            for pid_ in list(self.projects):
                record = host.get_staging_record(pid_)
                if record:
                    records[pid_] = record
            reaped = self.staging.reap_all(records)
            for pid_ in records:
                host.clear_staging_record(pid_)
            if reaped:
                logger.info(f"[LIVING_UI] Reaped {reaped} staging leftover(s)")
        except Exception as e:
            logger.warning(f"[LIVING_UI] staging reap failed: {e}")

        # 3. Reset all project statuses to 'stopped' and clear process references
        for project in self.projects.values():
            if project.status == "running":
                project.status = "stopped"
                project.process = None
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

        # _staging is workspace infrastructure, not an orphan project: the
        # wizard stages reference files under it (with its own age-based
        # sweeper) and StagingSupervisor keeps modify-era app copies there
        # (reaped deliberately — kill recorded pid, then delete — by
        # reap_orphans(), not by this blind rmtree).
        skip_names = {"_staging"}

        for folder in self.living_ui_dir.iterdir():
            if folder.name in skip_names:
                continue
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
        auth_mode: str = "none",
        style_pack: str = "",
    ) -> LivingUIProject:
        """
        Create a new Living UI project from template.

        Args:
            name: Project name
            description: Project description
            features: List of requested features
            data_source: Optional API URL or data source description
            theme: UI theme (light, dark, system)

        Returns:
            Created LivingUIProject instance
        """
        project_id = self._generate_id()
        sanitized_name = self._sanitize_name(name)
        folder = f"{sanitized_name}_{project_id}"

        # New projects are V2 (PocketBase single-process). The tools CLI does
        # the real scaffolding: blueprint copy, kit vendoring, placeholder
        # substitution, superuser bootstrap, system-file hash canon.
        port = self._allocate_port()
        if auth_mode not in ("none", "multi-user"):
            auth_mode = "none"

        try:
            result = await self.v2_runner.scaffold(
                name=name,
                description=description,
                parent_dir=self.living_ui_dir,
                port=port,
                project_id=project_id,
                auth_mode=auth_mode,
                folder=folder,
                style=style_pack or None,
            )
        except Exception as e:
            self._release_port(port)
            raise RuntimeError(f"Failed to scaffold V2 project: {e}")

        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(result.path),
            status="created",
            style_pack=style_pack or "",
            port=port,
            backend_port=None,
            features=features or [],
            theme=theme,
        )

        self._register_acquired(project, delivered=False)

        logger.info(f"[LIVING_UI] Created V2 project: {name} ({project_id})")
        return project

    def _register_acquired(self, project: LivingUIProject, *, delivered: bool) -> None:
        """Every entry point (scaffold / marketplace / import) lands here
        after its starting state is on disk (LIFECYCLE-PLAN Phase 3):
        registry + persistence + session, and — for sources that arrive as
        finished apps — the delivered flag that keys every later data-safety
        mode (staging verifies, no baseline restore)."""
        self.projects[project.id] = project
        self._save_projects()
        try:
            self.ensure_project_session(project)
        except Exception as e:
            logger.warning(
                f"[LIVING_UI] Could not ensure session for project {project.id}: {e}"
            )
        if delivered:
            try:
                from app.factory.host_craftbot import get_factory_host

                get_factory_host().mark_delivered(project.id)
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] mark_delivered failed for {project.id}: {e}"
                )

    # ── import (LIFECYCLE-PLAN Phase 4: one door, three sources) ────────────
    @staticmethod
    def detect_import_source(source: str) -> str:
        """'zip' | 'folder' | 'git' — raises ValueError on anything else."""
        s = (source or "").strip()
        if not s:
            raise ValueError("import source is required")
        if s.startswith(("http://", "https://", "git@", "file://")) or s.endswith(
            ".git"
        ):
            return "git"
        p = Path(s).expanduser()
        if p.is_file() and p.suffix.lower() == ".zip":
            return "zip"
        if p.is_dir():
            return "folder"
        raise ValueError(
            f"Cannot import {source!r}: not a .zip file, a folder, or a git URL"
        )

    @staticmethod
    def infer_app_runtime(src: Path) -> Optional[str]:
        """Best-effort runtime detection for a foreign app tree
        (EXTERNAL-APPS-PLAN Phase A). None = the adoption agent decides."""
        src = Path(src)
        if (src / "package.json").exists():
            return "node"
        if (src / "pyproject.toml").exists() or (src / "requirements.txt").exists():
            return "python"
        if (src / "go.mod").exists():
            return "go"
        if (src / "Cargo.toml").exists():
            return "rust"
        if (src / "index.html").exists():
            return "static"
        return None

    @staticmethod
    def _find_v2_root(root: Path) -> Optional[Path]:
        """The V2 Living UI project dir inside a source tree (root or first
        level), or None when the tree is a FOREIGN app."""
        candidates = [root] + [d for d in sorted(root.iterdir()) if d.is_dir()]
        for c in candidates:
            mf = c / "manifest.json"
            if not mf.exists():
                continue
            try:
                if (
                    json.loads(mf.read_text(encoding="utf-8")).get("livingUIVersion")
                    == 2
                ):
                    return c
            except Exception:
                continue
        return None

    async def import_project_source(
        self, source: str, name: Optional[str] = None
    ) -> LivingUIProject:
        """Import from a ZIP, a local folder, or a git URL — one door.

        A V2 Living UI tree imports natively (identity rewrite, credential
        strip, kit re-canon, delivered registration). A FOREIGN tree is
        registered as an EXTERNAL project that will run AS-IS in its own
        runtime, adopted by an agent mission (EXTERNAL-APPS-PLAN — the user
        decided foreign apps run unchanged, never auto-rebuilt)."""
        import tempfile
        import zipfile

        kind = self.detect_import_source(source)
        if kind == "folder":
            # Read-only: the user's folder is copied, never modified.
            root = Path(source).expanduser()
            if self._find_v2_root(root) is not None:
                return await self._import_project_tree(root, name)
            return await self._import_external_tree(root, name, origin=source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if kind == "zip":
                with zipfile.ZipFile(source) as zf:
                    zf.extractall(root)
            else:
                self._fetch_git_source(source, root)
            if self._find_v2_root(root) is not None:
                return await self._import_project_tree(root, name)
            return await self._import_external_tree(root, name, origin=source)

    async def _import_external_tree(
        self, root: Path, name: Optional[str], origin: str
    ) -> LivingUIProject:
        """Register a foreign app to RUN AS-IS: copy the tree, allocate a
        port, write the CraftBot pipeline config, register as an external
        project (not delivered — delivery is its first verified launch).
        The adoption mission fills in the pipeline verbs."""
        # Unwrap the single wrapper dir git clones / GitHub zips create.
        src = root
        entries = [e for e in Path(root).iterdir() if e.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            src = entries[0]
        if not any(f.is_file() for f in src.rglob("*")):
            raise ValueError("Source tree is empty — nothing to import")

        runtime = self.infer_app_runtime(src)
        display = (name or src.name or "External App").strip() or "External App"
        project_id = self._generate_id()
        port = self._allocate_port()
        dest = self.living_ui_dir / f"{self._sanitize_name(display)}_{project_id}"
        # node_modules is rebuilt by the install verb; .git/logs never import.
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns("node_modules", ".git", "logs"),
        )
        (dest / "logs").mkdir(exist_ok=True)

        # CraftBot's config lives in craftbot.json — NEVER manifest.json,
        # which a foreign app may legitimately own (Chrome extensions, PWAs).
        # Same four pipeline verbs as V2 manifests (REQUIREMENTS M3/M4);
        # start/health run through {{PORT}} substitution.
        config = {
            "id": project_id,
            "name": display,
            "external": True,
            "origin": origin,
            "appRuntime": runtime,
            "port": port,
            "pipeline": {
                "install": "",
                "build": "",
                "start": "",
                "health": {"strategy": "http_get", "url": "http://127.0.0.1:{{PORT}}/"},
            },
        }
        (dest / "craftbot.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )

        # The adoption SPEC is deterministic and small: the deliverable of an
        # import is the MANIFEST, so verification covers launchability — not
        # the foreign app's internal feature inventory. (Observed live
        # 2026-08-05, chili3d: feature-level requirements written from the
        # README made the verifier fail an optional plugin the adopter is
        # forbidden to touch, spawning unfixable fix missions.)
        ref = dest / "reference"
        ref.mkdir(exist_ok=True)
        (ref / "requirements.md").write_text(
            f"# {display} — Adoption Requirements\n\n"
            "This is an EXTERNAL app adopted to run AS-IS in its own runtime. "
            "The deliverable is the run configuration (craftbot.json), not "
            "the app's own features.\n\n"
            "## Features\n"
            "The user can open the app at its URL and its main screen "
            "renders (not blank, not an error page).\n\n"
            "## Scope\n"
            "The app's INTERNAL features are NOT part of this verification — "
            "they ship as-is. Console errors or 404s from the app's own "
            "optional components (plugins, analytics, telemetry) are NOT "
            "failures when the main screen works; mention anything visibly "
            "broken as a caveat instead.\n",
            encoding="utf-8",
        )

        project = LivingUIProject(
            id=project_id,
            name=display,
            description=f"External app imported from {origin}",
            path=str(dest),
            status="stopped",
            port=port,
            project_type="external",
            app_runtime=runtime,
        )
        self._register_acquired(project, delivered=False)
        logger.info(
            f"[LIVING_UI] Registered EXTERNAL app: {display} ({project_id}, "
            f"runtime={runtime or 'unknown'})"
        )
        return project

    def post_import_brief(self, project: LivingUIProject) -> str:
        """The run brief that finishes an import — verify for natives,
        ADOPTION for externals (write the pipeline verbs, then launch and
        verify). One composer so the action and the UI path never drift."""
        if getattr(project, "project_type", "native") == "external":
            return (
                f"ADOPT EXTERNAL APP '{project.name}' ({project.id}) at "
                f"{project.path}.\n"
                f"This is a foreign app that must RUN AS-IS in its own runtime "
                f"(detected: {project.app_runtime or 'unknown'}). Do NOT "
                f"rebuild it and do NOT edit its code except config needed to "
                f"bind the assigned port. Your deliverable is the RUN CONFIG, "
                f"not the app's features — reference/requirements.md already "
                f"defines the verification scope (launches + main screen "
                f"renders); do not rewrite it.\n"
                f"1. Understand the app: how it installs, builds, starts and "
                f"health-checks.\n"
                f"2. Write the pipeline verbs into {project.path}/craftbot.json "
                f'("install", "build", "start", "health") — use {{{{PORT}}}} '
                f"where the port belongs; the app MUST bind "
                f"127.0.0.1:{project.port}.\n"
                f"3. Note what the app is in {project.path}/LIVING_UI.md (one "
                f"short section — the user's reference, not a spec).\n"
                f'4. living_ui_notify_ready(project_id="{project.id}") — fix '
                f"any returned errors (evidence lands in logs/app.log) — then "
                f'living_ui_walk_verify(project_id="{project.id}").\n'
                f"The system announces the result — do not send status "
                f"messages."
            )
        return (
            f"IMPORT COMPLETE for Living UI '{project.name}' "
            f"({project.id}) at {project.path}.\n"
            f"Launch and verify it now:\n"
            f'living_ui_notify_ready(project_id="{project.id}") then\n'
            f'living_ui_walk_verify(project_id="{project.id}").\n'
            f"Fix any returned errors and repeat. The system announces "
            f"the result to the user — do not send status messages."
        )

    async def import_project_zip(
        self, zip_path: str, name: Optional[str] = None
    ) -> LivingUIProject:
        """Back-compat wrapper: ZIP import via the unified source door."""
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(root)
            return await self._import_project_tree(root, name)

    async def convert_foreign_source(
        self, source: str, name: Optional[str] = None, description: str = ""
    ) -> LivingUIProject:
        """Conversion (LIFECYCLE-PLAN Phase 4B): a foreign (non-Living-UI)
        app cannot be imported — its stack doesn't run here — so it is
        REBUILT: scaffold a fresh V2 project, ship the original source as
        read-only reference material, synthesize the requirements FROM that
        source, and let the normal supervised build implement them. Only the
        knowledge of what to build is imported; every delivered line is new.

        Returns the scaffolded project (pre-delivery — the caller dispatches
        the standard build run). Raises on a V2 source (that's an import)."""
        import tempfile

        kind = self.detect_import_source(source)
        if kind == "folder":
            return await self._convert_tree(
                Path(source).expanduser(), name, description, origin=source
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if kind == "zip":
                import zipfile

                with zipfile.ZipFile(source) as zf:
                    zf.extractall(root)
            else:
                self._fetch_git_source(source, root)
            return await self._convert_tree(root, name, description, origin=source)

    async def _convert_tree(
        self, root: Path, name: Optional[str], description: str, origin: str
    ) -> LivingUIProject:
        # A V2 Living UI must go through import — converting it would throw
        # away a working app and rebuild it from prose.
        candidates = [root] + [d for d in sorted(root.iterdir()) if d.is_dir()]
        for c in candidates:
            mf = c / "manifest.json"
            if mf.exists():
                try:
                    if (
                        json.loads(mf.read_text(encoding="utf-8")).get(
                            "livingUIVersion"
                        )
                        == 2
                    ):
                        raise ValueError(
                            "This source IS a Living UI V2 project — use "
                            "living_ui_import, not conversion."
                        )
                except ValueError:
                    raise
                except Exception:
                    pass

        # Unwrap the single wrapper dir git clones / GitHub zips create.
        src = root
        entries = [e for e in root.iterdir() if e.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            src = entries[0]

        display = (name or src.name or "Converted App").strip() or "Converted App"
        project = await self.create_project(
            name=display,
            description=description or f"Rebuild of the app imported from {origin}",
        )
        try:
            ref_source = Path(project.path) / "reference" / "source"
            self._ingest_reference_source(src, ref_source)

            from app.living_ui import wizard

            doc = await wizard.synthesize_requirements_from_source(
                ref_source, display, description
            )
            doc += (
                "\n\n## Original source\n"
                "This app is a REBUILD of an existing app whose source code "
                "ships read-only at `reference/source/`. Consult it for exact "
                "behaviors, field names, copy and edge cases — but never copy "
                "code from it: the stack is different, and only the features "
                "above are binding.\n"
            )
            req = Path(project.path) / "reference" / "requirements.md"
            req.parent.mkdir(parents=True, exist_ok=True)
            req.write_text(doc + "\n", encoding="utf-8")
        except Exception:
            # A conversion without requirements is a blank build with an
            # orphan tab — remove the scaffold and surface the real error.
            try:
                await self.delete_project(project.id)
            except Exception:
                pass
            raise
        return project

    # What never enters reference/source: runtime junk, dependency trees,
    # and anything credential-shaped. Caps keep a huge repo from bloating
    # the project (source is EVIDENCE for the synthesis + builder, not a
    # working checkout).
    _CONVERT_SKIP_DIRS = {
        "node_modules",
        ".git",
        "logs",
        "dist",
        "build",
        ".venv",
        "venv",
        "__pycache__",
        "pb_data",
        ".next",
        "target",
    }
    _CONVERT_SKIP_NAMES = {
        "credentials.json",
        "token.json",
        ".superuser",
        ".agent-token",
        ".jwt_secret",
        ".npmrc",
        ".netrc",
    }

    def _ingest_reference_source(
        self,
        src: Path,
        dest: Path,
        max_file_bytes: int = 1_000_000,
        max_total_bytes: int = 50_000_000,
    ) -> None:
        copied = 0
        for f in sorted(Path(src).rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src)
            if any(part in self._CONVERT_SKIP_DIRS for part in rel.parts):
                continue
            if f.name in self._CONVERT_SKIP_NAMES or f.name.startswith(".env"):
                continue
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes or copied + size > max_total_bytes:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied += size
        logger.info(
            f"[LIVING_UI] ingested reference source into {dest} ({copied} bytes)"
        )

    def _fetch_git_source(self, url: str, dest: Path) -> None:
        """Land a git repo's tree under dest. GitHub gets the zip-download
        fast path (no git binary, same mechanism as the marketplace
        installer) with a main→master fallback; everything else (and
        file:// URLs) is a depth-1 clone."""
        import io
        import subprocess
        import urllib.request
        import zipfile

        m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        if m:
            import ssl

            import certifi

            owner, repo = m.group(1), m.group(2)
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            last_err: Optional[Exception] = None
            for branch in ("main", "master"):
                zip_url = (
                    f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
                )
                try:
                    req = urllib.request.Request(
                        zip_url, headers={"User-Agent": "CraftBot"}
                    )
                    data = urllib.request.urlopen(
                        req, timeout=60, context=ssl_ctx
                    ).read()
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        zf.extractall(dest)
                    return
                except Exception as e:
                    last_err = e
            raise RuntimeError(f"GitHub download failed for {url}: {last_err}")

        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest / "repo")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed: {(result.stderr or result.stdout).strip()[:400]}"
            )

    async def _import_project_tree(
        self, root: Path, name: Optional[str] = None
    ) -> LivingUIProject:
        """The shared import pipeline: find the V2 project in the tree, copy
        it in with a fresh identity + port, strip shipped credentials,
        re-canonize, register delivered.

        Round-trip with export: new identity + port, shipped credentials
        stripped, kit re-vendored and hashes re-canonized via kit-sync.
        """
        project_id = self._generate_id()
        candidates = [root] + [d for d in sorted(root.iterdir()) if d.is_dir()]
        src = next((c for c in candidates if (c / "manifest.json").exists()), None)
        if src is None:
            raise ValueError(
                "Not a Living UI project (no manifest.json at its root or "
                "first level). A regular app can't be imported — it can be "
                "REBUILT as a Living UI instead: ask the agent to convert it."
            )
        raw_manifest = (src / "manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(raw_manifest)
        if manifest.get("livingUIVersion") != 2:
            raise ValueError(
                "Only Living UI V2 projects can be imported (foreign apps need "
                "the conversion flow)"
            )

        display = name or manifest.get("name") or "Imported App"
        port = self._allocate_port()
        dest = self.living_ui_dir / f"{self._sanitize_name(display)}_{project_id}"
        # Runtime junk never imports; node_modules is skipped because a
        # foreign machine's install may not run here — the launch pipeline's
        # install step rebuilds it from package.json.
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns("node_modules", ".git", "logs"),
        )

        # Never trust shipped credentials or runtime state.
        (dest / ".superuser").unlink(missing_ok=True)

        # Rewrite identity + port (pipeline start command embeds the port).
        old_port = manifest.get("port")
        manifest["id"], manifest["name"], manifest["port"] = project_id, display, port
        if isinstance(manifest.get("pipeline"), dict) and old_port:
            manifest["pipeline"] = json.loads(
                json.dumps(manifest["pipeline"]).replace(str(old_port), str(port))
            )
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

        # A TEMPLATE tree (a marketplace checkout imported by path — the
        # local living-ui-marketplace clone is full of them) still carries
        # {{...}} tokens in its files; without substitution the app imports
        # registered-but-broken. Same replacement map the marketplace
        # installer uses.
        if "{{" in raw_manifest:
            _desc = str(manifest.get("description", "") or "")
            if "{{" in _desc:  # the description itself may be the token
                _desc = display
            self._replace_placeholders(
                dest,
                {
                    "{{PROJECT_ID}}": project_id,
                    "{{PROJECT_NAME}}": display,
                    "{{PROJECT_DESCRIPTION}}": _desc or display,
                    "{{PORT}}": str(port),
                    "{{BACKEND_PORT}}": str(port),
                    "{{THEME}}": "system",
                    "{{CREATED_AT}}": datetime.now().isoformat(),
                    "{{FEATURES}}": "",
                },
            )

        # Kit re-vendor + hash re-canon (identity rewrite invalidated the canon).
        await self.v2_runner.kit_sync(dest)

        project = LivingUIProject(
            id=project_id,
            name=display,
            description=manifest.get("description", ""),
            path=str(dest),
            status="stopped",
            port=port,
        )
        # Delivered on arrival: an imported app may carry real data — later
        # gates/verifies run in staging mode, never a baseline restore.
        self._register_acquired(project, delivered=True)

        logger.info(f"[LIVING_UI] Imported V2 project: {display} ({project_id})")
        return project

    def create_placeholder_project(
        self, name: str, description: str = ""
    ) -> LivingUIProject:
        """Register a lightweight "creating" project so a tab/progress screen
        appears immediately, before the real import/install populates it.

        Used by async install flows (future V2 import/marketplace) so they
        behave like the form-create flow; the installer must adopt this id so
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
        """Replace template placeholders in all text files under directory.

        Values substituted into .json files are JSON-escaped (a description
        containing quotes/newlines must not break manifest.json)."""
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
            if not (filepath.is_file() and filepath.suffix in text_extensions):
                continue
            try:
                content = filepath.read_text(encoding="utf-8")
                modified = False
                for placeholder, value in replacements.items():
                    if placeholder in content:
                        if filepath.suffix == ".json":
                            value = json.dumps(value)[1:-1]
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
        repo_url: str = "https://github.com/CraftOS-dev/living-ui-marketplace/",
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

        # ADOPTION: when project_id names an EXISTING project with a real
        # directory (the wizard scaffolds one before the build run starts),
        # the install replaces that project in place — same id, port, session
        # and tab — instead of minting a duplicate. Observed live (2026-08-05,
        # kanban board): the build agent installed from the marketplace, a
        # SECOND project appeared, and the factory then redispatched a
        # "continue build" for the orphaned first one, which got built from
        # scratch. Callers only pass an existing id for never-delivered
        # scaffolds; delivered apps always install as a separate new project.
        existing = self.projects.get(project_id)
        adopting = existing is not None and bool(existing.path)
        if adopting:
            project_path = Path(existing.path)
        else:
            project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

        if (
            adopting
            and self.living_ui_dir.resolve()
            not in Path(existing.path).resolve().parents
        ):
            return {
                "status": "error",
                "error": (
                    f"Refusing to replace {existing.path!r} — outside the "
                    "Living UI workspace."
                ),
            }

        preserved_hold: Optional[Path] = None
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

                # The app exists in the zip — NOW it is safe to clear an
                # adopted scaffold, PRESERVING the wizard's requirements
                # (reference/) and the factory's machine state (.factory/),
                # which the continuing build run still needs. The extraction
                # below writes file-by-file into an existing dir, and a plain
                # overlay would leave scaffold leftovers behind (e.g. the
                # starter migration, which would create a stray `items`
                # collection in the installed app).
                if adopting:
                    if existing.process:
                        self._terminate_process(existing.process)
                        existing.process = None
                    if existing.port and self._is_port_in_use(existing.port):
                        self._kill_process_on_port(existing.port)
                    if project_path.exists():
                        preserved_hold = Path(tempfile.mkdtemp(prefix="lui-adopt-"))
                        for rel in ("reference", ".factory"):
                            keep = project_path / rel
                            if keep.exists():
                                shutil.move(str(keep), str(preserved_hold / rel))
                        shutil.rmtree(project_path.resolve())

                # Extract app files to project path
                project_path.mkdir(parents=True, exist_ok=True)
                for member in zf.namelist():
                    if member.startswith(app_prefix) and not member.endswith("/"):
                        # Get the relative path within the app folder
                        rel_path = member[len(app_prefix) :]
                        if rel_path:
                            target = project_path / rel_path
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(target, "wb") as dst:
                                dst.write(src.read())

            logger.info(f"[LIVING_UI:MARKETPLACE] Extracted {app_id} to {project_path}")

            # COMPATIBILITY GATE: this platform only runs Living UI V2
            # projects (root manifest.json, livingUIVersion 2, PocketBase
            # backend). Legacy V1 apps (config/manifest.json, FastAPI
            # backend) are rejected until re-published as V2.
            mf = project_path / "manifest.json"
            is_v2 = False
            if mf.exists():
                try:
                    is_v2 = json.loads(mf.read_text()).get("livingUIVersion") == 2
                except Exception:
                    is_v2 = False
            if not is_v2:
                shutil.rmtree(project_path, ignore_errors=True)
                if preserved_hold is not None:
                    # Adoption: give the scaffold its requirements/factory
                    # state back before bailing out.
                    project_path.mkdir(parents=True, exist_ok=True)
                    for rel in ("reference", ".factory"):
                        kept = preserved_hold / rel
                        if kept.exists():
                            shutil.move(str(kept), str(project_path / rel))
                    shutil.rmtree(preserved_hold, ignore_errors=True)
                    preserved_hold = None
                return {
                    "status": "error",
                    "error": (
                        f"Marketplace app '{app_id}' is in the legacy V1 "
                        "format and cannot run on this V2-only platform. It "
                        "needs to be re-published as a V2 app in the "
                        "marketplace."
                    ),
                }

            # Ports: an adopted project keeps its scaffold ports (the tab and
            # session already reference them); fresh installs allocate.
            if adopting and existing.port:
                frontend_port = existing.port
                backend_port = existing.backend_port or existing.port
            else:
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

            # Record WHICH marketplace app this project holds: a crash
            # between install and build-completion redispatches a "continue
            # build", and without this marker the resumed run cannot tell
            # "already installed here" from "install a new separate app" —
            # it would mint a duplicate through the fresh-install path.
            try:
                mf_path = project_path / "manifest.json"
                mf_data = json.loads(mf_path.read_text(encoding="utf-8"))
                mf_data["marketplaceAppId"] = app_id
                mf_path.write_text(json.dumps(mf_data, indent=2) + "\n")
            except Exception as e:
                logger.warning(f"[LIVING_UI:MARKETPLACE] could not record app id: {e}")

            # Adoption: put the wizard's requirements and the factory state
            # back where the build run expects them.
            if preserved_hold is not None:
                for rel in ("reference", ".factory"):
                    kept = preserved_hold / rel
                    if kept.exists():
                        shutil.move(str(kept), str(project_path / rel))
                shutil.rmtree(preserved_hold, ignore_errors=True)
                preserved_hold = None

            # Identity rewrite touched hash-canonized files (manifest.json):
            # re-vendor the kit and re-canonize hashes, as zip import does.
            await self.v2_runner.kit_sync(project_path)

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
            if adopting:
                # Same tab, same session, same look — only the contents changed.
                project.session_id = existing.session_id
                project.icon = existing.icon
                project.ui_theme = existing.ui_theme
                project.style_pack = existing.style_pack
                project.auto_launch = existing.auto_launch

            # Delivered on arrival (may ship with real data, never
            # walk-verified): marked BEFORE the launch so the success path
            # doesn't snapshot their pb_data as a "pristine" baseline and
            # later verifies run in staging mode.
            self._register_acquired(project, delivered=True)

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
            # Clean up on failure. For an adopted project, put the preserved
            # requirements/factory state back so a retry (or the continuing
            # build run) still has them.
            if preserved_hold is not None:
                try:
                    project_path.mkdir(parents=True, exist_ok=True)
                    for rel in ("reference", ".factory"):
                        kept = preserved_hold / rel
                        if kept.exists():
                            shutil.move(str(kept), str(project_path / rel))
                    shutil.rmtree(preserved_hold, ignore_errors=True)
                except Exception:
                    pass
            elif project_path.exists() and not adopting:
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

    def set_project_ui_theme(
        self, project_id: str, ui_theme: Optional[Dict[str, Any]]
    ) -> None:
        """Persist the project's display theme ({"themeId", "customColors"})."""
        project = self.projects.get(project_id)
        if project is None:
            return
        project.ui_theme = ui_theme or None
        self._save_projects()

    def get_project_by_session_id(self, session_id: str) -> Optional["LivingUIProject"]:
        """Return the Living UI project owning a given session_id, or None."""
        if not session_id:
            return None
        for project in self.projects.values():
            if project.session_id == session_id:
                return project
        return None

    async def start_development_run(
        self,
        project_id: str,
        *,
        brief: Optional[str] = None,
        trigger_source: Optional[str] = None,
        workflow_skill: str = "living-ui-creator",
        status: Optional[str] = "creating",
    ) -> Optional[str]:
        """
        Queue a run in the project's session (LIFECYCLE-PLAN Phase 3: one
        dispatcher for every entry point).

        Defaults reproduce the classic build run (full task instruction,
        LIVING_UI_DEV trigger, creator skill, status "creating"). Other
        entries pass their own brief/source/skill — e.g. an import's
        launch-and-verify run — and `status=None` to leave the project's
        status untouched.

        Returns:
            The project's session ID if successful, None otherwise
        """
        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return None

        if not self._session_manager or not self._trigger_service:
            logger.error("[LIVING_UI] Session manager or trigger service not bound")
            return None

        if brief is None:
            # The classic build instruction.
            features_str = (
                ", ".join(project.features) if project.features else "None specified"
            )
            from agent_core.core.prompts.application import LIVING_UI_TASK_INSTRUCTION

            brief = LIVING_UI_TASK_INSTRUCTION.format(
                project_id=project.id,
                project_name=project.name,
                description=project.description,
                features=features_str,
                theme=project.theme,
                project_path=project.path,
            )

        try:
            session = self.ensure_project_session(project)
            if not session:
                raise RuntimeError("could not create project session")

            if status:
                self.update_project_status(project_id, status)

            from app.triggers import TriggerSource, TriggerSpec

            await self._trigger_service.emit(
                TriggerSpec(
                    source=trigger_source or TriggerSource.LIVING_UI_DEV,
                    description=brief,
                    priority=50,
                    session_id=session.id,
                    payload={
                        "project_id": project_id,
                        # This run writes code, so it needs a Living UI skill —
                        # loaded now, unloaded when the run ends.
                        "workflow_skills": [workflow_skill],
                    },
                )
            )

            logger.info(
                f"[LIVING_UI] Queued {workflow_skill} run in session {session.id} "
                f"for project {project_id}"
            )
            return session.id

        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to start development run: {e}")
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
                project.process = None
                actually_alive = False

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

    async def _wait_for_server(self, port: int, timeout: int = 10) -> bool:
        """Wait for a server to start listening on a port."""
        for _ in range(timeout * 2):
            if self._is_port_in_use(port):
                return True
            await asyncio.sleep(0.5)
        return False

    async def _wait_for_health_check(self, url: str, timeout: int = 15) -> bool:
        """Wait for a server's health endpoint to respond with HTTP 200."""
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
        for project_id, project in self.projects.items():
            if project.bridge_token and project.bridge_token == token:
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

    async def stop_project(self, project_id: str) -> bool:
        """
        Stop a running Living UI project (its single PocketBase process).

        Args:
            project_id: Project ID to stop

        Returns:
            True if stop was successful
        """
        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return False

        # Stop the app process
        if project.process:
            self._terminate_process(project.process)
            project.process = None

        # Also kill by port in case process reference is stale
        if project.port and self._is_port_in_use(project.port):
            self._kill_process_on_port(project.port)

        project.url = None

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

        # Stop if running
        if project.status == "running":
            await self.stop_project(project_id)

        # Release ports
        if project.port:
            self._release_port(project.port)
        if project.backend_port:
            self._release_port(project.backend_port)

        # Delete project directory. SAFETY: only ever delete inside the
        # Living UI workspace. A never-adopted placeholder has path "" and
        # Path("") == Path(".") == the process CWD — i.e. the CraftBot repo
        # root; rmtree on it wiped the entire working tree twice
        # (2026-07-25/26) before this guard existed.
        if project.path:
            project_path = Path(project.path).resolve()
            living_root = self.living_ui_dir.resolve()
            if living_root in project_path.parents:
                if project_path.exists():
                    try:
                        shutil.rmtree(project_path)
                    except Exception as e:
                        logger.error(
                            f"[LIVING_UI] Failed to delete project directory: {e}"
                        )
            else:
                logger.error(
                    f"[LIVING_UI] REFUSED to delete project directory outside "
                    f"the Living UI workspace: {project.path!r}"
                )

        # Delete the project's dedicated session (triggers + streams + rows)
        if project.session_id:
            try:
                if self._trigger_service:
                    await self._trigger_service.cancel_sessions([project.session_id])
                if self._session_manager:
                    self._session_manager.delete_session(project.session_id)
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Failed to delete project session "
                    f"{project.session_id}: {e}"
                )

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
            ".snapshots",  # pristine pb_data baseline — local delivery state
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

    def get_project_url(self, project_id: str) -> Optional[str]:
        """Get the URL for a running project."""
        project = self.projects.get(project_id)
        if project and project.status == "running":
            return project.url
        return None

    # ------------------------------------------------------------------
    # LAN & Tunnel sharing
    # ------------------------------------------------------------------

    @staticmethod
    def get_lan_ip() -> Optional[str]:
        """Get the machine's LAN IP address."""
        try:
            # Connect to a public IP to determine the right interface
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return None

    def get_lan_url(self, project_id: str) -> Optional[str]:
        """Get the LAN-accessible URL for a running project.

        Uses the backend port since the backend also serves the frontend
        static files — single port for everything.
        """
        project = self.projects.get(project_id)
        if not project or project.status != "running":
            return None
        # Prefer backend port (serves both API + frontend static files)
        port = project.backend_port or project.port
        if not port:
            return None
        ip = self.get_lan_ip()
        if not ip or ip.startswith("127."):
            return None
        return f"http://{ip}:{port}"

    # Cloudflared binary download URLs per platform
    _CLOUDFLARED_URLS = {
        "win32": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
        "darwin": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
        "linux": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    }

    def _get_cloudflared_path(self) -> Optional[str]:
        """Find cloudflared — check PATH first, then our local bin directory."""
        system_path = shutil.which("cloudflared")
        if system_path:
            return system_path
        # Check our local bin
        import sys

        ext = ".exe" if sys.platform == "win32" else ""
        local_bin = Path(__file__).parent.parent / "bin" / f"cloudflared{ext}"
        if local_bin.exists():
            return str(local_bin)
        return None

    async def _ensure_cloudflared(self) -> Optional[str]:
        """Find cloudflared or auto-install it. Returns the binary path or None."""
        path = self._get_cloudflared_path()
        if path:
            return path

        logger.info("[LIVING_UI] cloudflared not found, auto-installing...")
        import sys
        import urllib.request

        platform_key = sys.platform
        if platform_key not in self._CLOUDFLARED_URLS:
            logger.error(f"[LIVING_UI] Unsupported platform: {platform_key}")
            return None

        bin_dir = Path(__file__).parent.parent / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        ext = ".exe" if platform_key == "win32" else ""
        target = bin_dir / f"cloudflared{ext}"

        try:
            url = self._CLOUDFLARED_URLS[platform_key]
            req = urllib.request.Request(url, headers={"User-Agent": "CraftBot"})
            resp = urllib.request.urlopen(req, timeout=60)

            if platform_key == "darwin":
                import tarfile
                import io

                with tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if "cloudflared" in member.name:
                            f = tar.extractfile(member)
                            if f:
                                target.write_bytes(f.read())
                                break
            else:
                target.write_bytes(resp.read())

            if platform_key != "win32":
                target.chmod(0o755)

            logger.info(f"[LIVING_UI] cloudflared installed at {target}")
            return str(target)
        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to download cloudflared: {e}")
            if target.exists():
                target.unlink()
            return None

    async def start_tunnel(
        self, project_id: str, provider: str = "cloudflared"
    ) -> Optional[str]:
        """Start a cloudflare tunnel for remote access. Returns the public URL."""
        logger.info(f"[LIVING_UI] start_tunnel called for {project_id}")
        project = self.projects.get(project_id)
        if not project or project.status != "running":
            logger.warning(
                f"[LIVING_UI] Cannot start tunnel: project={project is not None}, status={project.status if project else 'N/A'}"
            )
            return None

        logger.info("[LIVING_UI] Stopping any existing tunnel...")
        await self.stop_tunnel(project_id)

        # Only kill orphans on first tunnel start (no other tunnels active)
        other_tunnels = any(
            p.tunnel_process is not None and p.id != project_id
            for p in self.projects.values()
        )
        if not other_tunnels:
            logger.info(
                "[LIVING_UI] No other tunnels active, cleaning orphan cloudflared processes..."
            )
            try:
                if os.name == "nt":
                    subprocess.run(
                        [
                            "powershell",
                            "-Command",
                            "Stop-Process -Name cloudflared -Force -ErrorAction SilentlyContinue",
                        ],
                        capture_output=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW
                        if hasattr(subprocess, "CREATE_NO_WINDOW")
                        else 0,
                    )
                else:
                    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
                await asyncio.sleep(1)
            except Exception:
                pass

        port = project.backend_port or project.port
        if not port:
            return None

        cloudflared = await self._ensure_cloudflared()
        if not cloudflared:
            logger.error("[LIVING_UI] cloudflared binary not found")
            return None

        logger.info(
            f"[LIVING_UI] Starting cloudflared: {cloudflared} tunnel --url http://localhost:{port}"
        )
        proc = subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        logger.info(f"[LIVING_UI] cloudflared started, PID={proc.pid}, parsing URL...")
        url = await self._parse_cloudflare_url(proc)
        logger.info(f"[LIVING_UI] cloudflared URL parse result: {url}")

        if url:
            project.tunnel_process = proc
            project.tunnel_url = url
            self._save_projects()
            logger.info(f"[LIVING_UI] Tunnel started for {project.name}: {url}")
            return url
        else:
            self._terminate_process(proc)
            logger.error("[LIVING_UI] Failed to get tunnel URL")
            return None

    async def stop_tunnel(self, project_id: str) -> None:
        """Stop the tunnel for a project."""
        project = self.projects.get(project_id)
        if not project:
            return
        if project.tunnel_process:
            self._terminate_process(project.tunnel_process)
            project.tunnel_process = None
        project.tunnel_url = None
        self._save_projects()
        logger.info(f"[LIVING_UI] Tunnel stopped for {project.name}")

    async def _parse_cloudflare_url(
        self, proc: subprocess.Popen, timeout: int = 30
    ) -> Optional[str]:
        """Parse the public URL from cloudflared output."""
        import re
        import threading

        url_result = [None]
        pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        def _read_stream(stream):
            try:
                for line_bytes in stream:
                    text = line_bytes.decode("utf-8", errors="replace")
                    match = pattern.search(text)
                    if match:
                        url_result[0] = match.group(0)
                        return
            except Exception:
                pass

        # Read both stdout and stderr in parallel threads
        t1 = threading.Thread(target=_read_stream, args=(proc.stdout,), daemon=True)
        t2 = threading.Thread(target=_read_stream, args=(proc.stderr,), daemon=True)
        t1.start()
        t2.start()

        # Wait for either thread to find the URL
        deadline = time.time() + timeout
        while time.time() < deadline and url_result[0] is None:
            if proc.poll() is not None and url_result[0] is None:
                break
            await asyncio.sleep(0.5)

        if url_result[0]:
            logger.info(f"[LIVING_UI] Parsed cloudflare URL: {url_result[0]}")
        else:
            logger.error("[LIVING_UI] Failed to parse cloudflare URL within timeout")

        return url_result[0]

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
