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


def _check_mcp_changes() -> CheckResult:
    from app.security import mcp_trust
    from app.security.policy import get_policy

    if not get_policy().verify_mcp_servers:
        return CheckResult(
            "mcp_servers_unchanged",
            "info",
            "MCP servers start as configured",
            "Any change to an MCP server's command takes effect on the next start. "
            "Enhanced and Strict start only servers saved in Settings.",
        )
    changed = mcp_trust.changed_servers()
    if not changed:
        return CheckResult(
            "mcp_servers_unchanged",
            "ok",
            "MCP servers match what was saved in Settings",
            "No server's command was changed outside CraftBot's settings.",
        )
    return CheckResult(
        "mcp_servers_unchanged",
        "warn",
        "MCP servers were changed outside Settings",
        f"Not started until you confirm them: {', '.join(changed)}. Fix trusts them "
        f"as they are now; review their commands in Settings > MCP first.",
        fix_id="mcp_servers_unchanged",
    )


def _check_mcp_pins() -> CheckResult:
    from app.security import mcp_pins, mcp_trust

    unpinned = mcp_pins.unpinned_servers(mcp_trust._configured_servers())
    if not unpinned:
        return CheckResult(
            "mcp_packages_pinned", "ok", "MCP packages have fixed versions",
            "No enabled MCP server downloads a different package version on its own.",
        )
    shown = ", ".join(f"{name} ({spec})" for name, spec in unpinned[:5])
    more = f" and {len(unpinned) - 5} more" if len(unpinned) > 5 else ""
    return CheckResult(
        "mcp_packages_pinned", "warn", "Some MCP servers run the newest package version",
        f"These download whatever version is newest at each start, so a change by the "
        f"package's publisher runs here without review: {shown}{more}. Add a version "
        f"in Settings > MCP, for example package@1.2.3 or package==1.2.3.",
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
            "runtime_files_private", "ok", "Session and audit files are private",
            "Windows keeps them in your user profile.",
        )
    exposed = [p for p in runtime_secret_files() if not is_private(p)]
    if not exposed:
        return CheckResult(
            "runtime_files_private", "ok", "Session and audit files are private",
            "The session token, audit log and MCP trust records are readable by your user only.",
        )
    return CheckResult(
        "runtime_files_private", "fail", "Session or audit files are readable by other users",
        f"{len(exposed)} file(s): {', '.join(p.name for p in exposed[:5])}.",
        fix_id="runtime_files_private",
    )


def _check_prompt_logging() -> CheckResult:
    from app.security.policy import get_policy

    if get_policy().log_prompts:
        return CheckResult(
            "prompts_not_logged", "info", "Full prompts are written to the logs",
            "Useful for debugging, but the logs then hold your conversations and "
            "anything the agent read. Enhanced and Strict turn this off.",
        )
    return CheckResult(
        "prompts_not_logged", "ok", "Prompts stay out of the logs",
        "Only metadata about AI calls is recorded.",
    )


def _check_web_guard() -> CheckResult:
    from app.security.policy import get_policy

    if get_policy().network_guard:
        return CheckResult(
            "web_requests_public_only", "ok", "Web requests reach public sites only",
            "This computer, the local network and cloud metadata services are refused.",
        )
    return CheckResult(
        "web_requests_public_only", "info", "Web requests are checked on the first request only",
        "A redirect can still lead the agent's web tools into your local network. "
        "Enhanced and Strict check every redirect.",
    )


def _check_inbox() -> CheckResult:
    from craftos_integrations import has_credential, load_config
    from craftos_integrations.providers.gmail import client as gmail

    from app.security.policy import get_policy

    policy = get_policy()
    if not has_credential(gmail.GmailClient.spec.cred_file):
        return CheckResult("inbox_reaches_agent", "ok", "No inbox connected", "Gmail is not connected.")
    cfg = load_config(gmail._gmail_config_file(), gmail.GmailConfig) or gmail.GmailConfig()
    if not cfg.process_incoming:
        return CheckResult(
            "inbox_reaches_agent", "ok", "Incoming email does not reach the agent",
            "Gmail is connected with incoming processing off.",
        )
    if policy.email_allowed_senders:
        return CheckResult(
            "inbox_reaches_agent", "ok", "Only listed senders' email reaches the agent",
            f"{len(policy.email_allowed_senders)} sender(s) allowed.",
        )
    if policy.auto_mode:
        return CheckResult(
            "inbox_reaches_agent", "warn", "Every email in your inbox reaches the agent",
            "Anyone can send you an email, and with Auto mode on the agent can act on "
            "what it asks. Turn Auto mode off, or list the senders under Channels.",
        )
    return CheckResult(
        "inbox_reaches_agent", "info", "Every email in your inbox reaches the agent",
        "Auto mode is off, so actions after reading an email wait for your approval.",
    )


def _check_discord() -> CheckResult:
    from craftos_integrations import has_credential, load_config
    from craftos_integrations.providers.discord import client as discord

    from app.security.policy import get_policy

    if not has_credential(discord.DiscordClient.spec.cred_file):
        return CheckResult("discord_senders_limited", "ok", "Discord is not connected", "")
    cfg = load_config(discord._discord_config_file(), discord.DiscordConfig) or discord.DiscordConfig()
    lists = (
        cfg.self_usernames,
        cfg.self_role_names,
        cfg.self_user_ids,
        cfg.third_party_usernames,
        cfg.third_party_role_names,
        cfg.third_party_user_ids,
    )
    if cfg.mention_only or any(lists) or get_policy().strict_channel_identity:
        return CheckResult(
            "discord_senders_limited", "ok", "Discord messages are limited",
            "The bot needs a mention, or only listed people reach the agent.",
        )
    return CheckResult(
        "discord_senders_limited", "warn", "Every Discord message the bot sees reaches the agent",
        "Anyone in any server or channel the bot is in can write to the agent. Require a "
        "mention or list who may, in Settings > Integrations > Discord.",
    )


CHECKS: List[Callable[[], CheckResult]] = [
    _check_secret_files,
    _check_bind_address,
    _check_audit_chain,
    _check_level,
    _check_auto_mode,
    _check_mcp_changes,
    _check_mcp_pins,
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


def _fix_runtime_files() -> int:
    return sum(1 for p in runtime_secret_files() if restrict_to_owner(p))


FIXES: Dict[str, Callable[[], int]] = {
    "runtime_files_private": _fix_runtime_files,
    "secret_files_private": _fix_secret_files,
    "mcp_servers_unchanged": _fix_mcp_changes,
}


def apply_fix(fix_id: str) -> bool:
    fix = FIXES.get(fix_id)
    if fix is None:
        return False
    fix()
    return True
