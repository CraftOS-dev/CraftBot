"""Security check: the state of this install, with stable check ids.

Modelled on ``openclaw security audit``: every check has a fixed id the UI
and docs can refer to, a status, and, where the fix is safe and local, a
``fix_id`` the page's Fix button sends back. Checks read real state (file
modes, the bind address, the audit chain, the current settings); none of
them guesses from file or command names.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.security.files import is_private, restrict_to_owner


@dataclass
class CheckResult:
    id: str
    status: str  # "ok", "info", "warn" or "fail"
    title: str
    detail: str
    fix_id: Optional[str] = None


def secret_files() -> List[Path]:
    """CraftBot's own files that hold secrets: settings (LLM keys), MCP
    servers (their env), security settings, credentials and the vault."""
    from app.config import APP_CONFIG_PATH, PROJECT_ROOT

    files = [
        APP_CONFIG_PATH / "settings.json",
        APP_CONFIG_PATH / "mcp_config.json",
        APP_CONFIG_PATH / "security.json",
    ]
    credentials = Path(PROJECT_ROOT) / ".credentials"
    if credentials.is_dir():
        files.extend(p for p in credentials.iterdir() if p.is_file())
    return [p for p in files if p.exists()]


def _check_secret_files() -> CheckResult:
    if os.name == "nt":
        return CheckResult(
            "secret_files_private",
            "ok",
            "Secret files are private",
            "Windows keeps them in your user profile, which other users cannot read.",
        )
    exposed = [p for p in secret_files() if not is_private(p)]
    if not exposed:
        return CheckResult(
            "secret_files_private",
            "ok",
            "Secret files are private",
            "API keys, credentials and security settings are readable by your user only.",
        )
    names = ", ".join(p.name for p in exposed[:5])
    return CheckResult(
        "secret_files_private",
        "fail",
        "Secret files are readable by other users",
        f"{len(exposed)} file(s) holding keys or credentials can be read by other "
        f"accounts on this computer: {names}.",
        fix_id="secret_files_private",
    )


def _check_bind_address() -> CheckResult:
    from app.instance import LOOPBACK_NAMES, bind_host

    host = bind_host().strip("[]")
    loopback = host in LOOPBACK_NAMES
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if loopback:
        return CheckResult(
            "ui_local_only",
            "ok",
            "The CraftBot window is only reachable from this computer",
            f"The interface listens on {host}.",
        )
    return CheckResult(
        "ui_local_only",
        "warn",
        "The CraftBot window is reachable from the network",
        f"The interface listens on {host}, and CraftBot has no login of its own. "
        f"Publish its ports on 127.0.0.1 only, or put a login proxy in front of it.",
    )


def _check_audit_chain() -> CheckResult:
    from app.security import audit
    from app.security.policy import get_policy

    log = audit.get_log()
    if not log.path.exists():
        enabled = get_policy().audit_log
        return CheckResult(
            "audit_log_intact",
            "ok" if enabled else "info",
            "Security audit log",
            "Enabled; nothing recorded yet."
            if enabled
            else "Off. The Enhanced and Strict levels turn it on.",
        )
    intact, count, broken = log.verify()
    if intact:
        return CheckResult(
            "audit_log_intact",
            "ok",
            "Security audit log is intact",
            f"{count} record(s), none changed or removed.",
        )
    return CheckResult(
        "audit_log_intact",
        "fail",
        "Security audit log was changed",
        f"The record chain breaks at line {broken}: a record was edited or removed.",
    )


def _check_level() -> CheckResult:
    from app.security.policy import SecurityLevel, get_policy

    policy = get_policy()
    if policy.level == SecurityLevel.STANDARD and not policy.customized:
        return CheckResult(
            "security_level",
            "info",
            "Security level: Standard",
            "CraftBot works as it always has. Enhanced keeps the agent away from "
            "your keys, checks every web request and marks outside content, with "
            "few prompts.",
        )
    return CheckResult(
        "security_level",
        "ok",
        f"Security level: {policy.level.value.title()}"
        + (" (customized)" if policy.customized else ""),
        "Protections beyond Standard are on.",
    )


def _check_auto_mode() -> CheckResult:
    from app.security.policy import get_policy

    if get_policy().auto_mode:
        return CheckResult(
            "auto_mode",
            "info",
            "Auto mode is on",
            "The agent acts without asking. Turn it off to approve high-risk "
            "actions, such as running commands or sending messages, before they run.",
        )
    return CheckResult(
        "auto_mode",
        "ok",
        "Auto mode is off",
        "High-risk actions wait for your approval.",
    )


CHECKS: List[Callable[[], CheckResult]] = [
    _check_secret_files,
    _check_bind_address,
    _check_audit_chain,
    _check_level,
    _check_auto_mode,
]


def run_checks() -> List[Dict[str, object]]:
    results = []
    for check in CHECKS:
        try:
            results.append(asdict(check()))
        except Exception as exc:  # one broken check must not hide the rest
            results.append(
                asdict(
                    CheckResult(
                        check.__name__.lstrip("_"),
                        "warn",
                        "Check could not run",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
            )
    return results


def _fix_secret_files() -> int:
    return sum(1 for p in secret_files() if restrict_to_owner(p))


FIXES: Dict[str, Callable[[], int]] = {"secret_files_private": _fix_secret_files}


def apply_fix(fix_id: str) -> bool:
    fix = FIXES.get(fix_id)
    if fix is None:
        return False
    fix()
    return True
