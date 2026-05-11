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
    from app.task.task_manager import TaskManager
    from app.trigger import TriggerQueue


@dataclass
class LivingUIProject:
    """Represents a Living UI project."""
    id: str
    name: str
    description: str
    path: str
    status: str = 'created'  # created, creating, ready, running, stopped, error
    port: Optional[int] = None  # Frontend port
    backend_port: Optional[int] = None  # Backend API port
    url: Optional[str] = None  # Frontend URL
    backend_url: Optional[str] = None  # Backend API URL
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    features: List[str] = field(default_factory=list)
    theme: str = 'system'
    error: Optional[str] = None
    task_id: Optional[str] = None
    auto_launch: bool = False  # Auto-launch on CraftBot startup
    log_cleanup: bool = True  # Clean logs on restart
    project_type: str = 'native'  # 'native' or 'external'
    app_runtime: Optional[str] = None  # 'go', 'node', 'python', 'rust', 'docker', 'static'
    bridge_token: str = ""  # Ephemeral token for integration bridge (NOT serialized)
    tunnel_url: Optional[str] = None  # Public tunnel URL (NOT serialized)
    tunnel_process: Optional[subprocess.Popen] = None  # Tunnel process (NOT serialized)
    process: Optional[subprocess.Popen] = None  # Frontend process
    backend_process: Optional[subprocess.Popen] = None  # Backend process
    app_process: Optional[subprocess.Popen] = None  # Single process for external apps

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'path': self.path,
            'status': self.status,
            'port': self.port,
            'backendPort': self.backend_port,
            'url': self.url,
            'backendUrl': self.backend_url,
            'createdAt': int(self.created_at * 1000),  # Convert to JS timestamp
            'features': self.features,
            'theme': self.theme,
            'error': self.error,
            'autoLaunch': self.auto_launch,
            'logCleanup': self.log_cleanup,
            'projectType': self.project_type,
            'appRuntime': self.app_runtime,
            'tunnelUrl': self.tunnel_url,
        }


class LivingUIManager:
    """Manages Living UI project lifecycle."""

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
        self._projects_file = self.workspace_root / 'living_ui_projects.json'

        # Task and trigger management (set via bind_task_manager)
        self._task_manager: Optional["TaskManager"] = None
        self._trigger_queue: Optional["TriggerQueue"] = None

        # Watchdog state
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_running: bool = False

        # Ensure workspace directory exists
        self.living_ui_dir = self.workspace_root / 'living_ui'
        self.living_ui_dir.mkdir(parents=True, exist_ok=True)

        # Load existing projects
        self._load_projects()

    def bind_task_manager(
        self,
        task_manager: "TaskManager",
        trigger_queue: "TriggerQueue"
    ) -> None:
        """
        Bind the task manager and trigger queue for creating development tasks.

        Args:
            task_manager: TaskManager instance for creating tasks
            trigger_queue: TriggerQueue instance for firing triggers
        """
        self._task_manager = task_manager
        self._trigger_queue = trigger_queue
        logger.info("[LIVING_UI] Task manager and trigger queue bound")

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
                    if project.status != 'running':
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
                        if project.backend_process is None and not self._is_port_in_use(project.backend_port):
                            backend_dead = True
                    if not frontend_dead and project.port:
                        if project.process is None and not self._is_port_in_use(project.port):
                            frontend_dead = True

                    if not backend_dead and not frontend_dead:
                        # Everything healthy, reset retry counter
                        if project_id in retry_counts:
                            logger.info(f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) recovered")
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
                            logger.error(f"[LIVING_UI:WATCHDOG] Backend restart failed for {project_id}")
                            restart_ok = False

                    if frontend_dead:
                        project.process = None
                        success = await self._relaunch_frontend(project_id)
                        if not success:
                            logger.error(f"[LIVING_UI:WATCHDOG] Frontend restart failed for {project_id}")
                            restart_ok = False

                    if restart_ok:
                        logger.info(f"[LIVING_UI:WATCHDOG] {project.name} ({project_id}) restarted successfully")
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
            frontend_log_handle = open(frontend_log, 'a', encoding='utf-8')
            frontend_log_handle.write(
                f"\n{'='*60}\n[{datetime.now().isoformat()}] "
                f"Relaunching frontend on port {port}\n{'='*60}\n"
            )
            frontend_log_handle.flush()

            process = subprocess.Popen(
                ['npm', 'run', 'preview', '--', '--port', str(port)],
                cwd=str(project_path),
                stdout=frontend_log_handle,
                stderr=frontend_log_handle,
                shell=True if os.name == 'nt' else False,
            )

            project.process = process

            server_ready = await self._wait_for_server(port, timeout=15)
            if not server_ready:
                frontend_log_handle.flush()
                try:
                    recent = frontend_log.read_text(encoding='utf-8')[-500:]
                except Exception:
                    recent = ''
                logger.error(f"[LIVING_UI] Frontend relaunch failed for {project_id}. Log tail:\n{recent}")
                if process.poll() is None:
                    process.terminate()
                project.process = None
                frontend_log_handle.close()
                return False

            project.url = f"http://localhost:{port}"
            logger.info(f"[LIVING_UI] Frontend relaunched for {project_id} on port {port}")
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

        # Backend logs
        backend_subprocess_log = project_path / 'backend' / 'logs' / 'subprocess_output.log'
        if backend_subprocess_log.exists():
            try:
                content = backend_subprocess_log.read_text(encoding='utf-8')
                log_snippets.append(f"=== Backend subprocess log (last 1000 chars) ===\n{content[-1000:]}")
            except Exception:
                pass

        # Backend app-level logs (most recent session)
        backend_logs_dir = project_path / 'backend' / 'logs'
        if backend_logs_dir.exists():
            session_logs = sorted(backend_logs_dir.glob("backend_*.log"), reverse=True)
            if session_logs:
                try:
                    content = session_logs[0].read_text(encoding='utf-8')
                    log_snippets.append(f"=== Backend session log (last 1000 chars) ===\n{content[-1000:]}")
                except Exception:
                    pass

        # Health status
        health_status_file = project_path / 'backend' / 'logs' / 'health_status.json'
        if health_status_file.exists():
            try:
                log_snippets.append(f"=== Health status ===\n{health_status_file.read_text(encoding='utf-8')}")
            except Exception:
                pass

        # Frontend logs (most recent session)
        frontend_logs_dir = project_path / 'logs'
        if frontend_logs_dir.exists():
            frontend_logs = sorted(frontend_logs_dir.glob("frontend_*.log"), reverse=True)
            if frontend_logs:
                try:
                    content = frontend_logs[0].read_text(encoding='utf-8')
                    log_snippets.append(f"=== Frontend log (last 1000 chars) ===\n{content[-1000:]}")
                except Exception:
                    pass

        crash_str = " and ".join(crash_targets)
        all_logs = "\n\n".join(log_snippets) if log_snippets else "(no logs found)"

        # Update project status
        project.status = 'error'
        project.error = f'{crash_str} crashed after {len(self.WATCHDOG_RETRY_DELAYS)} restart attempts'
        project.process = None
        project.backend_process = None
        self._save_projects()

        # Create agent task to investigate and fix
        if not self._task_manager or not self._trigger_queue:
            logger.error("[LIVING_UI:WATCHDOG] Cannot escalate — task manager or trigger queue not bound")
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
The backend is a FastAPI app at {project.path}/backend/main.py
The frontend is a Vite+React app at {project.path}/frontend/"""

        try:
            task_id = self._task_manager.create_task(
                task_name=f"Fix crashed Living UI: {project.name}",
                task_instruction=task_instruction,
                mode="complex",
                action_sets=["file_operations", "code_execution", "living_ui", "core"],
                selected_skills=["living-ui-creator"],
            )

            trigger = Trigger(
                fire_at=time.time(),
                priority=30,  # Higher priority than normal creation tasks
                next_action_description=f"[Living UI] Fix crash: {project.name}",
                session_id=task_id,
                payload={
                    "type": "living_ui_crash_fix",
                    "project_id": project_id,
                },
            )
            await self._trigger_queue.put(trigger)

            project.task_id = task_id
            self._save_projects()
            logger.info(
                f"[LIVING_UI:WATCHDOG] Created fix task {task_id} for {project.name} ({project_id})"
            )
        except Exception as e:
            logger.error(f"[LIVING_UI:WATCHDOG] Failed to create fix task: {e}")

    def _load_projects(self) -> None:
        """Load projects from persistent storage."""
        if self._projects_file.exists():
            try:
                with open(self._projects_file, 'r') as f:
                    data = json.load(f)
                    for project_data in data.get('projects', []):
                        project = LivingUIProject(
                            id=project_data['id'],
                            name=project_data['name'],
                            description=project_data.get('description', ''),
                            path=project_data['path'],
                            status=project_data.get('status', 'stopped'),
                            port=project_data.get('port'),
                            backend_port=project_data.get('backendPort'),
                            created_at=project_data.get('createdAt', datetime.now().timestamp()) / 1000,
                            features=project_data.get('features', []),
                            theme=project_data.get('theme', 'system'),
                            auto_launch=project_data.get('autoLaunch', False),
                            log_cleanup=project_data.get('logCleanup', True),
                            project_type=project_data.get('projectType', 'native'),
                            app_runtime=project_data.get('appRuntime'),
                        )
                        # Check if saved tunnel URL is still reachable
                        saved_tunnel = project_data.get('tunnelUrl')
                        if saved_tunnel:
                            try:
                                import urllib.request
                                req = urllib.request.Request(saved_tunnel, method='HEAD')
                                urllib.request.urlopen(req, timeout=3)
                                project.tunnel_url = saved_tunnel
                                logger.info(f"[LIVING_UI] Tunnel still active for '{project.name}': {saved_tunnel}")
                            except Exception:
                                logger.info(f"[LIVING_UI] Tunnel expired for '{project.name}', clearing")
                                project.tunnel_url = None
                        # Reset status to stopped for all loaded projects
                        project.status = 'stopped' if project.status == 'running' else project.status
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
            data = {
                'projects': [p.to_dict() for p in self.projects.values()]
            }
            with open(self._projects_file, 'w') as f:
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
                logger.warning(f"[LIVING_UI] Port {port} in use by external process, skipping")
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
            return s.connect_ex(('localhost', port)) == 0

    def _get_pids_on_ports(self, ports_to_check: Optional[Set[int]] = None) -> Dict[int, str]:
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

        if os.name == 'nt':
            # Windows: run netstat once and parse all results
            try:
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True,
                    shell=True,
                    timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            addr = parts[1]
                            pid = parts[-1]
                            if ':' in addr:
                                try:
                                    port = int(addr.split(':')[-1])
                                    # Check if port is in range and optionally in the filter set
                                    if self._port_range[0] <= port <= self._port_range[1]:
                                        if ports_to_check is None or port in ports_to_check:
                                            port_pids[port] = pid
                                except ValueError:
                                    pass
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to get ports via netstat: {e}")
        else:
            # Linux/Mac: use lsof
            try:
                result = subprocess.run(
                    ['lsof', '-i', '-P', '-n'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'LISTEN' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            # PID is typically the second column
                            pid = parts[1]
                            # Find the port in the line
                            for part in parts:
                                if ':' in part:
                                    try:
                                        port = int(part.split(':')[-1])
                                        if self._port_range[0] <= port <= self._port_range[1]:
                                            if ports_to_check is None or port in ports_to_check:
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
            if os.name == 'nt':
                subprocess.run(
                    ['taskkill', '/F', '/PID', pid],
                    capture_output=True,
                    shell=True
                )
            else:
                subprocess.run(['kill', '-9', pid], capture_output=True)
            return True
        except Exception as e:
            logger.warning(f"[LIVING_UI] Failed to kill process {pid}: {e}")
            return False

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
                req = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status == 200:
                        return True
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
                pass
            await asyncio.sleep(0.5)
        return False

    async def _run_backend_tests(self, project_id: str, mode: str, port: int = 0) -> bool:
        """
        Run backend tests using test_runner.py.

        Args:
            project_id: Project ID to test
            mode: "internal" (pre-server) or "external" (post-server HTTP tests)
            port: Backend port (required for external mode)

        Returns:
            True if all tests pass, False otherwise
        """
        project = self.projects.get(project_id)
        if not project:
            return False

        backend_path = Path(project.path) / 'backend'
        test_runner = backend_path / 'test_runner.py'
        if not test_runner.exists():
            logger.warning(f"[LIVING_UI] No test_runner.py for {project_id}, skipping {mode} tests")
            return True  # No tests = pass (backwards compat with older projects)

        logger.info(f"[LIVING_UI] Running {mode} tests for {project.name} ({project_id})...")

        cmd = [sys.executable, str(test_runner), f'--{mode}']
        if mode == 'external' and port:
            cmd.extend(['--port', str(port)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(backend_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            stdout_str = stdout.decode('utf-8', errors='replace').strip()
            stderr_str = stderr.decode('utf-8', errors='replace').strip()

            if stderr_str:
                # stderr contains the test runner's logging output
                for line in stderr_str.split('\n')[-20:]:  # Last 20 lines
                    logger.debug(f"[LIVING_UI:TEST] {line}")

            if proc.returncode == 0:
                logger.info(f"[LIVING_UI] {mode.capitalize()} tests passed for {project_id}")
                return True
            else:
                # Read the detailed results file
                if mode == 'internal':
                    results_file = backend_path / 'logs' / 'test_discovery.json'
                else:
                    results_file = backend_path / 'logs' / 'test_results.json'

                error_details = ''
                if results_file.exists():
                    try:
                        results = json.loads(results_file.read_text(encoding='utf-8'))
                        errors = results.get('errors', [])
                        error_details = '; '.join(
                            f"[{e.get('test', '?')}] {e.get('error', '?')}" for e in errors[:5]
                        )
                    except Exception:
                        pass

                logger.error(
                    f"[LIVING_UI] {mode.capitalize()} tests failed for {project_id}: {error_details or stderr_str[-500:]}"
                )
                return False

        except asyncio.TimeoutError:
            logger.error(f"[LIVING_UI] {mode.capitalize()} tests timed out for {project_id}")
            return False
        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to run {mode} tests for {project_id}: {e}")
            return False

    # ========================================================================
    # Manifest-driven launch pipeline
    # ========================================================================

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
            return {"status": "error", "step": "setup", "errors": [f"Project not found: {project_id}"]}

        project_path = Path(project.path)
        if not project_path.exists():
            return {"status": "error", "step": "setup", "errors": [f"Project path not found: {project.path}"]}

        # Load manifest
        manifest_path = project_path / 'config' / 'manifest.json'
        if not manifest_path.exists():
            return {"status": "error", "step": "setup", "errors": ["config/manifest.json not found"]}

        try:
            # Ensure ports are allocated and available
            if not project.port:
                project.port = self._allocate_port()
            if not project.backend_port:
                project.backend_port = self._allocate_port()

            # Read manifest and resolve ports — always use project's current ports
            # regardless of what's hardcoded in the manifest file
            manifest_raw = manifest_path.read_text(encoding='utf-8')

            # Extract old ports from manifest to do replacement
            manifest_tmp = json.loads(manifest_raw)
            old_ports = manifest_tmp.get('ports', {})
            old_frontend = str(old_ports.get('frontend', old_ports.get('app', '')))
            old_backend = str(old_ports.get('backend', ''))

            # Replace old ports with current allocated ports in manifest and source files
            if old_frontend and old_frontend != str(project.port):
                manifest_raw = manifest_raw.replace(old_frontend, str(project.port))
            if old_backend and old_backend != str(project.backend_port):
                manifest_raw = manifest_raw.replace(old_backend, str(project.backend_port))

            manifest = json.loads(manifest_raw)

            # Write updated manifest back to disk so frontend can read correct ports
            if old_frontend != str(project.port) or old_backend != str(project.backend_port):
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                logger.info(f"[LIVING_UI:PIPELINE] Updated manifest ports: frontend={project.port}, backend={project.backend_port}")
        except Exception as e:
            return {"status": "error", "step": "setup", "errors": [f"Failed to parse manifest: {e}"]}

        pipeline = manifest.get('pipeline', {})
        if not pipeline:
            return {"status": "error", "step": "setup", "errors": ["No pipeline defined in manifest"]}

        logger.info(f"[LIVING_UI:PIPELINE] Starting launch pipeline for {project.name} ({project_id})")

        # Ensure index.html has the CraftBot theme sync listener (self-healing for older installs)
        self._patch_theme_listener(project_path)

        # Check for single-process mode (external apps)
        app_cfg = pipeline.get('app')
        if app_cfg:
            return await self._launch_single_process(project_id, project, project_path, app_cfg)

        # Stop any existing processes from previous launch attempts
        # This prevents orphan uvicorn/vite processes accumulating on repeated calls
        if project.backend_process and project.backend_process.poll() is None:
            logger.info(f"[LIVING_UI:PIPELINE] Killing existing backend process before relaunch")
            project.backend_process.terminate()
            project.backend_process = None
        if project.process and project.process.poll() is None:
            logger.info(f"[LIVING_UI:PIPELINE] Killing existing frontend process before relaunch")
            project.process.terminate()
            project.process = None

        # Check if source files changed since last successful launch
        files_changed = self._has_files_changed(project_path)

        if not files_changed:
            logger.info(f"[LIVING_UI:PIPELINE] No source changes detected — skipping tests/build, starting servers directly")
            # Fast path — just start servers
            return await self._launch_servers_only(project_id, project, project_path, pipeline)

        # Clean up old log files so each launch starts fresh (if enabled)
        if project.log_cleanup:
            self._cleanup_project_logs(project_path)

        # ================================================================
        # PHASE 1: Parallel validation (collect ALL errors before starting)
        # ================================================================

        backend_cfg = pipeline.get('backend')
        frontend_cfg = pipeline.get('frontend')

        # Run backend and frontend validation tracks in parallel
        backend_task = None
        frontend_task = None

        if backend_cfg:
            backend_cwd = project_path / backend_cfg.get('cwd', 'backend')
            backend_task = asyncio.create_task(
                self._validate_backend_track(project_id, project_path, backend_cfg, backend_cwd)
            )

        if frontend_cfg:
            frontend_cwd = project_path / frontend_cfg.get('cwd', '.')
            if str(frontend_cwd) == '.':
                frontend_cwd = project_path
            frontend_task = asyncio.create_task(
                self._validate_frontend_track(project_id, frontend_cfg, frontend_cwd)
            )

        # Wait for both tracks to complete
        all_errors: List[str] = []

        if backend_task:
            backend_errors = await backend_task
            all_errors.extend(backend_errors)

        if frontend_task:
            frontend_errors = await frontend_task
            all_errors.extend(frontend_errors)

        # If ANY errors from either track, return them all at once
        if all_errors:
            logger.error(f"[LIVING_UI:PIPELINE] Validation failed with {len(all_errors)} error(s)")
            for err in all_errors[:10]:
                logger.error(f"[LIVING_UI:PIPELINE]   {err}")
            project.status = 'error'
            project.error = f'{len(all_errors)} validation error(s)'
            self._save_projects()
            return {"status": "error", "step": "validation", "errors": all_errors}

        logger.info(f"[LIVING_UI:PIPELINE] All validation passed, starting servers...")

        # ================================================================
        # PHASE 2: Start servers (sequential — needs running processes)
        # ================================================================

        # --- Start backend ---
        if backend_cfg:
            backend_cwd = project_path / backend_cfg.get('cwd', 'backend')
            backend_port = project.backend_port
            if not backend_port:
                backend_port = self._allocate_port()
                project.backend_port = backend_port

            if not await self._ensure_port_available(backend_port):
                return {"status": "error", "step": "backend.port", "errors": [f"Port {backend_port} is occupied and could not be freed"]}

            start_cmd = backend_cfg.get('start', '')
            if not start_cmd:
                return {"status": "error", "step": "backend.start", "errors": ["No start command in manifest"]}

            logs_dir = backend_cwd / 'logs'
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / 'subprocess_output.log'

            # Generate bridge token for integration proxy
            from uuid import uuid4
            project.bridge_token = str(uuid4())

            backend_process = self._start_process(backend_cwd, start_cmd, log_file, port=backend_port, project=project)
            project.backend_process = backend_process
            logger.info(f"[LIVING_UI:PIPELINE] Backend starting on port {backend_port}")

            # Health check
            health_url = backend_cfg.get('health')
            if health_url:
                healthy = await self._wait_for_health_check(health_url, timeout=20)
                if not healthy:
                    log_tail = self._read_log_tail(log_file, 1000)
                    if backend_process.poll() is not None:
                        err = f"Backend process exited with code {backend_process.returncode}"
                    else:
                        err = f"Backend not responding at {health_url}"
                        backend_process.terminate()
                    project.backend_process = None
                    return {"status": "error", "step": "backend.health", "errors": [err, log_tail]}

            project.backend_url = f"http://localhost:{backend_port}"
            logger.info(f"[LIVING_UI:PIPELINE] Backend healthy on port {backend_port}")

            # Post-start tests (external smoke tests)
            for test in backend_cfg.get('post_start_tests', []):
                result = await self._run_pipeline_command(
                    backend_cwd, test['command'], step_name=f"backend.post_start.{test['name']}"
                )
                if result["status"] == "error" and test.get('required', True):
                    errors = self._collect_test_errors(project_path, test['name']) or result["errors"]
                    await self.stop_backend(project_id)
                    return {"status": "error", "step": f"backend.post_start.{test['name']}", "errors": errors}

        # --- Start frontend ---
        if frontend_cfg:
            frontend_cwd = project_path / frontend_cfg.get('cwd', '.')
            if str(frontend_cwd) == '.':
                frontend_cwd = project_path

            frontend_port = project.port
            if not frontend_port:
                frontend_port = self._allocate_port()
                project.port = frontend_port

            if not await self._ensure_port_available(frontend_port):
                await self.stop_backend(project_id)
                return {"status": "error", "step": "frontend.port", "errors": [f"Port {frontend_port} is occupied and could not be freed"]}

            start_cmd = frontend_cfg.get('start', '')
            if not start_cmd:
                await self.stop_backend(project_id)
                return {"status": "error", "step": "frontend.start", "errors": ["No start command in manifest"]}

            frontend_log = self._create_frontend_log(project_path)

            frontend_process = self._start_process(frontend_cwd, start_cmd, frontend_log, port=frontend_port)
            project.process = frontend_process
            project.port = frontend_port
            logger.info(f"[LIVING_UI:PIPELINE] Frontend starting on port {frontend_port}")

            server_ready = await self._wait_for_server(frontend_port, timeout=15)
            if not server_ready:
                log_tail = self._read_log_tail(frontend_log, 1000)
                if frontend_process.poll() is not None:
                    err = f"Frontend process exited with code {frontend_process.returncode}"
                else:
                    err = f"Frontend not responding on port {frontend_port}"
                    frontend_process.terminate()
                project.process = None
                await self.stop_backend(project_id)
                return {"status": "error", "step": "frontend.health", "errors": [err, log_tail]}

            project.url = f"http://localhost:{frontend_port}"
            logger.info(f"[LIVING_UI:PIPELINE] Frontend ready on port {frontend_port}")

        # === SUCCESS ===
        project.status = 'running'
        project.error = None
        self._save_projects()
        self._save_launch_timestamp(project_path)

        logger.info(f"[LIVING_UI:PIPELINE] Launch complete for {project.name} ({project_id})")
        if project.url:
            logger.info(f"[LIVING_UI:PIPELINE]   Frontend: {project.url}")
        if project.backend_url:
            logger.info(f"[LIVING_UI:PIPELINE]   Backend: {project.backend_url}")

        return {
            "status": "success",
            "url": project.url,
            "backend_url": project.backend_url,
            "port": project.port,
        }

    async def _launch_servers_only(
        self, project_id: str, project: 'LivingUIProject', project_path: Path, pipeline: dict
    ) -> dict:
        """Fast path: start servers without running tests/build (no source changes detected)."""
        backend_cfg = pipeline.get('backend')
        frontend_cfg = pipeline.get('frontend')

        # Start backend
        if backend_cfg:
            backend_cwd = project_path / backend_cfg.get('cwd', 'backend')
            backend_port = project.backend_port
            if not backend_port:
                backend_port = self._allocate_port()
                project.backend_port = backend_port

            if not await self._ensure_port_available(backend_port):
                return {"status": "error", "step": "backend.port", "errors": [f"Port {backend_port} occupied"]}

            start_cmd = backend_cfg.get('start', '')
            if start_cmd:
                logs_dir = backend_cwd / 'logs'
                logs_dir.mkdir(parents=True, exist_ok=True)
                log_file = logs_dir / 'subprocess_output.log'

                # Generate bridge token for integration proxy
                from uuid import uuid4
                project.bridge_token = str(uuid4())

                backend_process = self._start_process(backend_cwd, start_cmd, log_file, port=backend_port, project=project)
                project.backend_process = backend_process
                logger.info(f"[LIVING_UI:PIPELINE] Backend starting on port {backend_port} (fast)")

                health_url = backend_cfg.get('health')
                if health_url:
                    healthy = await self._wait_for_health_check(health_url, timeout=20)
                    if not healthy:
                        log_tail = self._read_log_tail(log_file, 1000)
                        if backend_process.poll() is not None:
                            err = f"Backend process exited with code {backend_process.returncode}"
                        else:
                            err = f"Backend not responding at {health_url}"
                            backend_process.terminate()
                        project.backend_process = None
                        return {"status": "error", "step": "backend.health", "errors": [err, log_tail]}

                project.backend_url = f"http://localhost:{backend_port}"
                logger.info(f"[LIVING_UI:PIPELINE] Backend healthy on port {backend_port}")

        # Start frontend
        if frontend_cfg:
            frontend_cwd = project_path / frontend_cfg.get('cwd', '.')
            if str(frontend_cwd) == '.':
                frontend_cwd = project_path

            frontend_port = project.port
            if not frontend_port:
                frontend_port = self._allocate_port()
                project.port = frontend_port

            if not await self._ensure_port_available(frontend_port):
                await self.stop_backend(project_id)
                return {"status": "error", "step": "frontend.port", "errors": [f"Port {frontend_port} occupied"]}

            start_cmd = frontend_cfg.get('start', '')
            if start_cmd:
                frontend_log = self._create_frontend_log(project_path)
                frontend_process = self._start_process(frontend_cwd, start_cmd, frontend_log, port=frontend_port)
                project.process = frontend_process
                project.port = frontend_port
                logger.info(f"[LIVING_UI:PIPELINE] Frontend starting on port {frontend_port} (fast)")

                server_ready = await self._wait_for_server(frontend_port, timeout=15)
                if not server_ready:
                    log_tail = self._read_log_tail(frontend_log, 1000)
                    if frontend_process.poll() is not None:
                        err = f"Frontend process exited with code {frontend_process.returncode}"
                    else:
                        err = f"Frontend not responding on port {frontend_port}"
                        frontend_process.terminate()
                    project.process = None
                    await self.stop_backend(project_id)
                    return {"status": "error", "step": "frontend.health", "errors": [err, log_tail]}

                project.url = f"http://localhost:{frontend_port}"
                logger.info(f"[LIVING_UI:PIPELINE] Frontend ready on port {frontend_port}")

        project.status = 'running'
        project.error = None
        self._save_projects()
        self._save_launch_timestamp(project_path)

        logger.info(f"[LIVING_UI:PIPELINE] Fast launch complete for {project.name} ({project_id})")
        return {"status": "success", "url": project.url, "backend_url": project.backend_url, "port": project.port}

    async def _validate_backend_track(
        self, project_id: str, project_path: Path, backend_cfg: dict, backend_cwd: Path
    ) -> List[str]:
        """
        Run backend validation: install → internal tests → unit + compatibility tests (parallel).
        Returns list of error strings (empty = all passed).
        """
        errors: List[str] = []

        # 1. Install
        install_cmd = backend_cfg.get('install')
        if install_cmd and backend_cwd.exists():
            result = await self._run_pipeline_command(backend_cwd, install_cmd, step_name="backend.install")
            if result["status"] == "error":
                errors.append(f"[backend.install] {result['errors'][0] if result.get('errors') else 'install failed'}")
                return errors  # Can't test without dependencies

        # 2. Internal tests (must run first — generates test_discovery.json)
        tests = backend_cfg.get('tests', [])
        internal_tests = [t for t in tests if t['name'] == 'internal']
        other_tests = [t for t in tests if t['name'] != 'internal']

        for test in internal_tests:
            result = await self._run_pipeline_command(
                backend_cwd, test['command'], step_name=f"backend.tests.{test['name']}"
            )
            if result["status"] == "error" and test.get('required', True):
                detailed = self._collect_test_errors(project_path, test['name'])
                errors.extend(detailed or result.get("errors", []))

        # 3. Remaining tests in parallel (unit + compatibility)
        if other_tests:
            parallel_tasks = []
            for test in other_tests:
                parallel_tasks.append(
                    self._run_pipeline_command(
                        backend_cwd, test['command'], step_name=f"backend.tests.{test['name']}"
                    )
                )
            results = await asyncio.gather(*parallel_tasks)

            for test, result in zip(other_tests, results):
                if result["status"] == "error" and test.get('required', True):
                    detailed = self._collect_test_errors(project_path, test['name'])
                    errors.extend(detailed or result.get("errors", []))

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
        install_cmd = frontend_cfg.get('install')
        if install_cmd:
            needs_install = not (frontend_cwd / 'node_modules').exists()
            if needs_install:
                result = await self._run_pipeline_command(frontend_cwd, install_cmd, step_name="frontend.install")
                if result["status"] == "error":
                    errors.append(f"[frontend.install] {result['errors'][0] if result.get('errors') else 'install failed'}")
                    return errors  # Can't build without dependencies

        # 2. Build
        build_cmd = frontend_cfg.get('build')
        if build_cmd:
            result = await self._run_pipeline_command(frontend_cwd, build_cmd, step_name="frontend.build", timeout=240)
            if result["status"] == "error":
                build_errors = result.get("errors", ["build failed"])
                for err in build_errors:
                    errors.append(f"[frontend.build] {err}")

        return errors

    async def _run_pipeline_command(
        self, cwd: Path, command: str, step_name: str, timeout: int = 1200
    ) -> dict:
        """Run a single pipeline command. Returns {"status": "success"} or {"status": "error", ...}."""
        command = self._resolve_python_in_command(command)

        logger.info(f"[LIVING_UI:PIPELINE] [{step_name}] Running: {command}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout_str = stdout.decode('utf-8', errors='replace').strip()
            stderr_str = stderr.decode('utf-8', errors='replace').strip()

            if proc.returncode == 0:
                logger.info(f"[LIVING_UI:PIPELINE] [{step_name}] OK")
                return {"status": "success"}
            else:
                # Combine stdout and stderr for error context
                output = (stderr_str or stdout_str)[-1000:]
                logger.error(f"[LIVING_UI:PIPELINE] [{step_name}] FAILED (exit code {proc.returncode})")
                return {
                    "status": "error",
                    "step": step_name,
                    "errors": [output] if output else [f"Command failed with exit code {proc.returncode}"],
                }
        except asyncio.TimeoutError:
            logger.error(f"[LIVING_UI:PIPELINE] [{step_name}] TIMEOUT ({timeout}s)")
            return {"status": "error", "step": step_name, "errors": [f"Command timed out after {timeout}s"]}
        except Exception as e:
            logger.error(f"[LIVING_UI:PIPELINE] [{step_name}] ERROR: {e}")
            return {"status": "error", "step": step_name, "errors": [str(e)]}

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
                    user, "AppData", "Local", "Programs", "Python",
                    f"Python{ver}", "python.exe"
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
                logger.info(f"[LIVING_UI] Resolved system Python: {path} ({output.strip()})")
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

    def _start_process(
        self, cwd: Path, command: str, log_file: Path, port: int = 0,
        project: "LivingUIProject" = None, extra_env: dict = None,
    ) -> subprocess.Popen:
        """Start a background process with output redirected to a log file."""
        command = self._resolve_python_in_command(command)

        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, 'a', encoding='utf-8')
        log_handle.write(f"\n{'='*60}\n[{datetime.now().isoformat()}] Starting: {command}\n{'='*60}\n")
        log_handle.flush()

        # Build env with integration bridge vars if project provided
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        if project and project.bridge_token:
            bridge_port = int(os.environ.get("BROWSER_PORT", "7926"))
            env["CRAFTBOT_BRIDGE_URL"] = f"http://localhost:{bridge_port}"
            env["CRAFTBOT_BRIDGE_TOKEN"] = project.bridge_token
            logger.info(f"[LIVING_UI] Bridge env injected: URL=http://localhost:{bridge_port}, token={project.bridge_token[:8]}...")
        else:
            logger.warning(f"[LIVING_UI] No bridge token for process: project={'yes' if project else 'no'}, token={'yes' if project and project.bridge_token else 'no'}")

        if os.name == 'nt':
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdout=log_handle,
                stderr=log_handle,
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
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

    def _collect_test_errors(self, project_path: Path, test_name: str) -> List[str]:
        """Read test result JSON files and extract error messages."""
        errors = []
        # Map test names to result files
        file_map = {
            "internal": "test_discovery.json",
            "unit": "test_unit.json",
            "compatibility": "test_compatibility.json",
            "external": "test_results.json",
        }
        result_file = project_path / 'backend' / 'logs' / file_map.get(test_name, f"test_{test_name}.json")
        if result_file.exists():
            try:
                data = json.loads(result_file.read_text(encoding='utf-8'))
                for err in data.get('errors', []):
                    errors.append(f"[{err.get('test', '?')}] {err.get('error', '?')}")
            except Exception:
                pass
        return errors

    @staticmethod
    def _cleanup_project_logs(project_path: Path) -> None:
        """Clean up old log files so each launch/restart starts fresh."""
        log_files_to_clean = [
            project_path / 'backend' / 'logs' / 'subprocess_output.log',
            project_path / 'backend' / 'logs' / 'frontend_console.log',
            project_path / 'backend' / 'logs' / 'test_discovery.json',
            project_path / 'backend' / 'logs' / 'test_unit.json',
            project_path / 'backend' / 'logs' / 'test_compatibility.json',
            project_path / 'backend' / 'logs' / 'test_results.json',
            project_path / 'backend' / 'logs' / 'health_status.json',
            project_path / 'logs' / 'frontend_output.log',  # Legacy non-timestamped
            project_path / 'backend' / 'logs' / 'latest.log',  # Legacy pointer file
        ]
        for log_file in log_files_to_clean:
            try:
                if log_file.exists():
                    log_file.unlink()
            except Exception:
                pass
        # Clean up old session logs — keep only the 5 most recent of each type
        backend_logs_dir = project_path / 'backend' / 'logs'
        if backend_logs_dir.exists():
            session_logs = sorted(backend_logs_dir.glob("backend_*.log"), reverse=True)
            for old_log in session_logs[5:]:
                try:
                    old_log.unlink()
                except Exception:
                    pass
        frontend_logs_dir = project_path / 'logs'
        if frontend_logs_dir.exists():
            session_logs = sorted(frontend_logs_dir.glob("frontend_*.log"), reverse=True)
            for old_log in session_logs[5:]:
                try:
                    old_log.unlink()
                except Exception:
                    pass

        logger.debug(f"[LIVING_UI:PIPELINE] Cleaned up old log files")

    @staticmethod
    def _create_frontend_log(project_path: Path) -> Path:
        """Create a timestamped frontend log file path."""
        logs_dir = project_path / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"frontend_{timestamp}.log"

    @staticmethod
    def _has_files_changed(project_path: Path) -> bool:
        """Check if any source files changed since last successful launch."""
        last_launch_file = project_path / '.last_launch'
        if not last_launch_file.exists():
            return True  # No record = assume changed

        try:
            last_launch_time = last_launch_file.stat().st_mtime
        except Exception:
            return True

        source_extensions = {'.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.html', '.css', '.md'}
        skip_dirs = {'node_modules', '__pycache__', 'dist', 'logs', '.git'}

        for filepath in project_path.rglob('*'):
            if filepath.is_file() and filepath.suffix in source_extensions:
                if any(skip in filepath.parts for skip in skip_dirs):
                    continue
                if filepath.stat().st_mtime > last_launch_time:
                    return True
        return False

    @staticmethod
    def _patch_theme_listener(project_path: Path) -> None:
        """Inject CraftBot theme-sync listener into index.html if not already present."""
        index_html = project_path / 'index.html'
        if not index_html.exists():
            return
        try:
            content = index_html.read_text(encoding='utf-8')
            if 'craftbot-theme-request' in content:
                return  # Already patched
            snippet = (
                '\n    <!-- CraftBot theme sync -->\n'
                '    <script>\n'
                '    (function(){\n'
                '      function applyTheme(t,v){\n'
                '        document.documentElement.setAttribute("data-theme",t||"dark");\n'
                '        if(v&&typeof v==="object"){\n'
                '          var el=document.getElementById("craftbot-theme-vars")||document.createElement("style");\n'
                '          el.id="craftbot-theme-vars";\n'
                '          el.textContent=":root{"+Object.keys(v).map(function(k){return k+":"+v[k];}).join(";")+"}";'
                '\n          if(!document.getElementById("craftbot-theme-vars"))document.head.appendChild(el);\n'
                '        }\n'
                '      }\n'
                '      window.addEventListener("load",function(){\n'
                '        try{window.parent.postMessage({type:"craftbot-theme-request"},"*");}catch(e){}\n'
                '      });\n'
                '      window.addEventListener("message",function(e){\n'
                '        if(e.data&&e.data.type==="craftbot-theme")applyTheme(e.data.theme,e.data.cssVars);\n'
                '      });\n'
                '      var _t="dark";try{var _s=window.parent.localStorage.getItem("craftbot-theme");'
                'if(_s==="light"||_s==="dark")_t=_s;}catch(e){}document.documentElement.setAttribute("data-theme",_t);\n'
                '    })();\n'
                '    </script>\n'
            )
            patched = content.replace('</body>', snippet + '</body>', 1)
            index_html.write_text(patched, encoding='utf-8')
            logger.info(f"[LIVING_UI] Patched theme listener into {index_html}")
        except Exception as e:
            logger.warning(f"[LIVING_UI] Could not patch index.html: {e}")

    @staticmethod
    def _save_launch_timestamp(project_path: Path) -> None:
        """Save current time as last successful launch timestamp."""
        last_launch_file = project_path / '.last_launch'
        try:
            last_launch_file.write_text(datetime.now().isoformat(), encoding='utf-8')
        except Exception:
            pass

    @staticmethod
    def _read_log_tail(log_file: Path, chars: int = 1000) -> str:
        """Read the last N characters of a log file."""
        try:
            content = log_file.read_text(encoding='utf-8')
            return content[-chars:] if len(content) > chars else content
        except Exception:
            return '(could not read log)'

    async def launch_backend(self, project_id: str) -> bool:
        """
        Launch the backend (FastAPI) server for a Living UI project.

        The backend holds all state and persists to SQLite.
        It should be launched before the frontend.

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
        backend_path = project_path / 'backend'

        if not backend_path.exists():
            logger.warning(f"[LIVING_UI] No backend directory for {project_id}")
            return True  # Not an error, just no backend

        # If backend port is occupied, allocate a new one instead of killing
        backend_port = project.backend_port
        if backend_port and self._is_port_in_use(backend_port):
            logger.info(f"[LIVING_UI] Port {backend_port} occupied, allocating a new port...")
            self._release_port(backend_port)
            backend_port = self._allocate_port()
            project.backend_port = backend_port
            logger.info(f"[LIVING_UI] Allocated new backend port: {backend_port}")

        # Allocate port if needed
        if not backend_port:
            backend_port = self._allocate_port()
            project.backend_port = backend_port

        try:
            # Start the FastAPI backend using uvicorn
            logger.info(f"[LIVING_UI] Starting backend for {project_id} on port {backend_port}")

            # Backend has its own file-based logger (logger.py in template),
            # but also capture subprocess stdout/stderr to a fallback log file
            # so we can diagnose startup crashes before the app logger initializes
            logs_dir = backend_path / 'logs'
            logs_dir.mkdir(parents=True, exist_ok=True)
            subprocess_log = logs_dir / 'subprocess_output.log'
            subprocess_log_handle = open(subprocess_log, 'a', encoding='utf-8')
            subprocess_log_handle.write(f"\n{'='*60}\n[{datetime.now().isoformat()}] Starting uvicorn on port {backend_port}\n{'='*60}\n")
            subprocess_log_handle.flush()

            # Generate bridge token for integration proxy
            from uuid import uuid4
            bridge_token = str(uuid4())
            project.bridge_token = bridge_token

            # Build env with integration bridge vars
            bridge_port = int(os.environ.get("BROWSER_PORT", "7926"))
            backend_env = os.environ.copy()
            backend_env["CRAFTBOT_BRIDGE_URL"] = f"http://localhost:{bridge_port}"
            backend_env["CRAFTBOT_BRIDGE_TOKEN"] = bridge_token

            # Use python -m uvicorn to run the backend
            if os.name == 'nt':
                # Windows
                backend_process = subprocess.Popen(
                    [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', str(backend_port)],
                    cwd=str(backend_path),
                    env=backend_env,
                    stdout=subprocess_log_handle,
                    stderr=subprocess_log_handle,
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                )
            else:
                # Linux/Mac
                backend_process = subprocess.Popen(
                    [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', str(backend_port)],
                    cwd=str(backend_path),
                    env=backend_env,
                    stdout=subprocess_log_handle,
                    stderr=subprocess_log_handle,
                )

            project.backend_process = backend_process

            # Wait for health check to pass
            health_url = f"http://localhost:{backend_port}/health"
            logger.info(f"[LIVING_UI] Waiting for backend health check at {health_url}...")
            backend_ready = await self._wait_for_health_check(health_url, timeout=20)

            if not backend_ready:
                # Backend didn't start - read the subprocess log for diagnostics
                subprocess_log_handle.flush()
                try:
                    recent_output = subprocess_log.read_text(encoding='utf-8')[-1000:]
                except Exception:
                    recent_output = '(could not read subprocess log)'
                if backend_process.poll() is not None:
                    logger.error(f"[LIVING_UI] Backend process exited with code {backend_process.returncode}. Log tail:\n{recent_output}")
                else:
                    logger.error(f"[LIVING_UI] Backend not responding on port {backend_port}. Log tail:\n{recent_output}")
                    backend_process.terminate()
                project.backend_process = None
                subprocess_log_handle.close()
                return False

            project.backend_url = f"http://localhost:{backend_port}"
            logger.info(f"[LIVING_UI] Backend started successfully on port {backend_port}")
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

    def _terminate_process(self, process: subprocess.Popen) -> None:
        """Terminate a subprocess, killing the entire process tree on Windows."""
        try:
            if os.name == 'nt':
                # On Windows with shell=True, terminate() only kills cmd.exe,
                # not the child python/uvicorn. Kill the whole tree via taskkill.
                subprocess.run(
                    ['taskkill', '/T', '/F', '/PID', str(process.pid)],
                    capture_output=True, shell=True
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
        if os.name != 'nt':
            # Linux/Mac: use lsof and kill
            try:
                result = subprocess.run(
                    ['lsof', '-ti', f':{port}'],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        subprocess.run(['kill', '-9', pid], capture_output=True)
                    logger.info(f"[LIVING_UI] Killed process(es) on port {port}")
                    return True
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to kill process on port {port}: {e}")
            return False
        else:
            # Windows: use netstat and taskkill
            try:
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True,
                    shell=True
                )
                killed = False
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            # /T kills entire process tree (shell + child processes)
                            subprocess.run(
                                ['taskkill', '/T', '/F', '/PID', pid],
                                capture_output=True,
                                shell=True
                            )
                            logger.info(f"[LIVING_UI] Killed process tree {pid} on port {port}")
                            killed = True
                if killed:
                    return True
            except Exception as e:
                logger.warning(f"[LIVING_UI] Failed to kill process on port {port}: {e}")
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

        # 3. Reset all project statuses to 'stopped' and clear process references
        for project in self.projects.values():
            if project.status == 'running':
                project.status = 'stopped'
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
                    logger.warning(f"[LIVING_UI] Failed to delete orphan folder {folder}: {e}")

        return orphan_count

    def _generate_id(self) -> str:
        """Generate a unique project ID."""
        return str(uuid.uuid4())[:8]

    def _sanitize_name(self, name: str) -> str:
        """Sanitize project name for use in file paths."""
        # Replace spaces and special characters
        sanitized = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)
        return sanitized.lower()

    async def create_project(
        self,
        name: str,
        description: str,
        features: List[str] = None,
        data_source: Optional[str] = None,
        theme: str = 'system'
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
        self._replace_placeholders(project_path, {
            '{{PROJECT_ID}}': project_id,
            '{{PROJECT_NAME}}': name,
            '{{PROJECT_DESCRIPTION}}': description,
            '{{PORT}}': str(frontend_port),
            '{{BACKEND_PORT}}': str(backend_port),
            '{{THEME}}': theme,
            '{{CREATED_AT}}': datetime.now().isoformat(),
            '{{FEATURES}}': ', '.join(features or []),
        })

        # Create project instance
        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(project_path),
            status='created',
            port=frontend_port,
            backend_port=backend_port,
            features=features or [],
            theme=theme,
        )

        self.projects[project_id] = project
        self._save_projects()

        logger.info(f"[LIVING_UI] Created project: {name} ({project_id})")
        return project

    def _replace_placeholders(self, directory: Path, replacements: Dict[str, str]) -> None:
        """Replace placeholders in all text files in directory."""
        text_extensions = {'.ts', '.tsx', '.js', '.jsx', '.json', '.html', '.css', '.md', '.py', '.txt', '.env'}

        for filepath in directory.rglob('*'):
            if filepath.is_file() and filepath.suffix in text_extensions:
                try:
                    content = filepath.read_text(encoding='utf-8')
                    modified = False
                    for placeholder, value in replacements.items():
                        if placeholder in content:
                            content = content.replace(placeholder, value)
                            modified = True
                    if modified:
                        filepath.write_text(content, encoding='utf-8')
                except Exception as e:
                    logger.warning(f"[LIVING_UI] Failed to process {filepath}: {e}")

    async def install_from_marketplace(
        self,
        app_id: str,
        app_name: str,
        app_description: str,
        custom_fields: Optional[Dict[str, str]] = None,
        repo_url: str = "https://github.com/CraftOS-dev/living-ui-marketplace",
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

        project_id = self._generate_id()
        sanitized_name = self._sanitize_name(app_name)
        project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

        try:
            # Download the repo as a zip
            # GitHub API: /{owner}/{repo}/zipball/main
            parts = repo_url.rstrip('/').split('/')
            owner = parts[-2]
            repo = parts[-1]
            zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"

            logger.info(f"[LIVING_UI:MARKETPLACE] Downloading {app_id} from {zip_url}")

            import ssl, certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(zip_url, headers={'User-Agent': 'CraftBot'})
            response = urllib.request.urlopen(req, timeout=60, context=ssl_ctx)
            zip_data = response.read()

            # Extract just the app folder from the zip
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                # GitHub zips have a root folder like "repo-main/"
                root_prefix = None
                app_prefix = None

                for name in zf.namelist():
                    if root_prefix is None:
                        root_prefix = name.split('/')[0] + '/'
                    # Look for the app folder: root/{app_id}/
                    if f'/{app_id}/' in name:
                        if app_prefix is None:
                            # Find the prefix up to and including the app folder
                            idx = name.index(f'{app_id}/')
                            app_prefix = name[:idx + len(app_id) + 1]
                        break

                if not app_prefix:
                    return {"status": "error", "error": f"App '{app_id}' not found in marketplace repo"}

                # Extract app files to project path
                project_path.mkdir(parents=True, exist_ok=True)
                for member in zf.namelist():
                    if member.startswith(app_prefix) and not member.endswith('/'):
                        # Get the relative path within the app folder
                        rel_path = member[len(app_prefix):]
                        if rel_path:
                            target = project_path / rel_path
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(target, 'wb') as dst:
                                dst.write(src.read())

            logger.info(f"[LIVING_UI:MARKETPLACE] Extracted {app_id} to {project_path}")

            # Allocate ports
            frontend_port = self._allocate_port()
            backend_port = self._allocate_port()

            # Replace placeholders (marketplace apps use the same template placeholders)
            # Build replacements — system placeholders + custom fields
            replacements = {
                '{{PROJECT_ID}}': project_id,
                '{{PROJECT_NAME}}': app_name,
                '{{PROJECT_DESCRIPTION}}': app_description,
                '{{PORT}}': str(frontend_port),
                '{{BACKEND_PORT}}': str(backend_port),
                '{{THEME}}': 'system',
                '{{CREATED_AT}}': datetime.now().isoformat(),
                '{{FEATURES}}': '',
            }
            # Add custom fields from marketplace template (e.g., APP_TITLE)
            if custom_fields:
                for key, value in custom_fields.items():
                    replacements[f'{{{{{key}}}}}'] = value

            self._replace_placeholders(project_path, replacements)

            # Create project instance
            project = LivingUIProject(
                id=project_id,
                name=app_name,
                description=app_description,
                path=str(project_path),
                status='created',
                port=frontend_port,
                backend_port=backend_port,
            )

            self.projects[project_id] = project
            self._save_projects()

            logger.info(f"[LIVING_UI:MARKETPLACE] Created project: {app_name} ({project_id})")

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
            return {"status": "error", "error": f"Failed to download from marketplace: {e}"}
        except Exception as e:
            logger.error(f"[LIVING_UI:MARKETPLACE] Install failed: {e}")
            # Clean up on failure
            if project_path.exists():
                try:
                    shutil.rmtree(project_path)
                except Exception:
                    pass
            return {"status": "error", "error": f"Installation failed: {e}"}

    def update_project_status(self, project_id: str, status: str, error: Optional[str] = None) -> None:
        """Update project status."""
        if project_id in self.projects:
            self.projects[project_id].status = status
            if error:
                self.projects[project_id].error = error
            self._save_projects()

    def set_project_task(self, project_id: str, task_id: str) -> None:
        """Associate a task ID with a project."""
        if project_id in self.projects:
            self.projects[project_id].task_id = task_id

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

        # Build the task instruction
        features_str = ', '.join(project.features) if project.features else 'None specified'
        from agent_core.core.prompts.application import LIVING_UI_TASK_INSTRUCTION
        task_instruction = LIVING_UI_TASK_INSTRUCTION.format(
            project_id=project.id,
            project_name=project.name,
            description=project.description,
            features=features_str,
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
                selected_skills=["living-ui-creator"],
            )

            # Associate task with project
            self.set_project_task(project_id, task_id)

            # Update project status
            self.update_project_status(project_id, "creating")

            # Create and fire the trigger to start execution
            trigger = Trigger(
                fire_at=time.time(),
                priority=50,
                next_action_description=f"[Living UI] Create: {project.name}",
                session_id=task_id,
                payload={
                    "type": "living_ui_development",
                    "project_id": project_id,
                },
            )
            await self._trigger_queue.put(trigger)

            logger.info(f"[LIVING_UI] Created task {task_id} and fired trigger for project {project_id}")
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

        if project.status == 'running':
            # Verify processes are actually alive before trusting the stored status
            actually_alive = True

            if project.process is not None and project.process.poll() is not None:
                logger.warning(f"[LIVING_UI] Frontend process dead for {project_id} (stale status)")
                project.process = None
                actually_alive = False

            if project.backend_process is not None and project.backend_process.poll() is not None:
                logger.warning(f"[LIVING_UI] Backend process dead for {project_id} (stale status)")
                project.backend_process = None
                actually_alive = False

            if actually_alive and project.port and not self._is_port_in_use(project.port):
                logger.warning(f"[LIVING_UI] Frontend port {project.port} not responding for {project_id}")
                actually_alive = False

            if actually_alive:
                logger.info(f"[LIVING_UI] Project already running: {project_id}")
                return True

            # Status was stale — reset and fall through to full launch
            logger.info(f"[LIVING_UI] Project {project_id} status was stale, relaunching...")
            project.status = 'stopped'
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
        self, project_id: str, project: 'LivingUIProject', project_path: Path, app_cfg: dict
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
            return {"status": "error", "step": "app.port", "errors": [f"Port {proxy_port} occupied"]}
        if not await self._ensure_port_available(app_port):
            return {"status": "error", "step": "app.port", "errors": [f"Port {app_port} occupied"]}

        cwd = project_path / app_cfg.get('cwd', '.')

        # Install step (optional)
        install_cmd = app_cfg.get('install', '')
        if install_cmd:
            logger.info(f"[LIVING_UI:PIPELINE] [app.install] Running: {install_cmd}")
            result = await self._run_pipeline_command(cwd, install_cmd, "app.install")
            if result["status"] == "error":
                return result

        # Start the app on the internal port
        start_cmd = app_cfg.get('start', '')
        if not start_cmd:
            return {"status": "error", "step": "app.start", "errors": ["No start command in manifest"]}

        logs_dir = project_path / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / 'app_output.log'

        # Build extra env vars — use app_port for the app itself
        extra_env = {}
        for k, v in app_cfg.get('env', {}).items():
            extra_env[k] = str(v).replace('{{PORT}}', str(app_port)).replace('{{BACKEND_PORT}}', str(app_port))
        # Always override PORT with the internal app port — manifest may have a stale hardcoded value
        extra_env['PORT'] = str(app_port)

        # Replace port placeholders in start command with internal app port
        start_cmd = start_cmd.replace('{{PORT}}', str(app_port)).replace('{{BACKEND_PORT}}', str(app_port))

        # Generate bridge token
        from uuid import uuid4
        project.bridge_token = str(uuid4())

        app_process = self._start_process(cwd, start_cmd, log_file, port=app_port, project=project, extra_env=extra_env)
        project.app_process = app_process
        logger.info(f"[LIVING_UI:PIPELINE] App starting on internal port {app_port}")

        # Health check on the app's internal port
        health_cfg = app_cfg.get('health', {})
        # Replace port placeholders in health URL with app_port
        if isinstance(health_cfg, dict) and 'url' in health_cfg:
            health_cfg = dict(health_cfg)
            health_cfg['url'] = health_cfg['url'].replace('{{PORT}}', str(app_port)).replace('{{BACKEND_PORT}}', str(app_port))
        elif isinstance(health_cfg, str):
            health_cfg = health_cfg.replace('{{PORT}}', str(app_port)).replace('{{BACKEND_PORT}}', str(app_port))

        healthy = await self._check_health_with_strategy(health_cfg, app_port, app_process)
        if not healthy:
            log_tail = self._read_log_tail(log_file, 1000)
            if app_process.poll() is not None:
                err = f"App process exited with code {app_process.returncode}"
            else:
                err = f"App not responding on port {app_port}"
                app_process.terminate()
            project.app_process = None
            return {"status": "error", "step": "app.health", "errors": [err, log_tail]}

        logger.info(f"[LIVING_UI:PIPELINE] App healthy on internal port {app_port}")

        # Start the sidecar proxy on the user-facing port
        sidecar_path = Path(__file__).parent.parent / 'data' / 'living_ui_sidecar' / 'proxy.py'
        if sidecar_path.exists():
            sidecar_cmd = f"python \"{sidecar_path}\" --app-port {app_port} --proxy-port {proxy_port}"
            sidecar_log = logs_dir / 'sidecar_output.log'
            sidecar_process = self._start_process(project_path, sidecar_cmd, sidecar_log, port=proxy_port, project=project)
            project.process = sidecar_process  # Store sidecar as frontend process (gets stopped with stop_project)
            logger.info(f"[LIVING_UI:PIPELINE] Sidecar proxy starting: port {proxy_port} → app port {app_port}")

            # Wait for sidecar to be ready
            sidecar_healthy = await self._wait_for_health_check(f"http://localhost:{proxy_port}/health", timeout=15)
            if not sidecar_healthy:
                logger.warning(f"[LIVING_UI:PIPELINE] Sidecar not responding, app still accessible directly on port {app_port}")
                project.url = f"http://localhost:{app_port}"
            else:
                project.url = f"http://localhost:{proxy_port}"
                logger.info(f"[LIVING_UI:PIPELINE] Sidecar ready on port {proxy_port}")
        else:
            logger.warning("[LIVING_UI:PIPELINE] Sidecar proxy not found, running app without proxy")
            project.url = f"http://localhost:{app_port}"

        project.backend_url = f"http://localhost:{app_port}"
        project.status = 'running'
        self._save_projects()

        logger.info(f"[LIVING_UI:PIPELINE] App ready: {project.url}")
        return {
            "status": "success",
            "url": project.url,
            "port": proxy_port,
        }

    @staticmethod
    def _append_node_args(command: str, extra_args: str) -> str:
        """Append CLI args to an npm/pnpm/yarn run command using `--`, or to a direct binary call."""
        if re.match(r'^\s*(?:npm|pnpm|yarn)\s+run\s+\S+', command):
            return f"{command} {extra_args}" if ' -- ' in command else f"{command} -- {extra_args}"
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

        pkg_json_path = project_path / 'package.json'
        if not pkg_json_path.exists():
            return new_start, new_env

        try:
            pkg = json.loads(pkg_json_path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"[LIVING_UI] Could not parse {pkg_json_path}, skipping start-command normalization: {e}")
            return new_start, new_env

        deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
        scripts = pkg.get('scripts', {})

        # If start_command is `npm/pnpm/yarn run X`, look up what X actually invokes
        underlying = start_command
        run_match = re.match(r'^\s*(?:npm|pnpm|yarn)\s+run\s+(\S+)', start_command)
        if run_match:
            underlying = scripts.get(run_match.group(1), '')

        def uses(name: str) -> bool:
            return name in deps or bool(re.search(rf'\b{re.escape(name)}\b', underlying))

        already_has_port = bool(re.search(r'(--port|-p\s|--hostname|-H\s)', new_start))

        if uses('vite'):
            # Vite: CLI --port overrides server.port; BROWSER=none suppresses server.open auto-open
            new_env.setdefault('BROWSER', 'none')
            if not already_has_port:
                new_start = self._append_node_args(
                    new_start, '--port {{PORT}} --host 127.0.0.1 --strictPort'
                )
        elif uses('next'):
            # Next.js: -p PORT, -H HOST. Doesn't auto-open by default.
            if not already_has_port:
                new_start = self._append_node_args(new_start, '-p {{PORT}} -H 127.0.0.1')
        elif uses('react-scripts') or uses('webpack-dev-server'):
            # CRA / webpack-dev-server: respect PORT env, BROWSER=none disables auto-open
            new_env.setdefault('BROWSER', 'none')
        elif uses('@vue/cli-service') or uses('vue-cli-service'):
            new_env.setdefault('BROWSER', 'none')
            if not already_has_port:
                new_start = self._append_node_args(
                    new_start, '--port {{PORT}} --host 127.0.0.1'
                )
        else:
            # Generic Node app — defensively suppress browser auto-open
            new_env.setdefault('BROWSER', 'none')

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
        app_runtime: str = 'unknown',
        install_command: str = '',
        start_command: str = '',
        health_strategy: str = 'tcp',
        health_url: str = '',
        port_env_var: str = 'PORT',
    ) -> Dict[str, Any]:
        """Import an external app as a Living UI project."""
        project_id = self._generate_id()
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
        config_dir = project_path / 'config'
        config_dir.mkdir(exist_ok=True)
        logs_dir = project_path / 'logs'
        logs_dir.mkdir(exist_ok=True)

        # Build health config — uses app_port (internal)
        health_cfg: Any = {"strategy": health_strategy}
        if health_strategy == 'http_get':
            health_cfg["url"] = health_url or f"http://localhost:{{{{PORT}}}}"
            health_cfg["timeout"] = 30

        env_dict: Dict[str, str] = {port_env_var: "{{PORT}}"} if port_env_var else {}

        # Auto-normalize Node.js dev-server start commands so the app binds to
        # CraftBot's allocated port and doesn't pop a system browser tab.
        if app_runtime == 'node':
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
            "agentAwareness": {"enabled": False, "observationMode": "external"},
        }

        manifest_path = config_dir / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2))

        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(project_path),
            status='created',
            port=proxy_port,
            backend_port=app_port,
            project_type='external',
            app_runtime=app_runtime,
        )

        self.projects[project_id] = project
        self._save_projects()

        logger.info(f"[LIVING_UI] Imported external app: {name} ({project_id})")
        return {
            "status": "success",
            "project": project.to_dict(),
        }

    async def _check_health_with_strategy(self, health_cfg, port: int, process, timeout: int = 30) -> bool:
        """Check health using configured strategy (http_get, tcp, process_alive, or URL string)."""
        if isinstance(health_cfg, str):
            # Backward compat: plain URL string
            return await self._wait_for_health_check(health_cfg, timeout=timeout)

        if not isinstance(health_cfg, dict):
            # No health config — just check if port is listening
            return await self._wait_for_server(port, timeout=timeout)

        strategy = health_cfg.get('strategy', 'tcp')
        timeout = health_cfg.get('timeout', timeout)

        if strategy == 'http_get':
            url = health_cfg.get('url', f'http://localhost:{port}')
            url = url.replace('{{PORT}}', str(port))
            return await self._wait_for_health_check(url, timeout=timeout)
        elif strategy == 'tcp':
            return await self._wait_for_server(port, timeout=timeout)
        elif strategy == 'process_alive':
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
        running = [pid for pid, p in self.projects.items() if p.status == 'running']
        if not running:
            return
        logger.info(f"[LIVING_UI] Shutting down {len(running)} running project(s)...")
        for project_id in running:
            try:
                await self.stop_project(project_id)
            except Exception as e:
                logger.warning(f"[LIVING_UI] Error stopping {project_id} during shutdown: {e}")
        logger.info("[LIVING_UI] All projects stopped")

    async def stop_project(self, project_id: str, stop_backend: bool = True) -> bool:
        """
        Stop a running Living UI project (frontend and optionally backend).

        Args:
            project_id: Project ID to stop
            stop_backend: Whether to also stop the backend (default: True)

        Returns:
            True if stop was successful
        """
        project = self.projects.get(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found: {project_id}")
            return False

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

        project.status = 'stopped'
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
        if project.status == 'running':
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
            suffix='.zip', prefix=f'livingui_{self._sanitize_name(project.name)}_',
            delete=False,
        )
        tmp.close()
        zip_path = Path(tmp.name)

        skip_dirs = {'node_modules', '__pycache__', '.git', 'dist', 'build', 'logs', '.venv', 'venv'}
        skip_suffixes = {'.pyc', '.pyo', '.log', '.db', '.sqlite', '.sqlite3'}
        skip_names = {'.env', '.env.local', '.env.production', '.last_launch',
                      'credentials.json', 'token.json', '.jwt_secret'}

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for f in files:
                    file_path = Path(root) / f
                    if file_path.suffix in skip_suffixes or file_path.name in skip_names:
                        continue
                    zf.write(file_path, file_path.relative_to(project_path))

        logger.info(f"[LIVING_UI] Exported project '{project.name}' to {zip_path}")
        return zip_path

    async def import_project_zip(self, zip_path: str, name: str = '') -> 'LivingUIProject':
        """Import a Living UI project from a ZIP file.

        The ZIP should contain a project directory structure with at least
        a config/manifest.json. A new project ID and ports are allocated.
        """
        zip_file = Path(zip_path)
        if not zip_file.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        # Extract to a temp directory first to inspect contents
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                zf.extractall(tmp_dir)

            tmp_path = Path(tmp_dir)

            # Check if files are nested inside a single directory
            entries = list(tmp_path.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                extracted_root = entries[0]
            else:
                extracted_root = tmp_path

            # Read manifest if it exists
            manifest_path = extracted_root / 'config' / 'manifest.json'
            manifest = {}
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                except Exception:
                    pass

            # Determine project name
            if not name:
                name = manifest.get('name', zip_file.stem.replace('livingui_', '').rsplit('_', 1)[0])
            if not name:
                name = 'imported_project'

            # Generate new ID and project path
            project_id = self._generate_id()
            sanitized_name = self._sanitize_name(name)
            project_path = self.living_ui_dir / f"{sanitized_name}_{project_id}"

            # Copy to Living UI workspace
            shutil.copytree(extracted_root, project_path)

        # Allocate new ports
        frontend_port = self._allocate_port()
        backend_port = self._allocate_port()

        # Update manifest with new ID and ports
        manifest_path = project_path / 'config' / 'manifest.json'
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                old_id = manifest.get('id', '')
                old_port = str(manifest.get('ports', {}).get('frontend', manifest.get('ports', {}).get('app', '')))
                old_backend = str(manifest.get('ports', {}).get('backend', ''))

                manifest_raw = manifest_path.read_text(encoding='utf-8')
                if old_id:
                    manifest_raw = manifest_raw.replace(old_id, project_id)
                if old_port and old_port != str(frontend_port):
                    manifest_raw = manifest_raw.replace(old_port, str(frontend_port))
                if old_backend and old_backend != str(backend_port):
                    manifest_raw = manifest_raw.replace(old_backend, str(backend_port))

                manifest_path.write_text(manifest_raw, encoding='utf-8')
                manifest = json.loads(manifest_raw)
            except Exception as e:
                logger.warning(f"[LIVING_UI] Could not update imported manifest: {e}")

        # Determine project type from manifest
        project_type = manifest.get('projectType', 'native')
        app_runtime = manifest.get('appRuntime')
        description = manifest.get('description', '')

        project = LivingUIProject(
            id=project_id,
            name=name,
            description=description,
            path=str(project_path),
            status='ready',
            port=frontend_port,
            backend_port=backend_port,
            project_type=project_type,
            app_runtime=app_runtime,
        )

        self.projects[project_id] = project
        self._save_projects()

        logger.info(f"[LIVING_UI] Imported project '{name}' ({project_id}) from ZIP")
        return project

    def get_project_url(self, project_id: str) -> Optional[str]:
        """Get the URL for a running project."""
        project = self.projects.get(project_id)
        if project and project.status == 'running':
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
            s.connect(('8.8.8.8', 80))
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
        if not project or project.status != 'running':
            return None
        # Prefer backend port (serves both API + frontend static files)
        port = project.backend_port or project.port
        if not port:
            return None
        ip = self.get_lan_ip()
        if not ip or ip.startswith('127.'):
            return None
        return f"http://{ip}:{port}"

    # Cloudflared binary download URLs per platform
    _CLOUDFLARED_URLS = {
        'win32': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe',
        'darwin': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz',
        'linux': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',
    }

    def _get_cloudflared_path(self) -> Optional[str]:
        """Find cloudflared — check PATH first, then our local bin directory."""
        system_path = shutil.which('cloudflared')
        if system_path:
            return system_path
        # Check our local bin
        import sys
        ext = '.exe' if sys.platform == 'win32' else ''
        local_bin = Path(__file__).parent.parent / 'bin' / f'cloudflared{ext}'
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

        bin_dir = Path(__file__).parent.parent / 'bin'
        bin_dir.mkdir(parents=True, exist_ok=True)
        ext = '.exe' if platform_key == 'win32' else ''
        target = bin_dir / f'cloudflared{ext}'

        try:
            url = self._CLOUDFLARED_URLS[platform_key]
            req = urllib.request.Request(url, headers={'User-Agent': 'CraftBot'})
            resp = urllib.request.urlopen(req, timeout=60)

            if platform_key == 'darwin':
                import tarfile, io
                with tarfile.open(fileobj=io.BytesIO(resp.read()), mode='r:gz') as tar:
                    for member in tar.getmembers():
                        if 'cloudflared' in member.name:
                            f = tar.extractfile(member)
                            if f:
                                target.write_bytes(f.read())
                                break
            else:
                target.write_bytes(resp.read())

            if platform_key != 'win32':
                target.chmod(0o755)

            logger.info(f"[LIVING_UI] cloudflared installed at {target}")
            return str(target)
        except Exception as e:
            logger.error(f"[LIVING_UI] Failed to download cloudflared: {e}")
            if target.exists():
                target.unlink()
            return None

    async def start_tunnel(self, project_id: str, provider: str = 'cloudflared') -> Optional[str]:
        """Start a cloudflare tunnel for remote access. Returns the public URL."""
        logger.info(f"[LIVING_UI] start_tunnel called for {project_id}")
        project = self.projects.get(project_id)
        if not project or project.status != 'running':
            logger.warning(f"[LIVING_UI] Cannot start tunnel: project={project is not None}, status={project.status if project else 'N/A'}")
            return None

        logger.info(f"[LIVING_UI] Stopping any existing tunnel...")
        await self.stop_tunnel(project_id)

        # Only kill orphans on first tunnel start (no other tunnels active)
        other_tunnels = any(
            p.tunnel_process is not None and p.id != project_id
            for p in self.projects.values()
        )
        if not other_tunnels:
            logger.info("[LIVING_UI] No other tunnels active, cleaning orphan cloudflared processes...")
            try:
                if os.name == 'nt':
                    subprocess.run(
                        ['powershell', '-Command', 'Stop-Process -Name cloudflared -Force -ErrorAction SilentlyContinue'],
                        capture_output=True, timeout=5
                    )
                else:
                    subprocess.run(['pkill', '-f', 'cloudflared'], capture_output=True)
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

        logger.info(f"[LIVING_UI] Starting cloudflared: {cloudflared} tunnel --url http://localhost:{port}")
        proc = subprocess.Popen(
            [cloudflared, 'tunnel', '--url', f'http://localhost:{port}'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' and hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
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
            logger.error(f"[LIVING_UI] Failed to get tunnel URL")
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

    async def _parse_cloudflare_url(self, proc: subprocess.Popen, timeout: int = 30) -> Optional[str]:
        """Parse the public URL from cloudflared output."""
        import re
        import threading

        url_result = [None]
        pattern = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')

        def _read_stream(stream):
            try:
                for line_bytes in stream:
                    text = line_bytes.decode('utf-8', errors='replace')
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
            if project and project.status != 'error':
                logger.info(f"[LIVING_UI] Auto-launching: {project.name} ({project_id})")
                project.status = 'launching'
                self._save_projects()
                await self.launch_project(project_id)
