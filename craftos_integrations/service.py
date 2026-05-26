"""Common-ops facade + metadata + connect dispatchers.

Thin wrappers over the registry for everything that is platform-agnostic:
- send_message, is_connected, list_connected, disconnect, status
- Per-integration UI metadata (display_name, description, auth_type, fields)
- connect_token / connect_oauth / connect_interactive dispatchers

For platform-specific features (Discord voice, Jira transitions, LinkedIn UGC
posts, Gmail send, etc.) callers should reach for the typed client directly:

    from craftos_integrations import get_client
    discord = get_client("discord")
    await discord.join_voice(guild_id, channel_id)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from dataclasses import asdict, fields as dc_fields

from .credentials_store import has_config, load_config, save_config
from .registry import (
    autoload_integrations,
    get_all_clients,
    get_client,
    get_handler,
    get_registered_handler_names,
)


def _resolve_handler(integration: str):
    """Autoload + resolve handler. Returns ``(handler, None)`` on success or
    ``(None, "Unknown integration: ...")`` if the name is unregistered."""
    autoload_integrations()
    handler = get_handler(integration)
    if handler is None:
        return None, f"Unknown integration: {integration}"
    return handler, None


# ════════════════════════════════════════════════════════════════════════
# Common ops
# ════════════════════════════════════════════════════════════════════════


async def send_message(
    integration: str, recipient: str, text: str, **kwargs
) -> Dict[str, Any]:
    """Send a message via any platform's BasePlatformClient.send_message."""
    autoload_integrations()
    client = get_client(integration)
    if client is None:
        return {"error": f"Unknown integration: {integration}"}
    return await client.send_message(recipient, text, **kwargs)


def is_connected(integration: str) -> bool:
    """True if the integration has stored credentials."""
    autoload_integrations()
    client = get_client(integration)
    if client is None:
        return False
    try:
        return bool(client.has_credentials())
    except Exception:
        return False


def list_connected() -> List[str]:
    """Names of platforms that currently have credentials."""
    autoload_integrations()
    out: List[str] = []
    for pid, client in get_all_clients().items():
        try:
            if client.has_credentials():
                out.append(pid)
        except Exception:
            pass
    return out


def list_all() -> List[str]:
    """Names of every registered integration handler."""
    autoload_integrations()
    return get_registered_handler_names()


async def disconnect(
    integration: str, account_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Run the integration's logout flow."""
    handler, err = _resolve_handler(integration)
    if err:
        return False, err
    args = [account_id] if account_id else []
    return await handler.logout(args)


async def status(integration: str) -> Tuple[bool, str]:
    """Run the integration's status check."""
    handler, err = _resolve_handler(integration)
    if err:
        return False, err
    return await handler.status()


# ════════════════════════════════════════════════════════════════════════
# Metadata
# ════════════════════════════════════════════════════════════════════════


def get_metadata(integration: str) -> Optional[Dict[str, Any]]:
    """Static UI metadata for an integration (no I/O)."""
    autoload_integrations()
    handler = get_handler(integration)
    if handler is None:
        return None
    config_class = getattr(handler, "config_class", None)
    config_fields = getattr(handler, "config_fields", []) or []
    return {
        "id": integration,
        "name": handler.display_name or integration,
        "description": handler.description,
        "auth_type": handler.auth_type,
        "fields": [dict(f) for f in handler.fields],
        "icon": getattr(handler, "icon", "") or "",
        "has_config": config_class is not None,
        "config_fields": [dict(f) for f in config_fields] if config_class else None,
        "connect_help": getattr(handler, "connect_help", None),
    }


def list_metadata() -> List[Dict[str, Any]]:
    """Static UI metadata for every registered integration."""
    autoload_integrations()
    return [m for name in get_registered_handler_names() if (m := get_metadata(name))]


# ════════════════════════════════════════════════════════════════════════
# Per-integration runtime config (post-connect knobs)
# ════════════════════════════════════════════════════════════════════════


def _config_filename(handler) -> str:
    """Derive the config filename from the handler's spec.

    Convention: ``<cred_file_stem>_config.json``. So ``github.json`` →
    ``github_config.json``, ``whatsapp_web.json`` → ``whatsapp_web_config.json``.
    Keeps config and credential files visually paired in ``.credentials/``."""
    stem = handler.spec.cred_file
    if stem.endswith(".json"):
        stem = stem[:-5]
    return f"{stem}_config.json"


def _coerce(value: Any, type_: str) -> Any:
    """Coerce an incoming UI value to the type the dataclass expects.

    The frontend sends strings/lists/booleans; the dataclass may want int
    or list. This is the only place we apply per-type coercion."""
    if value is None:
        return None
    if type_ == "number":
        try:
            if isinstance(value, str):
                return int(value) if "." not in value else float(value)
            return value
        except (TypeError, ValueError):
            return value
    if type_ == "checkbox":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if type_ == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return list(value or [])
    # text / textarea / select → string
    return value if isinstance(value, str) else str(value)


def get_config_schema(integration: str) -> Optional[List[Dict[str, Any]]]:
    """Return the handler's ``config_fields`` schema, or ``None`` if the
    integration declares no runtime config."""
    handler, _ = _resolve_handler(integration)
    if handler is None:
        return None
    if getattr(handler, "config_class", None) is None:
        return None
    return [dict(f) for f in (handler.config_fields or [])]


def get_config(integration: str) -> Optional[Dict[str, Any]]:
    """Return the integration's current config as a plain dict.

    If no config has been saved yet, returns the dataclass defaults so the
    frontend can pre-populate the form. Returns ``None`` if the integration
    declares no ``config_class`` at all."""
    handler, _ = _resolve_handler(integration)
    if handler is None:
        return None
    cls = getattr(handler, "config_class", None)
    if cls is None:
        return None
    fname = _config_filename(handler)
    obj = load_config(fname, cls) if has_config(fname) else cls()
    if obj is None:
        obj = cls()
    return asdict(obj)


def update_config(integration: str, values: Dict[str, Any]) -> Tuple[bool, str]:
    """Coerce ``values`` per the handler's ``config_fields`` schema, build
    a fresh ``config_class`` instance, persist it. Unknown keys are dropped.
    Missing keys keep their dataclass defaults (so a partial UI update is
    safe — the user can edit one field without resetting the others)."""
    handler, err = _resolve_handler(integration)
    if err:
        return False, err
    cls = getattr(handler, "config_class", None)
    if cls is None:
        return False, f"{integration} has no config_class declared"
    schema = handler.config_fields or []
    type_by_key = {f["key"]: f.get("type", "text") for f in schema}
    valid_keys = {fld.name for fld in dc_fields(cls)}

    fname = _config_filename(handler)
    existing = load_config(fname, cls) if has_config(fname) else cls()
    if existing is None:
        existing = cls()
    merged = asdict(existing)
    for k, raw in (values or {}).items():
        if k not in valid_keys:
            continue
        merged[k] = _coerce(raw, type_by_key.get(k, "text"))
    try:
        new_obj = cls(**merged)
    except TypeError as e:
        return False, f"Invalid config values: {e}"
    save_config(fname, new_obj)
    return True, f"{handler.display_name or integration} config saved"


# ════════════════════════════════════════════════════════════════════════
# Status parsing
# ════════════════════════════════════════════════════════════════════════


def parse_status_accounts(status_message: str) -> List[Dict[str, str]]:
    """Extract per-account info from a handler.status() message.

    Status messages look like:
        "Integration: Connected
          - Account Name (account_id)"
    """
    accounts: List[Dict[str, str]] = []
    for raw_line in status_message.split("\n"):
        line = raw_line.strip()
        if line.startswith("- "):
            info = line[2:].strip()
            if "(" in info and info.endswith(")"):
                name_part = info[: info.rfind("(")].strip()
                id_part = info[info.rfind("(") + 1 : -1].strip()
                accounts.append({"display": name_part, "id": id_part})
            else:
                accounts.append({"display": info, "id": info})
    return accounts


async def get_integration_info(integration: str) -> Optional[Dict[str, Any]]:
    """Static metadata + live connection status (async; calls handler.status())."""
    metadata = get_metadata(integration)
    if metadata is None:
        return None
    handler = get_handler(integration)
    connected = False
    accounts: List[Dict[str, str]] = []
    try:
        _, status_msg = await handler.status()
        if "Connected" in status_msg and "Not connected" not in status_msg:
            connected = True
            accounts = parse_status_accounts(status_msg)
    except Exception:
        pass
    metadata["connected"] = connected
    metadata["accounts"] = accounts
    return metadata


async def list_integrations() -> List[Dict[str, Any]]:
    """Metadata + live connection status for every registered integration."""
    autoload_integrations()
    out: List[Dict[str, Any]] = []
    for name in get_registered_handler_names():
        info = await get_integration_info(name)
        if info:
            out.append(info)
    return out


# ════════════════════════════════════════════════════════════════════════
# Connect dispatchers — auto-start the matching listener on success
# ════════════════════════════════════════════════════════════════════════


async def _start_listener_for_handler(handler) -> None:
    """If a manager is running, start the listener for this handler's platform."""
    from .manager import get_external_comms_manager

    manager = get_external_comms_manager()
    if manager is None:
        return
    spec = getattr(handler, "spec", None)
    platform_id = getattr(spec, "platform_id", None) if spec else None
    if not platform_id:
        return
    try:
        await manager.start_platform(platform_id)
    except Exception:
        pass


async def connect_token(
    integration: str, credentials: Dict[str, str], *, start_listener: bool = True
) -> Tuple[bool, str]:
    """Token-based connect: dispatch to handler.connect_token() and start listener on success."""
    handler, err = _resolve_handler(integration)
    if err:
        return False, err
    success, message = await handler.connect_token(credentials)
    if success and start_listener:
        await _start_listener_for_handler(handler)
    return success, message


async def connect_oauth(
    integration: str, *, start_listener: bool = True
) -> Tuple[bool, str]:
    """OAuth-based connect: dispatch to handler.connect_oauth() and start listener on success."""
    handler, err = _resolve_handler(integration)
    if err:
        return False, err
    if handler.auth_type not in ("oauth", "both"):
        return False, f"OAuth not supported for {integration}"
    success, message = await handler.connect_oauth()
    if success and start_listener:
        await _start_listener_for_handler(handler)
    return success, message


async def connect_interactive(
    integration: str, *, start_listener: bool = True
) -> Tuple[bool, str]:
    """Interactive (e.g. QR) connect: dispatch to handler.connect_interactive() and start listener on success."""
    handler, err = _resolve_handler(integration)
    if err:
        return False, err
    if handler.auth_type not in ("interactive", "token_with_interactive"):
        return False, f"Interactive login not supported for {integration}"
    success, message = await handler.connect_interactive()
    if success and start_listener:
        await _start_listener_for_handler(handler)
    return success, message


# ════════════════════════════════════════════════════════════════════════
# Sync wrappers — for sync callers that can't await
# ════════════════════════════════════════════════════════════════════════


def _run_sync(coro):
    """Run an async coroutine from sync code by spinning a fresh event loop.

    WARNING: must NOT be called from inside an already-running event loop —
    ``loop.run_until_complete`` will raise ``RuntimeError: This event loop is
    already running``. The ``*_sync`` helpers in this module are intended for
    purely synchronous call sites (REPL, scripts). From an async context,
    use the async variant directly (``await list_integrations()`` etc.).
    """
    import asyncio as _asyncio

    loop = _asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def list_integrations_sync() -> List[Dict[str, Any]]:
    return _run_sync(list_integrations())


def get_integration_info_sync(integration: str) -> Optional[Dict[str, Any]]:
    return _run_sync(get_integration_info(integration))


def get_integration_accounts(integration: str) -> List[Dict[str, str]]:
    info = get_integration_info_sync(integration)
    return info.get("accounts", []) if info else []


def get_integration_auth_type(integration: str) -> str:
    meta = get_metadata(integration)
    return meta["auth_type"] if meta else "token"


def get_integration_fields(integration: str) -> List[Dict[str, Any]]:
    meta = get_metadata(integration)
    return list(meta["fields"]) if meta else []


def integration_registry() -> Dict[str, Dict[str, Any]]:
    """Snapshot of metadata, keyed by integration id (rebuilt on each call)."""
    return {m["id"]: m for m in list_metadata()}
