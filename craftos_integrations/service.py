"""Common-ops facade + metadata.

Thin, platform-agnostic wrappers:
- is_connected, list_connected, status
- Per-integration UI metadata + runtime config, read off the PROVIDERS
  (``providers/<id>/provider.py``).
CONNECTING is the IntegrationSystem's job, not this module's:
token connect goes through ``_helpers.system_connect_token`` and OAuth through
``IntegrationSystem.add_account``, both of which store real multi-account
credentials.

Anything that touches a real account goes through the IntegrationSystem, which
binds a client to one account's credential:

    client = system.client_for("discord", identity)
    await client.join_voice(guild_id, channel_id)

``get_client(platform_id)`` returns the UNBOUND singleton. It carries no
credential — only the class registry populated by ``@register_client`` — so it
is useful for capability checks, not for calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from dataclasses import asdict, fields as dc_fields

from .credentials_store import has_config, load_config, save_config


def _resolve_provider(integration: str):
    """Resolve a shipped provider by id, or None. Providers carry the
    metadata and runtime-config declarations as of 2026-08-26."""
    from .providers import get_provider

    return get_provider(integration)


# ════════════════════════════════════════════════════════════════════════
# Common ops
# ════════════════════════════════════════════════════════════════════════


def _stored_accounts(integration: str) -> List[Dict[str, str]]:
    """Accounts from the multi-account AccountSet document, read-only.

    The account document is the only credential store."""
    try:
        from .core.accounts import AccountSet
        from .core.storage import FileCredentialStore

        raw = FileCredentialStore().load(integration)
        if not raw:
            return []
        account_set = AccountSet.from_dict(raw)
        return [
            {"display": record.alias or identity, "id": identity}
            for identity, record in account_set.accounts.items()
        ]
    except Exception:
        return []


def is_connected(integration: str) -> bool:
    """True if the integration has at least one connected account."""
    return bool(_stored_accounts(integration))


def list_connected() -> List[str]:
    """Ids of integrations that have at least one connected account."""
    return [pid for pid in list_all() if _stored_accounts(pid)]


def list_all() -> List[str]:
    """Every integration id the app knows about.

    Sourced from the provider registry, which is the enumeration source
    for everything user-facing.
    """
    from .providers import provider_ids

    return provider_ids()


async def status(integration: str) -> Tuple[bool, str]:
    """Connection status line for an integration."""
    info = await get_integration_info(integration)
    if info is None:
        return False, f"Unknown integration: {integration}"
    if not info["connected"]:
        return True, f"{info['name']}: Not connected"
    lines = [f"{info['name']}: Connected"]
    for account in info.get("accounts", []):
        display = account.get("display", "")
        acct_id = account.get("id", "")
        if display and acct_id and display != acct_id:
            lines.append(f"  - {display} ({acct_id})")
        else:
            lines.append(f"  - {display or acct_id}")
    return True, "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════
# Metadata
# ════════════════════════════════════════════════════════════════════════


def get_metadata(integration: str) -> Optional[Dict[str, Any]]:
    """Static UI metadata for an integration (no I/O).

    Read off the provider, which carries the metadata as of 2026-08-26.
    ``provider_metadata`` reproduces the dict shape this returned when the
    handlers were the source, so consumers are unchanged.
    """
    from .contracts import provider_metadata
    from .providers import get_provider

    provider = get_provider(integration)
    if provider is None:
        return None
    return provider_metadata(provider)


def list_metadata() -> List[Dict[str, Any]]:
    """Static UI metadata for every shipped integration."""
    return [m for name in list_all() if (m := get_metadata(name))]


# ════════════════════════════════════════════════════════════════════════
# Per-integration runtime config (post-connect knobs)
# ════════════════════════════════════════════════════════════════════════


def _config_filename(integration: str) -> str:
    """``<integration>_config.json`` — config and credential files stay
    visually paired in ``.credentials/``.

    Derived from the handler's ``spec.cred_file`` stem until 2026-08-26. The
    two agree for all 11 integrations that declare runtime config (only the
    four Google credential files diverge from ``<id>.json`` and none of them
    has config), so moving to the provider id changed no filename.
    """
    return f"{integration}_config.json"


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
    """Return the provider's ``config_fields`` schema, or ``None`` if the
    integration declares no runtime config."""
    provider = _resolve_provider(integration)
    if provider is None or getattr(provider, "config_class", None) is None:
        return None
    return [dict(f) for f in (getattr(provider, "config_fields", None) or [])]


def get_config(integration: str) -> Optional[Dict[str, Any]]:
    """Return the integration's current config as a plain dict.

    If no config has been saved yet, returns the dataclass defaults so the
    frontend can pre-populate the form. Returns ``None`` if the integration
    declares no ``config_class`` at all."""
    provider = _resolve_provider(integration)
    if provider is None:
        return None
    cls = getattr(provider, "config_class", None)
    if cls is None:
        return None
    fname = _config_filename(integration)
    obj = load_config(fname, cls) if has_config(fname) else cls()
    if obj is None:
        obj = cls()
    return asdict(obj)


def update_config(integration: str, values: Dict[str, Any]) -> Tuple[bool, str]:
    """Coerce ``values`` per the handler's ``config_fields`` schema, build
    a fresh ``config_class`` instance, persist it. Unknown keys are dropped.
    Missing keys keep their dataclass defaults (so a partial UI update is
    safe — the user can edit one field without resetting the others)."""
    provider = _resolve_provider(integration)
    if provider is None:
        return False, f"Unknown integration: {integration}"
    cls = getattr(provider, "config_class", None)
    if cls is None:
        return False, f"{integration} has no config_class declared"
    schema = getattr(provider, "config_fields", None) or []
    type_by_key = {f["key"]: f.get("type", "text") for f in schema}
    valid_keys = {fld.name for fld in dc_fields(cls)}

    fname = _config_filename(integration)
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
    return True, f"{getattr(provider, 'display_name', '') or integration} config saved"


async def get_integration_info(integration: str) -> Optional[Dict[str, Any]]:
    """Static metadata + live connection status.

    Connection state comes from the AccountSet document, which is the only
    credential store.
    """
    metadata = get_metadata(integration)
    if metadata is None:
        return None
    accounts: List[Dict[str, str]] = _stored_accounts(integration)
    metadata["connected"] = bool(accounts)
    metadata["accounts"] = accounts
    return metadata


async def list_integrations() -> List[Dict[str, Any]]:
    """Metadata + live connection status for every shipped integration."""
    out: List[Dict[str, Any]] = []
    for name in list_all():
        info = await get_integration_info(name)
        if info:
            out.append(info)
    return out


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


def get_integration_info_sync(integration: str) -> Optional[Dict[str, Any]]:
    return _run_sync(get_integration_info(integration))


def get_integration_auth_type(integration: str) -> str:
    meta = get_metadata(integration)
    return meta["auth_type"] if meta else "token"


def get_integration_fields(integration: str) -> List[Dict[str, Any]]:
    meta = get_metadata(integration)
    return list(meta["fields"]) if meta else []


def integration_registry() -> Dict[str, Dict[str, Any]]:
    """Snapshot of metadata, keyed by integration id (rebuilt on each call)."""
    return {m["id"]: m for m in list_metadata()}
