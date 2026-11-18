"""Claude subscription access through the unmodified Claude Code CLI.

CraftBot stores a versioned opt-in flag. Claude Code owns login, tokens and
refresh inside CraftBot's private CLI config directory. The standalone CLI
login is never read, copied or signed out.

Sign-in works like ChatGPT's: ``claude auth login`` opens one browser tab,
approving there redirects to the CLI's local callback, and the CLI exchanges
the code with its own PKCE verifier and stores the tokens. CraftBot only
waits for the CLI to finish, so it never holds anything it could use to
authenticate.

Sign-in needs a CLI with ``claude auth``. When the CLI is missing or older,
status reports a ``setup`` step and Connect stops before starting a login
that could never open a browser; ``setup_cli`` installs or updates it.
Install sources live in ``claude_code_cli.json``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import ConfigStore
from ..credentials_store import load_credential, remove_credential, save_credential

CRED_FILE = "anthropic_claude_code.json"
PROFILE_VERSION = 1
_CLI = json.loads(Path(__file__).with_name("claude_code_cli.json").read_text("utf-8"))
INSTALL_MESSAGE = (
    f"Claude Code CLI is required. Install it from {_CLI['setup_guide']}, "
    "then connect again."
)
# How long Connect waits for the user to approve in the browser.
LOGIN_TIMEOUT_SECONDS = 5 * 60
# How long installing or updating the CLI may take on a slow connection.
SETUP_TIMEOUT_SECONDS = 10 * 60
_PASTE_PROMPT = re.compile(r"^.*Paste code here if prompted\s*>\s*")


class ClaudeCodeMissing(RuntimeError):
    """No Claude Code CLI that CraftBot can run was found."""


@dataclass
class ClaudeCodeConnection:
    enabled: bool = True
    # Old markers borrowed the standalone CLI login. Never adopt them into
    # the new profile without a separate login through CraftBot.
    profile_version: int = 0


def profile_directory() -> Path:
    """Private, stable auth directory for this CraftBot installation."""
    path = (ConfigStore.project_root / ".credentials" / "claude_code").resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _native_install() -> Path:
    """Where the native installer puts ``claude``. An app started before the
    install still has the old PATH, so this location is checked as well."""
    return (
        Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    )


def _installed_cli() -> Optional[Path]:
    """The ``claude`` CraftBot runs: the first on PATH, else the native install."""
    command = shutil.which("claude")
    if command:
        return Path(command)
    return _native_install() if _native_install().is_file() else None


def _npm_package(found: Path) -> Path:
    """Where the npm package sits beside a Windows npm shim."""
    return found.parent / "node_modules" / _CLI["npm"]["package"]


def cli_command() -> list[str]:
    """Resolve a native CLI or npm entrypoint without passing through a shell."""
    path = _installed_cli()
    if path is None:
        raise ClaudeCodeMissing(INSTALL_MESSAGE)
    if path.suffix.lower() in (".cmd", ".bat", ".ps1"):
        # Windows npm shims invoke a shell, which can reinterpret arguments.
        # Run what the shim runs directly: the package's native binary, or
        # through Node the JS entrypoint that releases before it published.
        package = _npm_package(path)
        binary = package / _CLI["npm"]["binary"]
        if binary.is_file():
            return [str(binary)]
        entrypoint = package / _CLI["npm"]["node_script"]
        node = shutil.which("node")
        if node and entrypoint.is_file():
            return [node, str(entrypoint)]
        raise ClaudeCodeMissing(INSTALL_MESSAGE)
    return [str(path)]


def cli_environment() -> Dict[str, str]:
    """Always use CraftBot's CLI profile, never the standalone CLI account."""
    env = dict(os.environ)
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        # CraftBot's per-request reasoning choice owns these settings.
        "MAX_THINKING_TOKENS",
        "CLAUDE_CODE_EFFORT_LEVEL",
        "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
    ):
        env.pop(name, None)
    env["CLAUDE_CONFIG_DIR"] = str(profile_directory())
    return env


def run_cli(args: list[str], *, timeout: float, env_overrides=None, **kwargs):
    # Resolve first: a status check without a CLI must not create the profile.
    command = cli_command()
    env = cli_environment()
    env.update(env_overrides or {})
    # Request-specific generation settings must not redirect authentication.
    env["CLAUDE_CONFIG_DIR"] = str(profile_directory())
    return subprocess.run(
        [*command, *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        **kwargs,
    )


def open_cli(args: list[str], *, env_overrides=None, **kwargs) -> subprocess.Popen:
    """Start the CLI like run_cli, without waiting for it: stdin, stdout and
    stderr are text pipes, so the caller reads its output as it is written."""
    command = cli_command()
    env = cli_environment()
    env.update(env_overrides or {})
    env["CLAUDE_CONFIG_DIR"] = str(profile_directory())
    return subprocess.Popen(
        [*command, *args],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        **kwargs,
    )


def _read_auth_status() -> Dict[str, Any]:
    # An explicit --json makes releases without `claude auth` reject the
    # option instead of sending "auth status" to Claude as a prompt.
    result = run_cli(["auth", "status", "--json"], timeout=10, stdin=subprocess.DEVNULL)
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or not isinstance(data.get("loggedIn"), bool):
        raise ValueError("Invalid authentication status")
    if result.returncode not in (0, 1) or (result.returncode and data["loggedIn"]):
        raise RuntimeError("Claude Code authentication check failed")
    return data


def _cli_version() -> str:
    """The installed CLI's version as it reports it, or "" when unknown."""
    try:
        result = run_cli(["--version"], timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return ""
    words = result.stdout.split()
    return words[0] if result.returncode == 0 and words else ""


def _setup_for(error: Exception) -> Optional[Dict[str, str]]:
    """The setup step a failed status read calls for, if any."""
    if isinstance(error, (ClaudeCodeMissing, OSError)):
        return {"action": "install"}
    if isinstance(error, ValueError):
        # The CLI runs but has no `claude auth status`.
        return {"action": "update", "version": _cli_version()}
    return None


def _setup_message(setup: Dict[str, str]) -> str:
    if setup["action"] == "install":
        return (
            "Claude subscription sign-in requires Claude Code. "
            "Install it, then sign in again."
        )
    version = f" {setup['version']}" if setup.get("version") else ""
    return (
        f"Claude Code{version} does not support subscription sign-in. "
        "Update it, then sign in again."
    )


def auth_status() -> Dict[str, Any]:
    try:
        data = _read_auth_status()
        if not data["loggedIn"]:
            return {
                "connected": False,
                "error": "Use Connect to sign in to CraftBot's separate Claude profile.",
            }
        if data.get("authMethod") != "claude.ai":
            return {
                "connected": False,
                "error": "A Claude subscription login is required. Use Connect in CraftBot.",
            }
        return {
            "connected": True,
            "email": data.get("email") or "",
            "plan": data.get("subscriptionType") or "Claude Code",
        }
    except subprocess.TimeoutExpired:
        return {
            "connected": False,
            "error": "Claude Code authentication check timed out.",
        }
    except (OSError, RuntimeError, ValueError) as e:
        setup = _setup_for(e)
        if setup:
            return {"connected": False, "error": _setup_message(setup), "setup": setup}
        return {
            "connected": False,
            "error": "Could not check Claude Code login. " + INSTALL_MESSAGE,
        }


def cli_setup() -> Optional[Dict[str, str]]:
    """None when the CLI can run subscription sign-in, else the step it needs:
    ``{"action": "install"}`` or ``{"action": "update", "version": ...}``."""
    return auth_status().get("setup")


def has_credential() -> bool:
    connection = load_credential(CRED_FILE, ClaudeCodeConnection)
    return (
        connection is not None
        and connection.enabled
        and connection.profile_version == PROFILE_VERSION
    )


def status() -> Dict[str, Any]:
    if not has_credential():
        # Report a missing or outdated CLI before the user tries to sign in.
        setup = cli_setup()
        return {
            "supported": True,
            "connected": False,
            **({"setup": setup} if setup else {}),
        }
    # Authentication can fail while the explicit opt-in still owns routing.
    # Keep Disconnect available until logout is verified and the flag is removed.
    return {"supported": True, "configured": True, **auth_status()}


def _save_connection(current: Dict[str, Any]) -> Tuple[bool, str]:
    """Record the opt-in once the private profile is signed in to claude.ai."""
    if not current["connected"]:
        return False, str(current.get("error", "Claude Code sign-in failed."))
    save_credential(CRED_FILE, ClaudeCodeConnection(profile_version=PROFILE_VERSION))
    if not has_credential():
        return False, "Could not save the Claude Code connection."
    who = f" as {current['email']}" if current.get("email") else ""
    return True, f"Claude subscription connected{who}."


_login_lock = threading.Lock()
_login_process: Optional[subprocess.Popen] = None
_login_generation = 0


def _cancel_login() -> None:
    """Invalidate every older attempt and reap its CLI before changing auth.

    Caller holds _login_lock. Never wait for browser approval under this lock.
    """
    global _login_generation, _login_process
    _login_generation += 1
    process = _login_process
    if process is not None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        _login_process = None


def _finish_login(attempt: int, current: Dict[str, Any]) -> Tuple[bool, str]:
    with _login_lock:
        if attempt != _login_generation:
            return False, "Claude sign-in was cancelled or replaced by a newer request."
        return _save_connection(current)


def _last_message(output: List[str]) -> str:
    for line in reversed(output):
        line = _PASTE_PROMPT.sub("", line).strip()
        if line:
            return line
    return ""


def _browser_login(attempt: int) -> Tuple[bool, str]:
    """Run ``claude auth login`` until the user approves in its browser tab."""
    global _login_process
    try:
        with _login_lock:
            if attempt != _login_generation:
                return (
                    False,
                    "Claude sign-in was cancelled or replaced by a newer request.",
                )
            process = subprocess.Popen(
                # Subscription OAuth is the CLI default. Avoid undocumented
                # flags that older supported CLIs reject before opening a tab.
                [*cli_command(), "auth", "login"],
                env=cli_environment(),
                # Never written, but kept open: at end of input the CLI would
                # stop waiting for the browser.
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            _login_process = process
    except RuntimeError as e:
        return False, str(e)
    except OSError as e:
        return False, f"Could not start Claude Code: {e}"
    output: List[str] = []

    def read_output() -> None:
        for raw in iter(process.stdout.readline, b""):
            output.append(raw.decode("utf-8", "replace").strip())

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        process.wait(timeout=LOGIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        return False, "Claude sign-in timed out. Click Connect to try again."
    finally:
        with _login_lock:
            replaced = attempt != _login_generation
            if not replaced and process.poll() is not None:
                _login_process = None
    reader.join(timeout=5)
    if replaced:
        return False, "A newer Claude sign-in replaced this one."
    if process.returncode:
        detail = _last_message(output) or "Claude Code could not sign in"
        return False, f"Claude sign-in failed: {detail}"
    return _finish_login(attempt, auth_status())


def _login() -> Tuple[bool, str]:
    # Reserve an identity before even checking an existing private sign-in:
    # Disconnect must also invalidate that fast path and post-approval checks.
    with _login_lock:
        try:
            _cancel_login()
        except (OSError, subprocess.TimeoutExpired):
            return False, "Could not stop the previous Claude sign-in. Retry Connect."
        attempt = _login_generation
    # A sign-in the private profile already has needs no browser.
    current = auth_status()
    if current["connected"]:
        return _finish_login(attempt, current)
    if "setup" in current:
        # A missing or older CLI cannot open the sign-in page; waiting for it
        # would only end in a timeout.
        return False, current["error"]
    return _browser_login(attempt)


async def run_login() -> Tuple[bool, str]:
    """Sign in like ChatGPT's loopback flow: Claude Code opens one browser
    tab, and this returns once the user approves there or the wait times out."""
    return await asyncio.to_thread(_login)


_setup_lock = threading.Lock()


def _setup_command() -> List[str]:
    """Update the CLI CraftBot found the way it was installed: npm updates an
    npm install in place. Anything else gets the official native installer."""
    found = _installed_cli()
    if found is not None and (
        _npm_package(found).is_dir() or "node_modules" in found.resolve().parts
    ):
        npm = shutil.which("npm")
        if not npm:
            raise ClaudeCodeMissing(
                "Claude Code was installed with npm, but npm was not found. "
                f"Update it as described at {_CLI['setup_guide']}."
            )
        return [npm, "install", "--global", f"{_CLI['npm']['package']}@latest"]
    return list(_CLI["native_installer"]["windows" if os.name == "nt" else "posix"])


def setup_cli() -> Tuple[bool, str]:
    """Install Claude Code, or update the copy CraftBot runs, then verify that
    it supports subscription sign-in."""
    if not _setup_lock.acquire(blocking=False):
        return False, "Claude Code setup is already running."
    try:
        # A pending sign-in holds the files an update replaces.
        with _login_lock:
            try:
                _cancel_login()
            except (OSError, subprocess.TimeoutExpired):
                return False, "Could not stop the pending Claude sign-in. Retry setup."
        try:
            result = subprocess.run(
                _setup_command(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=SETUP_TIMEOUT_SECONDS,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except ClaudeCodeMissing as e:
            return False, str(e)
        except subprocess.TimeoutExpired:
            return False, "Claude Code setup timed out. Check the connection and retry."
        except OSError as e:
            return False, f"Could not start the Claude Code installer: {e}"
        if result.returncode:
            detail = (
                _last_message((result.stdout + "\n" + result.stderr).splitlines())
                or f"exit code {result.returncode}"
            )
            return False, (
                f"Claude Code setup failed: {detail}. "
                f"Set it up as described at {_CLI['setup_guide']}."
            )
        setup = cli_setup()
        if setup:
            found = _installed_cli()
            where = f" at {found}" if found else ""
            return False, (
                f"Claude Code was set up, but the copy CraftBot runs{where} still "
                "does not support subscription sign-in. Remove or update that "
                f"copy as described at {_CLI['setup_guide']}."
            )
        version = _cli_version()
        name = f"Claude Code {version}" if version else "Claude Code"
        return True, f"{name} is ready. Sign in to continue."
    finally:
        _setup_lock.release()


def remove() -> Tuple[bool, str]:
    """Sign out only CraftBot's official CLI profile, then clear its marker."""
    # Serialize logout with starting a CLI and committing a connection flag.
    # Killing and reaping first prevents a pending CLI from writing auth later.
    with _login_lock:
        try:
            _cancel_login()
        except (OSError, subprocess.TimeoutExpired):
            return False, "Could not stop the pending Claude sign-in. Retry Disconnect."
        return _remove_connection()


def _remove_connection() -> Tuple[bool, str]:
    try:
        result = run_cli(["auth", "logout"], timeout=30)
        if result.returncode:
            return (
                False,
                "Claude sign-out failed. Retry Disconnect; the connection was retained.",
            )
        if _read_auth_status()["loggedIn"]:
            return (
                False,
                "Claude Code is still signed in to CraftBot's profile. Retry Disconnect.",
            )
    except subprocess.TimeoutExpired:
        return False, "Claude sign-out or verification timed out. Retry Disconnect."
    except (OSError, RuntimeError, ValueError):
        return (
            False,
            "Could not verify Claude sign-out. Check the CLI installation and retry Disconnect.",
        )
    try:
        remove_credential(CRED_FILE)
    except OSError:
        return (
            False,
            "Claude signed out, but CraftBot could not clear the connection. Retry Disconnect.",
        )
    return (
        True,
        "Signed out of CraftBot's Claude profile. Your standalone Claude Code login is unchanged.",
    )
