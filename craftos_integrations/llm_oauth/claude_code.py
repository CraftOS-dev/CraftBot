"""Claude subscription access through the unmodified Claude Code CLI.

CraftBot stores a versioned opt-in flag. Claude Code owns login, tokens and
refresh inside CraftBot's private CLI config directory. The standalone CLI
login is never read, copied or signed out.

Sign-in works like ChatGPT's: ``claude auth login`` opens one browser tab,
approving there redirects to the CLI's local callback, and the CLI exchanges
the code with its own PKCE verifier and stores the tokens. CraftBot only
waits for the CLI to finish, so it never holds anything it could use to
authenticate.
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
INSTALL_MESSAGE = (
    "Claude Code CLI is required. Install it from "
    "https://code.claude.com/docs/en/setup, then connect again."
)
# How long Connect waits for the user to approve in the browser.
LOGIN_TIMEOUT_SECONDS = 5 * 60
_PASTE_PROMPT = re.compile(r"^.*Paste code here if prompted\s*>\s*")


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


def cli_command() -> list[str]:
    """Resolve a native CLI or npm entrypoint without passing through a shell."""
    command = shutil.which("claude")
    if not command and _native_install().is_file():
        command = str(_native_install())
    if not command:
        raise RuntimeError(INSTALL_MESSAGE)
    path = Path(command)
    if path.suffix.lower() in (".cmd", ".bat", ".ps1"):
        # Windows npm shims invoke a shell, which can reinterpret arguments.
        # Execute the same published JS entrypoint directly with Node instead.
        entrypoint = path.parent / "node_modules/@anthropic-ai/claude-code/cli.js"
        node = shutil.which("node")
        if node and entrypoint.is_file():
            return [node, str(entrypoint)]
        raise RuntimeError(INSTALL_MESSAGE)
    return [command]


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
    env = cli_environment()
    env.update(env_overrides or {})
    # Request-specific generation settings must not redirect authentication.
    env["CLAUDE_CONFIG_DIR"] = str(profile_directory())
    return subprocess.run(
        [*cli_command(), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        **kwargs,
    )


def _read_auth_status() -> Dict[str, Any]:
    result = run_cli(["auth", "status"], timeout=10)
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or not isinstance(data.get("loggedIn"), bool):
        raise ValueError("Invalid authentication status")
    if result.returncode not in (0, 1) or (result.returncode and data["loggedIn"]):
        raise RuntimeError("Claude Code authentication check failed")
    return data


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
    except (OSError, RuntimeError, ValueError):
        return {
            "connected": False,
            "error": "Could not check Claude Code login. " + INSTALL_MESSAGE,
        }


def has_credential() -> bool:
    connection = load_credential(CRED_FILE, ClaudeCodeConnection)
    return (
        connection is not None
        and connection.enabled
        and connection.profile_version == PROFILE_VERSION
    )


def status() -> Dict[str, Any]:
    if not has_credential():
        return {"supported": True, "connected": False}
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
    return _browser_login(attempt)


async def run_login() -> Tuple[bool, str]:
    """Sign in like ChatGPT's loopback flow: Claude Code opens one browser
    tab, and this returns once the user approves there or the wait times out."""
    return await asyncio.to_thread(_login)


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
