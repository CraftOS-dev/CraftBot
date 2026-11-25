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
            "Key files are private",
            "",
        )
    exposed = [p for p in secret_files() if not is_private(p)]
    if not exposed:
        return CheckResult(
            "secret_files_private",
            "ok",
            "Key files are private",
            "",
        )
    names = ", ".join(p.name for p in exposed[:5])
    return CheckResult(
        "secret_files_private",
        "fail",
        "Key files are readable by other users",
        names,
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
            "Interface is local only",
            "",
        )
    return CheckResult(
        "ui_local_only",
        "warn",
        "Interface is open to the network",
        f"Listening on {host} with no login. Bind it to 127.0.0.1 or add a login proxy.",
    )


def _check_audit_chain() -> CheckResult:
    from app.security import audit

    log = audit.get_log()
    if not log.path.exists():
        return CheckResult("audit_log_intact", "ok", "Audit log is intact", "")
    intact, count, broken = log.verify()
    if intact:
        return CheckResult(
            "audit_log_intact",
            "ok",
            "Audit log is intact",
            "",
        )
    return CheckResult(
        "audit_log_intact",
        "fail",
        "Audit log was changed",
        f"A record was edited or removed at line {broken}.",
    )


def _check_level() -> CheckResult:
    from app.security.policy import SecurityLevel, get_policy

    policy = get_policy()
    if policy.level == SecurityLevel.STANDARD and not policy.customized:
        return CheckResult(
            "security_level",
            "info",
            "Security level: Standard",
            "",
        )
    return CheckResult(
        "security_level",
        "ok",
        f"Security level: {policy.level.value.title()}"
        + (" (custom)" if policy.customized else ""),
        "",
    )


def _check_auto_mode() -> CheckResult:
    from app.security.policy import get_policy

    if get_policy().auto_mode:
        return CheckResult(
            "auto_mode",
            "info",
            "Auto mode is on",
            "",
        )
    return CheckResult(
        "auto_mode",
        "ok",
        "Auto mode is off",
        "",
    )


def _check_mcp_changes() -> CheckResult:
    from app.security import mcp_trust
    from app.security.policy import get_policy

    if not get_policy().verify_mcp_servers:
        return CheckResult(
            "mcp_servers_unchanged",
            "info",
            "MCP servers aren't verified",
            "",
        )
    changed = mcp_trust.changed_servers()
    if not changed:
        return CheckResult(
            "mcp_servers_unchanged",
            "ok",
            "MCP servers are unchanged",
            "",
        )
    return CheckResult(
        "mcp_servers_unchanged",
        "warn",
        "MCP servers changed outside Settings",
        f"Paused until you confirm: {', '.join(changed)}. Review them in Settings > MCP, then Fix.",
        fix_id="mcp_servers_unchanged",
    )


def _check_mcp_pins() -> CheckResult:
    from app.security import mcp_pins, mcp_trust

    unpinned = mcp_pins.unpinned_servers(mcp_trust._configured_servers())
    if not unpinned:
        return CheckResult(
            "mcp_packages_pinned", "ok", "MCP packages are pinned", "",
        )
    shown = ", ".join(f"{name} ({spec})" for name, spec in unpinned[:5])
    more = f" and {len(unpinned) - 5} more" if len(unpinned) > 5 else ""
    return CheckResult(
        "mcp_packages_pinned", "warn", "MCP packages aren't pinned",
        f"{shown}{more}. Add a version in Settings > MCP.",
    )


def _check_memory_files() -> CheckResult:
    from app.security import memory_guard
    from app.security.policy import get_policy

    if not get_policy().guard_memory:
        return CheckResult(
            "memory_files_trusted", "info", "Memory files aren't guarded", "",
        )
    untrusted = memory_guard.untrusted_files()
    if not untrusted:
        return CheckResult(
            "memory_files_trusted", "ok", "Memory files are trusted", "",
        )
    names = ", ".join(entry["name"] for entry in untrusted)
    return CheckResult(
        "memory_files_trusted",
        "warn",
        "Memory files changed from outside content",
        f"Kept out of the prompt: {names}. Review them in Settings > Memory, then Fix.",
        fix_id="memory_files_trusted",
    )


def runtime_secret_files() -> List[Path]:
    """Files CraftBot writes at run time that must stay private: the session
    token files, the audit log and the MCP trust ledger."""
    from app import paths
    from app.config import PROJECT_ROOT

    found: List[Path] = []
    for folder in (Path(paths.STATE_ROOT) / "run", Path(PROJECT_ROOT) / ".security"):
        if folder.is_dir():
            found.extend(p for p in folder.iterdir() if p.is_file())
    return found


def _check_runtime_files() -> CheckResult:
    if os.name == "nt":
        return CheckResult(
            "runtime_files_private", "ok", "Session and audit files are private", "",
        )
    exposed = [p for p in runtime_secret_files() if not is_private(p)]
    if not exposed:
        return CheckResult(
            "runtime_files_private", "ok", "Session and audit files are private", "",
        )
    return CheckResult(
        "runtime_files_private", "fail", "Session or audit files are readable by other users",
        ", ".join(p.name for p in exposed[:5]),
        fix_id="runtime_files_private",
    )


def _check_prompt_logging() -> CheckResult:
    from app.security.policy import get_policy

    if get_policy().log_prompts:
        return CheckResult(
            "prompts_not_logged", "info", "Full prompts are logged", "",
        )
    return CheckResult(
        "prompts_not_logged", "ok", "Prompts aren't logged", "",
    )


def _check_web_guard() -> CheckResult:
    from app.security.policy import get_policy

    if get_policy().network_guard:
        return CheckResult(
            "web_requests_public_only", "ok", "Local network is blocked", "",
        )
    return CheckResult(
        "web_requests_public_only", "info", "Local network isn't blocked", "",
    )


def _check_inbox() -> CheckResult:
    from craftos_integrations import has_credential, load_config
    from craftos_integrations.providers.gmail import client as gmail

    from app.security.policy import get_policy

    policy = get_policy()
    if not has_credential(gmail.GmailClient.spec.cred_file):
        return CheckResult("inbox_reaches_agent", "ok", "No inbox connected", "")
    cfg = load_config(gmail._gmail_config_file(), gmail.GmailConfig) or gmail.GmailConfig()
    if not cfg.process_incoming:
        return CheckResult(
            "inbox_reaches_agent", "ok", "Email doesn't reach the agent", "",
        )
    if policy.email_allowed_senders:
        return CheckResult(
            "inbox_reaches_agent", "ok", "Only allowed senders reach the agent", "",
        )
    if policy.auto_mode:
        return CheckResult(
            "inbox_reaches_agent", "warn", "Every email reaches the agent",
            "Anyone can email you while Auto mode is on. Turn it off or add allowed senders.",
        )
    return CheckResult(
        "inbox_reaches_agent", "info", "Every email reaches the agent", "",
    )


def _check_discord() -> CheckResult:
    from craftos_integrations import has_credential, load_config
    from craftos_integrations.providers.discord import client as discord

    if not has_credential(discord.DiscordClient.spec.cred_file):
        return CheckResult("discord_senders_limited", "ok", "Discord isn't connected", "")
    cfg = load_config(discord._discord_config_file(), discord.DiscordConfig) or discord.DiscordConfig()
    lists = (
        cfg.self_usernames,
        cfg.self_role_names,
        cfg.self_user_ids,
        cfg.third_party_usernames,
        cfg.third_party_role_names,
        cfg.third_party_user_ids,
    )
    if cfg.mention_only or any(lists):
        return CheckResult(
            "discord_senders_limited", "ok", "Discord messages are limited", "",
        )
    return CheckResult(
        "discord_senders_limited", "warn", "Every Discord message reaches the agent",
        "Require a mention or list who may write, in Settings > Integrations > Discord.",
    )


CHECKS: List[Callable[[], CheckResult]] = [
    _check_secret_files,
    _check_bind_address,
    _check_audit_chain,
    _check_level,
    _check_auto_mode,
    _check_mcp_changes,
    _check_mcp_pins,
    _check_memory_files,
    _check_runtime_files,
    _check_prompt_logging,
    _check_web_guard,
    _check_inbox,
    _check_discord,
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


def _fix_mcp_changes() -> int:
    from app.security import mcp_trust

    return mcp_trust.trust_current()


def _fix_memory_files() -> int:
    from app.security import memory_guard

    return sum(1 for entry in memory_guard.untrusted_files() if memory_guard.trust(entry["name"]))


def _fix_runtime_files() -> int:
    return sum(1 for p in runtime_secret_files() if restrict_to_owner(p))


FIXES: Dict[str, Callable[[], int]] = {
    "runtime_files_private": _fix_runtime_files,
    "secret_files_private": _fix_secret_files,
    "mcp_servers_unchanged": _fix_mcp_changes,
    "memory_files_trusted": _fix_memory_files,
}


def apply_fix(fix_id: str) -> bool:
    fix = FIXES.get(fix_id)
    if fix is None:
        return False
    fix()
    return True
