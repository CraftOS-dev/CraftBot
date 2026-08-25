"""Living UI runner — thin adapter between CraftBot and the living-ui
workspace (spec REQUIREMENTS §14/I1).

Consumes only the two public contracts:
  * the tools CLI (`create`, `validate`, `pb path`) for scaffold/gate/binary,
  * the manifest pipeline semantics (single PocketBase process, /api/health).

Knows nothing about the manager's registry, sessions, or broadcasting —
the manager composes this class; it never reaches back.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app import node_runtime
from app.node_runtime import MIN_NODE_MAJOR

logger = logging.getLogger(__name__)

GATE_TIMEOUT_S = 600
INSTALL_TIMEOUT_S = 600
HEALTH_TIMEOUT_S = 30

# Node resolution: app/node_runtime.py. The lui CLI is the strictest
# consumer — TypeScript run by native type stripping, >= 24 or
# ERR_UNKNOWN_FILE_EXTENSION (observed 2026-08-19, system Node 22.14).


@dataclass
class V2ScaffoldResult:
    path: Path
    id: str
    slug: str
    port: int


@dataclass
class V2GateResult:
    passed: bool
    output: str


class LivingUIRunnerUnavailable(RuntimeError):
    """Node or the living-ui workspace is missing."""


def read_superuser_creds(project_dir: Path):
    """(email, password) from the project's 0600 `.superuser` file, or None
    when the file is absent/unreadable/incomplete. The ONE parser of that
    file — ensure_superuser writes it and reads through here; the backup
    service reads through here to call the PocketBase admin API. Never log
    the values."""
    import json as _json

    try:
        stored = _json.loads(
            (Path(project_dir) / ".superuser").read_text(encoding="utf-8")
        )
        email = stored.get("email") or ""
        password = stored.get("password") or ""
        if email and password:
            return (email, password)
    except Exception:
        pass
    return None


class LivingUIRunner:
    """Drives Living UI projects through scaffold → install → gate → serve."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir)

    # ------------------------------------------------------------------ setup

    @property
    def cli_path(self) -> Path:
        return self.workspace_dir / "tools" / "src" / "cli.ts"

    def ensure_available(self) -> None:
        rt = node_runtime.resolve()
        if rt is None:
            hint = ""
            path_version = None
            path_node = shutil.which("node")
            if path_node:
                path_version = node_runtime.probe_version(path_node)
                hint = (
                    f" (PATH has {path_version or 'an unprobeable node'} at "
                    f"{path_node}, which the lui CLI — TypeScript run by "
                    "Node's native type stripping — cannot load; it is left "
                    "untouched)"
                )
            raise LivingUIRunnerUnavailable(
                f"Node.js >= {MIN_NODE_MAJOR} is required to build Living UIs "
                f"and none was found{hint}. CraftBot never upgrades your "
                "default Node: run `python install.py` to add a side-by-side "
                "Node (nvm install 24 also works), or point the CRAFTBOT_NODE "
                "env var at a >= 24 binary, then restart."
            )
        major = node_runtime.major_of(rt.version)
        if major is not None and major < MIN_NODE_MAJOR:
            # Only reachable via a CRAFTBOT_NODE override pointing at an old
            # binary — resolve() filters everything else by version.
            raise LivingUIRunnerUnavailable(
                f"Node.js >= {MIN_NODE_MAJOR} is required to build Living UIs — "
                f"CRAFTBOT_NODE points at {rt.node} ({rt.version}). Point it "
                "at a >= 24 binary or unset it, then restart."
            )
        if not self.cli_path.exists():
            raise LivingUIRunnerUnavailable(
                f"living-ui workspace not found at {self.workspace_dir}"
            )

    def _cli(self, *args: str) -> list:
        return [node_runtime.node_cmd() or "node", str(self.cli_path), *args]

    async def _run(
        self, cmd: list, timeout: int, cwd: Optional[Path] = None
    ) -> "tuple[int, str]":
        """Run a command, return (exit_code, combined_output)."""
        kwargs = {}
        if sys.platform == "win32":
            # Without this, spawning node/npm/pocketbase from this windowless
            # process makes Windows flash a new console window per invocation.
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            # Own process group, so a timeout can kill the WHOLE TREE. Killing
            # only the direct child (cli.ts) orphans its pocketbase grandchild
            # — observed: a wedged `pocketbase migrate` surviving its parent's
            # timeout kill and squatting forever.
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            env=node_runtime.child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **kwargs,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                import signal as _signal

                try:
                    os.killpg(proc.pid, _signal.SIGKILL)
                except Exception:
                    proc.kill()
            return 124, f"timed out after {timeout}s: {' '.join(map(str, cmd))}"
        return proc.returncode or 0, out.decode(errors="replace")

    # ------------------------------------------------------------- lifecycle

    async def scaffold(
        self,
        name: str,
        description: str,
        parent_dir: Path,
        port: int,
        project_id: str,
        auth_mode: str = "none",
        folder: Optional[str] = None,
        style: Optional[str] = None,
    ) -> V2ScaffoldResult:
        """Scaffold via `lui create --json` (copies blueprint, vendors kit,
        substitutes placeholders, bootstraps superuser, canonizes hashes)."""
        self.ensure_available()
        args = [
            "create",
            name,
            "--description",
            description,
            "--dir",
            str(parent_dir),
            "--port",
            str(port),
            "--auth",
            auth_mode,
            "--id",
            project_id,
            "--json",
        ]
        if folder is not None:
            args += ["--folder", folder]
        if style:
            args += ["--style", style]
        # Provenance: stamp which CraftBot scaffolded this app into the
        # manifest (before hashes are canonized, so the gate stays green).
        try:
            from app.config import get_app_version

            args += ["--craftbot-version", get_app_version()]
        except Exception:
            pass
        code, out = await self._run(self._cli(*args), timeout=GATE_TIMEOUT_S)
        if code != 0:
            raise RuntimeError(f"scaffold failed:\n{out}")
        # --json prints exactly one JSON line (steps log lines precede it).
        payload = json.loads(out.strip().splitlines()[-1])
        return V2ScaffoldResult(
            path=Path(payload["path"]),
            id=payload["id"],
            slug=payload["slug"],
            port=int(payload["port"]),
        )

    async def install(self, project_dir: Path) -> None:
        """Install frontend deps (skipped when node_modules already exists)."""
        frontend = project_dir / "frontend"
        if (frontend / "node_modules").exists():
            return
        # Windows: bare "npm" is npm.cmd — CreateProcess only finds it via a
        # full path, so never spawn the bare name.
        npm = node_runtime.npm_cmd() or "npm"
        code, out = await self._run(
            # --ignore-scripts: any npm package is allowed in a project, so
            # lifecycle scripts must never run (supply-chain guard, spec B7).
            [npm, "install", "--no-audit", "--no-fund", "--ignore-scripts"],
            timeout=INSTALL_TIMEOUT_S,
            cwd=frontend,
        )
        if code != 0:
            raise RuntimeError(f"npm install failed:\n{out[-4000:]}")

    async def gate(self, project_dir: Path) -> V2GateResult:
        """Run the validation gate; output is the machine-readable error list."""
        self.ensure_available()
        code, out = await self._run(
            self._cli("validate", str(project_dir)), timeout=GATE_TIMEOUT_S
        )
        return V2GateResult(passed=code == 0, output=out)

    async def kit_sync(self, project_dir: Path) -> None:
        """Re-vendor the kit and re-canonize system-file hashes (used after
        import, where identity rewrites invalidate the shipped hash canon)."""
        # Import/marketplace installs reach here without going through
        # scaffold/gate — without this check an old Node surfaces as a raw
        # ERR_UNKNOWN_FILE_EXTENSION stack trace instead of the friendly
        # version requirement (observed 2026-08-25, marketplace install).
        self.ensure_available()
        code, out = await self._run(
            self._cli("kit-sync", str(project_dir)), timeout=GATE_TIMEOUT_S
        )
        if code != 0:
            raise RuntimeError(f"kit-sync failed:\n{out[-2000:]}")

    async def adapter_sync(self, project_dir: Path) -> None:
        """Bring the project's system pb_hooks up to the current adapter.

        Without this, the A2APP layer reaches only apps that were installed or
        imported AFTER it shipped: `kit_sync` is called from those two paths
        alone, so an app a user already had would never gain the write guard,
        the identity endpoint or `describe`, however often they opened it.

        Safe on every launch: it replaces only the tooling-owned hook files
        (agent-authored `ops.pb.js` and friends are untouched), needs no
        rebuild because PocketBase reads hooks at runtime, and is idempotent.
        Failure is NON-FATAL — an app that cannot be upgraded should still
        start, just without the newer guard.
        """
        try:
            self.ensure_available()
        except LivingUIRunnerUnavailable as e:
            logger.warning(f"[LIVING_UI] adapter-sync skipped: {e}")
            return
        code, out = await self._run(
            self._cli("adapter-sync", str(project_dir)), timeout=GATE_TIMEOUT_S
        )
        if code != 0:
            logger.warning(
                f"[LIVING_UI] adapter-sync failed for {project_dir.name} "
                f"(app will run with its existing adapter): {out[-300:]}"
            )

    async def pb_binary(self) -> Path:
        self.ensure_available()
        code, out = await self._run(self._cli("pb", "path"), timeout=300)
        if code != 0:
            raise RuntimeError(f"could not resolve PocketBase binary:\n{out}")
        return Path(out.strip().splitlines()[-1])

    async def ensure_superuser(self, project_dir: Path) -> None:
        """Guarantee the project's PocketBase has a machine superuser.

        Without one, PocketBase treats the first `serve` as an install and
        POPS OPEN ITS SETUP/LOGIN PAGE IN THE USER'S BROWSER — jarring, and
        it exposes an admin console the user never asked for. `lui create`
        bootstraps this for scaffolded projects, but marketplace installs
        and ZIP imports skip that path, and a wiped pb_data loses it, so
        (re)assert it on every launch. `superuser upsert` is idempotent.

        Credentials live only in the project-local, 0600 `.superuser` file
        (spec B5) — never logged, never shipped.
        """
        import json as _json
        import secrets

        pb_bin = await self.pb_binary()
        pb_dir = project_dir / "pb"
        cred_file = project_dir / ".superuser"

        creds = read_superuser_creds(project_dir)
        email = creds[0] if creds else "agent@lui.local"
        password = creds[1] if creds else secrets.token_urlsafe(18)

        code, out = await self._run(
            [
                str(pb_bin),
                "superuser",
                "upsert",
                email,
                password,
                "--dir",
                str(pb_dir / "pb_data"),
                "--migrationsDir",
                str(pb_dir / "pb_migrations"),
                "--hooksDir",
                str(pb_dir / "pb_hooks"),
            ],
            timeout=60,
        )
        if code != 0:
            # FAIL CLOSED. A serve without a superuser makes PocketBase pop
            # the user's SYSTEM BROWSER with a one-time /_/#/pbinstall/…
            # admin-installer token (observed live 2026-08-05, kanban_board
            # marketplace install) — a jarring tab AND an unauthenticated
            # admin takeover link. A failed launch with evidence beats that.
            # Never include the password in the error.
            raise RuntimeError(
                f"superuser upsert failed for {project_dir.name} — refusing "
                f"to serve without one (PocketBase would open its installer "
                f"page in the user's browser): {out[-300:]}"
            )
        try:
            cred_file.write_text(
                _json.dumps({"email": email, "password": password}) + "\n",
                encoding="utf-8",
            )
            cred_file.chmod(0o600)
        except Exception as e:
            logger.warning(f"[LIVING_UI] could not persist .superuser: {e}")

    def ensure_agent_token(self, project_dir: Path) -> str:
        """Guarantee the project has an agent token, and return it.

        This is the credential a NON-BROWSER client presents to write: the lui
        CLI, CraftBot, or a third-party agent (spec A2APP-PLAN Phase 2 C4).

        Threat model, stated plainly: the file is 0600 but any local process
        running as this user can read it, so it is not a boundary against local
        code. It is the same model Home Assistant and Obsidian's local API use,
        and it is the right one for a loopback app. What it buys is a real
        credential that can be handed to an external agent, and the foundation
        for tightening collection rules (A4) and for remote access later.

        The app's own frontend does NOT need it — browsers always send Origin
        on writes, and a loopback Origin is trusted by the system middleware.
        """
        import secrets

        token_file = project_dir / ".agent-token"
        try:
            existing = token_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except Exception:
            pass

        token = secrets.token_urlsafe(32)
        try:
            token_file.write_text(token + "\n", encoding="utf-8")
            token_file.chmod(0o600)
        except Exception as e:
            logger.warning(f"[LIVING_UI] could not persist .agent-token: {e}")
        return token

    async def start(
        self, project_dir: Path, port: int, bridge_token: str = ""
    ) -> subprocess.Popen:
        """Start the single production process: PocketBase serving app + API."""
        pb_bin = await self.pb_binary()
        pb_dir = project_dir / "pb"
        # Must happen BEFORE serve, or PocketBase opens its setup page.
        await self.ensure_superuser(project_dir)
        # The credential non-browser clients present to write (Phase 2 C4).
        self.ensure_agent_token(project_dir)
        # Upgrade the in-app A2APP layer. This is the ONLY path that reaches an
        # app the user already had — install and import cover new arrivals only.
        await self.adapter_sync(project_dir)
        logs_dir = project_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(logs_dir / "pocketbase.log", "a")

        # The app's pb_hooks (_craftbot_bridge.js) call back into CraftBot's
        # LLM/integration bridge over HTTP using these two env vars — without
        # them every AI feature silently no-ops (empty prompt result, no
        # network call attempted at all).
        env = os.environ.copy()
        if bridge_token:
            bridge_port = int(os.environ.get("BROWSER_PORT", "7926"))
            env["CRAFTBOT_BRIDGE_URL"] = f"http://localhost:{bridge_port}"
            env["CRAFTBOT_BRIDGE_TOKEN"] = bridge_token
            logger.info(
                f"[LIVING_UI] bridge env injected: URL=http://localhost:{bridge_port}, token={bridge_token[:8]}..."
            )
        else:
            logger.warning(
                "[LIVING_UI] no bridge token provided; AI features will be unavailable"
            )

        process = subprocess.Popen(
            [
                str(pb_bin),
                "serve",
                f"--http=127.0.0.1:{port}",
                "--dir",
                str(pb_dir / "pb_data"),
                "--hooksDir",
                str(pb_dir / "pb_hooks"),
                "--migrationsDir",
                str(pb_dir / "pb_migrations"),
                "--publicDir",
                str(pb_dir / "pb_public"),
            ],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        logger.info(f"[LIVING_UI] started PocketBase pid={process.pid} port={port}")
        return process

    async def verify(self, project_dir: Path, url: str) -> "tuple[str, str]":
        """Headless smoke verification of the running app (walk-verify core).

        Returns (status, detail) where status is 'pass' | 'fail' | 'skipped'.
        Skipped (no browser installed) must not block a launch.
        """
        code, out = await self._run(
            self._cli("verify", str(project_dir), "--url", url), timeout=120
        )
        detail = out.strip().splitlines()[-1] if out.strip() else "{}"
        if code == 0:
            return "pass", detail
        if code == 2:
            return "skipped", detail
        return "fail", detail

    async def wait_healthy(self, port: int, timeout: int = HEALTH_TIMEOUT_S) -> bool:
        """Poll /api/health until 200 or timeout."""
        import urllib.request

        deadline = asyncio.get_event_loop().time() + timeout
        url = f"http://127.0.0.1:{port}/api/health"
        while asyncio.get_event_loop().time() < deadline:
            try:
                status = await asyncio.to_thread(
                    lambda: urllib.request.urlopen(url, timeout=2).status
                )
                if status == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False
