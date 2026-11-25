"""Only start MCP servers as they were saved through CraftBot's settings.

Hermes Agent's June 2026 "hermes-0day" campaign planted an MCP entry that
re-ran an attacker's command at every start: config that the agent (or a
command it runs) can write, and that later starts a process, is a
privileged sink. Hermes answers with text patterns and a blocklist; this
records provenance instead.

Every time a server is saved through CraftBot's own paths (Settings > MCP,
the /mcp command, a profile bundle import the user starts), a fingerprint
of what it runs is stored: transport, command, arguments, working
directory, URL. With "Only start MCP servers saved in Settings" on
(Enhanced, Strict), a server whose entry no longer matches its fingerprint
(edited on disk, for example by a command the agent ran) is not started
until the user confirms it in Settings > Security > Security check.

The first time the check runs, the servers configured at that moment are
taken as the user's (trust on first use).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.security.files import ensure_private_dir, write_private_json
from app.security.policy import get_policy

_lock = threading.Lock()


def _field(server: Any, name: str):
    return server.get(name) if isinstance(server, dict) else getattr(server, name, None)


def fingerprint(server: Any) -> str:
    """What starting this server runs: transport, command, args, cwd, URL."""
    runs = {
        "transport": _field(server, "transport") or "stdio",
        "command": _field(server, "command"),
        "args": list(_field(server, "args") or []),
        "cwd": _field(server, "cwd"),
        "url": _field(server, "url"),
    }
    return hashlib.sha256(json.dumps(runs, sort_keys=True).encode("utf-8")).hexdigest()


def ledger_path() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / ".security" / "mcp_trusted.json"


def config_path() -> Path:
    from app.config import APP_CONFIG_PATH

    return APP_CONFIG_PATH / "mcp_config.json"


def _read_ledger() -> Optional[Dict[str, str]]:
    try:
        data = json.loads(ledger_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _configured_servers() -> List[dict]:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [s for s in data.get("mcp_servers") or [] if isinstance(s, dict) and s.get("name")]


def record(servers: Iterable[Any]) -> None:
    """Trust these servers as saved now (called by CraftBot's own save paths)."""
    with _lock:
        ledger = _read_ledger() or {}
        for server in servers:
            name = _field(server, "name")
            if name:
                ledger[name] = fingerprint(server)
        ensure_private_dir(ledger_path().parent)
        write_private_json(ledger_path(), ledger)


def _ledger_or_first_use() -> Dict[str, str]:
    ledger = _read_ledger()
    if ledger is None:
        record(_configured_servers())
        ledger = _read_ledger() or {}
    return ledger


def refusal(server: Any) -> Optional[str]:
    """None when this server may start; otherwise why it was held back."""
    if not get_policy().verify_mcp_servers:
        return None
    name = _field(server, "name")
    if _ledger_or_first_use().get(name) == fingerprint(server):
        return None
    return (
        f"MCP server '{name}' was changed outside CraftBot's settings, so it was "
        f"not started. Review it in Settings > MCP and save it, or confirm it in "
        f"Settings > Security > Security check."
    )


def changed_servers() -> List[str]:
    """Enabled servers whose entry no longer matches what was saved."""
    ledger = _ledger_or_first_use()
    return [
        s["name"]
        for s in _configured_servers()
        if s.get("enabled", True) and ledger.get(s["name"]) != fingerprint(s)
    ]


def trust_current() -> int:
    """The user confirmed the servers as configured now."""
    servers = _configured_servers()
    record(servers)
    return len(servers)
