"""Action-side helpers — collapse the repeated try/has_credentials/wrap pattern.

Each action used to be ~14 lines of skeleton wrapped around a single
client method call. With ``run_client`` an action becomes ~5 lines:

    from app.data.action.integrations._helpers import run_client

    @action(name="send_discord_message", ...)
    async def send_discord_message(input_data: dict) -> dict:
        return await run_client(
            "discord", "bot_send_message",
            channel_id=input_data["channel_id"],
            content=input_data["content"],
        )

For sync actions, use ``run_client_sync`` (same API, no await).

Some clients return ``{"ok": True, "result": ...}`` / ``{"error": ...}``
envelopes (Outlook, Jira, etc.). ``_shape_result`` collapses that
transport envelope automatically — the agent never sees a nested
``{"ok": true, "result": ...}`` wrapper inside the action result, and
envelope failures surface as ``{"status": "error"}`` instead of being
buried under a success wrapper. ``unwrap_envelope=True`` is still
accepted for backward compatibility (it additionally treats ANY dict
containing an ``error`` key as a failure). Pair with
``success_message="..."`` when the action should report a fixed success
string instead of the inner result.

Actions that do real pre/post-processing (parsing labels, recording to
conversation history, building complex payloads) keep their explicit
form — the helper is only for the boilerplate-heavy 80% case.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional


# Common aliases the agent/user might use → canonical registered integration id.
# Google Workspace apps in particular are frequently referred to by short names
# or lumped under "google", which is not itself an integration.
#
# These live here (not in an action module) because action handlers are executed
# via exec() on their own extracted source — module-level names in the action
# file are NOT in scope at runtime. Handlers must import these inside the function
# body, the same way they import run_client/with_client.
INTEGRATION_ALIASES = {
    "mail": "gmail",
    "googlemail": "gmail",
    "google mail": "gmail",
    "drive": "google_drive",
    "gdrive": "google_drive",
    "googledrive": "google_drive",
    "google drive": "google_drive",
    "docs": "google_docs",
    "gdocs": "google_docs",
    "googledocs": "google_docs",
    "google docs": "google_docs",
    "google_doc": "google_docs",
    "calendar": "google_calendar",
    "gcal": "google_calendar",
    "gcalendar": "google_calendar",
    "google calendar": "google_calendar",
    "youtube": "google_youtube",
}

# Umbrella terms that aren't a single integration — Google Workspace apps are
# tracked individually, so callers must check the specific app.
GOOGLE_UMBRELLA = {
    "google",
    "google workspace",
    "google_workspace",
    "workspace",
    "gsuite",
    "g suite",
    "google suite",
}
GOOGLE_FAMILY = (
    "gmail",
    "google_drive",
    "google_docs",
    "google_calendar",
    "google_youtube",
)


def normalize_integration_id(integration_id: str) -> str:
    """Map a user/agent-supplied integration name through known aliases."""
    return INTEGRATION_ALIASES.get(integration_id, integration_id)


def record_outgoing_message(platform_name: str, recipient: str, text: str) -> None:
    """Best-effort: record an outgoing platform message into the agent's conversation history.

    Used by integration actions that send messages on behalf of the agent
    (Telegram, WhatsApp, etc.) so the conversation transcript reflects what
    the agent emitted, not just what came back. Silently no-ops if the
    state manager is not reachable — never raises.
    """
    try:
        import app.internal_action_interface as iai

        sm = iai.InternalActionInterface.state_manager
        if sm:
            label = f"[Sent via {platform_name} to {recipient}]: {text}"
            sm.record_agent_message(label, platform=platform_name)
    except Exception:
        pass


def _resolve_handler(integration: str):
    """Resolve a handler by handler-name first, then by client platform_id (e.g. 'google_workspace' -> google handler)."""
    try:
        from craftos_integrations import get_handler, get_registered_handler_names

        handler = get_handler(integration)
        if handler is not None:
            return handler, integration
        for name in get_registered_handler_names():
            h = get_handler(name)
            spec = getattr(h, "spec", None)
            if spec and getattr(spec, "platform_id", None) == integration:
                return h, name
    except Exception:
        pass
    return None, integration


def _no_cred_message(integration: str) -> str:
    handler, slash_name = _resolve_handler(integration)
    display = handler.display_name if handler and handler.display_name else integration
    return f"No {display} credential. Use /{slash_name} login first."


def _shape_result(
    raw: Any,
    *,
    unwrap_envelope: bool,
    success_message: Optional[str],
    fail_message: str,
) -> Dict[str, Any]:
    """Translate a client return value into the action response envelope.

    The ``{"ok": ...}`` transport envelope some clients emit is ALWAYS
    collapsed — previously (without ``unwrap_envelope=True``) the agent got
    a double-nested ``{"status": "success", "result": {"ok": true,
    "result": ...}}`` on every call, and envelope failures were wrapped as
    successes. ``unwrap_envelope`` remains as an opt-in for the looser
    "any dict containing an 'error' key is a failure" interpretation.
    """
    if isinstance(raw, dict):
        # Success envelope: {"ok": True, "result": ...} — or Slack-style
        # bodies where "ok" sits alongside the payload fields.
        if raw.get("ok") is True:
            if success_message:
                return {"status": "success", "message": success_message}
            if set(raw.keys()) == {"ok", "result"}:
                return {"status": "success", "result": raw["result"]}
            return {
                "status": "success",
                "result": {k: v for k, v in raw.items() if k != "ok"},
            }
        # Explicit failure envelope: {"ok": False, "error": ...}
        if raw.get("ok") is False:
            return {"status": "error", "message": raw.get("error", fail_message)}
        # Implicit failure envelope from craftos_integrations.helpers.request:
        # 4xx/5xx HTTP responses (and caught exceptions) return
        # {"error": "API error: 403", "details": "..."} with NO "ok" key.
        # Restricted to exactly that shape by default so a legitimate payload
        # that merely *contains* an "error" field isn't misread as failure;
        # unwrap_envelope=True keeps the looser historical behavior.
        if "error" in raw and (
            unwrap_envelope or set(raw.keys()) <= {"error", "details"}
        ):
            return {
                "status": "error",
                "message": raw.get("error", fail_message),
                "details": raw.get("details"),
            }
        # Clients that pre-wrap their own {"status": "error", ...} (e.g. the
        # WhatsApp bridge) — surface the failure instead of re-wrapping it
        # under a success envelope.
        if raw.get("status") == "error":
            return {
                "status": "error",
                "message": raw.get("message") or raw.get("error", fail_message),
            }
    if success_message:
        return {"status": "success", "message": success_message}
    return {"status": "success", "result": raw}


def pick_result(res: Dict[str, Any], keys) -> Dict[str, Any]:
    """Reduce a successful ``run_client`` result to the named top-level keys.

    Used by write/create/send actions whose provider returns the entire
    mutated object: the agent only needs the id (+ a couple of key fields),
    and can always fetch the full object with the matching ``get_*`` action.
    Non-dict results, error results, and missing keys pass through untouched
    so this is always safe to apply::

        res = await run_client("stripe", "create_customer", ...)
        return pick_result(res, ["id", "status"])
    """
    if res.get("status") == "success" and isinstance(res.get("result"), dict):
        r = res["result"]
        picked = {k: r.get(k) for k in keys if r.get(k) is not None}
        if picked:
            res = {**res, "result": picked}
    return res


def _account_hint() -> Optional[str]:
    """The ``account`` value of the action currently executing, if any.

    Read from the executor's execution context (never threaded through
    action signatures — legacy actions don't declare ``account``; the
    schema is injected centrally by ``account_bridge``). Returns None
    outside an action context (e.g. sandboxed subprocess actions, direct
    calls from host code) — callers fall back to the primary account.
    """
    try:
        from agent_core.core.impl.action.context import current_input_data

        data = current_input_data.get()
        hint = (data or {}).get("account")
        if isinstance(hint, str) and hint.strip():
            return hint.strip()
    except Exception:
        pass
    return None


def _bridge_client_or_error(integration: str):
    """Account-aware client resolution for bridged multi-account platforms.

    Returns ``(client, error_dict, handled)``:
      - ``handled=False`` → the platform has no v2 provider; caller takes
        the legacy singleton path unchanged.
      - ``handled=True`` → the v2 system owns this platform: ``client`` is
        bound to the resolved account (the ``account`` hint from the
        executing action, or the primary), or ``error_dict`` explains the
        failure in self-correcting terms.

    An explicit ``account`` hint on a NON-bridged platform is a loud
    error, not a silent primary fallback — silently sending from the
    wrong account is the one failure mode this whole system exists to
    prevent.
    """
    from craftos_integrations.contracts import AccountResolutionError

    hint = _account_hint()
    system = system_for(integration)
    if system is None:
        if hint:
            return None, {
                "status": "error",
                "message": (
                    f"{integration} does not support account selection yet — "
                    f"retry without the 'account' parameter."
                ),
            }, True
        return None, None, False
    try:
        # list_accounts (not resolve) first: it runs the one-time legacy
        # credential migration and gives a friendlier no-accounts message.
        if not system.list_accounts(integration):
            return None, {
                "status": "error",
                "message": _no_cred_message(integration),
            }, True
        identity = system.resolve(integration, hint)
        return system.client_for(integration, identity), None, True
    except AccountResolutionError as e:
        return None, {"status": "error", "message": str(e)}, True
    except Exception as e:
        return None, {
            "status": "error",
            "message": f"{integration} account resolution failed: {e}",
        }, True


async def run_client(
    integration: str,
    method_name: str,
    *,
    unwrap_envelope: bool = False,
    success_message: Optional[str] = None,
    fail_message: str = "Operation failed",
    **kwargs,
) -> Dict[str, Any]:
    """Resolve client by integration, check creds, call method, wrap result.

    The named method may be sync or async; coroutines are awaited.
    """
    from craftos_integrations import get_client

    client, err, handled = _bridge_client_or_error(integration)
    if err:
        return err
    if not handled:
        client = get_client(integration)
        if client is None:
            return {"status": "error", "message": f"Unknown integration: {integration}"}
        if not client.has_credentials():
            return {"status": "error", "message": _no_cred_message(integration)}
    try:
        method = getattr(client, method_name, None)
        if method is None:
            return {
                "status": "error",
                "message": f"Method {method_name!r} not found on {integration} client",
            }
        raw = method(**kwargs)
        if asyncio.iscoroutine(raw):
            raw = await raw
        result = _shape_result(
            raw,
            unwrap_envelope=unwrap_envelope,
            success_message=success_message,
            fail_message=fail_message,
        )
        if result.get("status") != "error":
            try:
                from app.ui_layer.metrics.collector import MetricsCollector

                collector = MetricsCollector.get_instance()
                if collector:
                    collector.record_integration_call(integration)
            except Exception:
                pass
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def run_client_sync(
    integration: str,
    method_name: str,
    *,
    unwrap_envelope: bool = False,
    success_message: Optional[str] = None,
    fail_message: str = "Operation failed",
    **kwargs,
) -> Dict[str, Any]:
    """Sync flavor of ``run_client`` for sync actions calling sync methods."""
    from craftos_integrations import get_client

    client, err, handled = _bridge_client_or_error(integration)
    if err:
        return err
    if not handled:
        client = get_client(integration)
        if client is None:
            return {"status": "error", "message": f"Unknown integration: {integration}"}
        if not client.has_credentials():
            return {"status": "error", "message": _no_cred_message(integration)}
    try:
        method = getattr(client, method_name, None)
        if method is None:
            return {
                "status": "error",
                "message": f"Method {method_name!r} not found on {integration} client",
            }
        raw = method(**kwargs)
        if asyncio.iscoroutine(raw):
            return {
                "status": "error",
                "message": f"{method_name!r} is async — use run_client (await) instead",
            }
        result = _shape_result(
            raw,
            unwrap_envelope=unwrap_envelope,
            success_message=success_message,
            fail_message=fail_message,
        )
        if result.get("status") != "error":
            try:
                from app.ui_layer.metrics.collector import MetricsCollector

                collector = MetricsCollector.get_instance()
                if collector:
                    collector.record_integration_call(integration)
            except Exception:
                pass
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_client_or_error(integration: str):
    """Resolve a client + run the credential check.

    Returns a tuple ``(client, error_dict)``:
      - on success: ``(client, None)``
      - on failure: ``(None, {"status": "error", "message": ...})``

    Use this in actions that return bespoke result shapes / do multi-step
    logic and can't use ``run_client`` or ``with_client``::

        def my_action(input_data):
            client, err = get_client_or_error("google_workspace")
            if err:
                return err
            ...
    """
    from craftos_integrations import get_client

    client, err, handled = _bridge_client_or_error(integration)
    if err:
        return None, err
    if handled:
        return client, None
    client = get_client(integration)
    if client is None:
        return None, {
            "status": "error",
            "message": f"Unknown integration: {integration}",
        }
    if not client.has_credentials():
        return None, {"status": "error", "message": _no_cred_message(integration)}
    return client, None


# ════════════════════════════════════════════════════════════════════════
# multi-account integration routing for the management actions
#
# The 10 multi-account providers (gmail, google_calendar, google_docs, google_drive,
# google_youtube, outlook, linkedin, notion, hubspot, slack) get their
# connection state, OAuth connect, token connect, and disconnect from the
# IntegrationSystem — the legacy single-account credential files are never
# read or written for them, except by the one-time upgrade migration
# (legacy file present, no AccountSet document → imported as the first account;
# see IntegrationSystem._migrate_legacy).
# Legacy handlers remain the METADATA source (display name, icon, auth_type,
# description, token field schemas) for all integrations.
# ════════════════════════════════════════════════════════════════════════


def system_for(integration_id: str):
    """Return the IntegrationSystem when it knows this provider id.

    Returns None for legacy integrations (or if bootstrap fails), so
    callers fall back to the legacy path unchanged.
    """
    try:
        from app.integrations import get_system

        system = get_system()
        if system.registry.get(integration_id) is not None:
            return system
    except Exception:
        pass
    return None


def accounts_payload(accounts) -> list:
    """Serialize AccountInfo objects into the structured action-result shape
    (same wire shape the settings UI uses — plan §6)."""
    return [
        {
            "identity": a.identity,
            "alias": a.alias,
            "isPrimary": a.is_primary,
            "listen": a.listen,
        }
        for a in accounts
    ]


def account_lines(accounts) -> list:
    """Shared status-text format from plan §6:
    ``- {alias or identity} ({identity}) [primary]``."""
    lines = []
    for a in accounts:
        line = f"- {a.alias or a.identity} ({a.identity})"
        if a.is_primary:
            line += " [primary]"
        lines.append(line)
    return lines


def v2_display_name(system, integration_id: str) -> str:
    """Display name: legacy handler metadata first (still the metadata
    source), falling back to the provider's own display_name."""
    try:
        from craftos_integrations import get_metadata

        meta = get_metadata(integration_id)
        if meta and meta.get("name"):
            return meta["name"]
    except Exception:
        pass
    provider = system.registry.get(integration_id)
    return getattr(provider, "display_name", None) or integration_id


async def list_integrations_merged_async() -> list:
    """Metadata + connection status for every integration, with multi-account provider
    ids sourcing their connection state and accounts from the
    IntegrationSystem instead of the legacy credential files. Legacy
    integrations keep the legacy ``handler.status()`` path unchanged.

    v2 entries carry ``accounts`` in the ManagedAccount wire shape
    ({identity, alias, isPrimary, listen}); legacy entries keep the
    status-parsed ``{display, id}`` shape.
    """
    from craftos_integrations import get_integration_info, get_metadata, list_all

    out = []
    for name in list_all():
        system = system_for(name)
        if system is not None:
            info = get_metadata(name)
            if info is None:
                continue
            infos = system.list_accounts(name)
            info["accounts"] = accounts_payload(infos)
            info["connected"] = bool(infos)
        else:
            info = await get_integration_info(name)
        if info:
            out.append(info)
    return out


def list_integrations_merged() -> list:
    """Sync wrapper. Safe both off-loop (action/handler contexts) and on the
    event-loop thread (metrics collector on the browser WS refresh path) —
    the latter used to attempt a nested ``run_until_complete`` that always
    raised and left dashboard integration counts empty."""
    import asyncio as _asyncio

    try:
        _asyncio.get_running_loop()
    except RuntimeError:
        loop = _asyncio.new_event_loop()
        try:
            return loop.run_until_complete(list_integrations_merged_async())
        finally:
            loop.close()

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_asyncio.run, list_integrations_merged_async()).result()


def _v2_verify_slack_token(credentials: Dict[str, str]):
    """Same verification the legacy SlackHandler.login() runs: prefix check
    + ``auth.test`` with the bot token; same credential dict shape."""
    from dataclasses import asdict

    from craftos_integrations.integrations.slack import SlackCredential, _slack_call

    bot_token = (credentials.get("bot_token") or "").strip()
    if not bot_token.startswith(("xoxb-", "xoxp-")):
        return False, "Invalid token. Expected xoxb-... or xoxp-...", None

    result = _slack_call("POST", "auth.test", {"Authorization": f"Bearer {bot_token}"})
    if "error" in result:
        return False, f"Slack auth failed: {result['error']}", None
    team_id = result.get("team_id", "")
    workspace_name = (credentials.get("workspace_name") or "").strip() or result.get(
        "team", team_id
    )
    credential = asdict(
        SlackCredential(
            bot_token=bot_token,
            workspace_id=team_id,
            team_name=workspace_name,
        )
    )
    return True, f"Slack connected: {workspace_name} ({team_id})", credential


def _v2_verify_notion_token(credentials: Dict[str, str]):
    """Same verification the legacy NotionHandler.login() runs: ``GET
    /users/me`` with the integration token; same credential dict shape,
    plus the bot user id captured as ``bot_id`` so ``identity_of`` gets a
    stable account key. (Without it the credential landed under the
    LEGACY sentinel and a second token connect silently overwrote the
    first account.)"""
    from dataclasses import asdict

    from craftos_integrations.integrations.notion import (
        NOTION_VERSION,
        NotionCredential,
        _notion_call,
    )

    token = (credentials.get("token") or "").strip()
    data = _notion_call(
        "GET",
        "/users/me",
        {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
    )
    if "error" in data:
        return False, f"Notion auth failed: {data['error']}", None
    ws_name = data.get("bot", {}).get("workspace_name", "default")
    credential = asdict(NotionCredential(token=token))
    # The bot user id is workspace-scoped and stable — one integration
    # token = one workspace = one account.
    bot_id = data.get("id")
    if isinstance(bot_id, str) and bot_id.strip():
        credential["bot_id"] = bot_id.strip()
    ws_id = data.get("bot", {}).get("workspace_id")
    if isinstance(ws_id, str) and ws_id.strip():
        credential["workspace_id"] = ws_id.strip()
    return True, f"Notion connected: {ws_name}", credential


def _v2_verify_hubspot_token(credentials: Dict[str, str]):
    """Same verification the legacy HubSpotHandler.login() runs: 'pat-'
    prefix check + ``GET /account-info/v3/details``; same credential dict
    shape (hub_id captured for the account identity)."""
    from dataclasses import asdict

    from craftos_integrations.helpers import request as http_request
    from craftos_integrations.integrations.hubspot import (
        HUBSPOT_API,
        HubSpotCredential,
    )

    token = (credentials.get("access_token") or "").strip()
    if not token.startswith("pat-"):
        return False, "Invalid token. Private App tokens start with 'pat-'.", None

    ping = http_request(
        "GET",
        f"{HUBSPOT_API}/account-info/v3/details",
        headers={"Authorization": f"Bearer {token}"},
        expected=(200,),
    )
    if "error" in ping:
        return False, f"HubSpot auth failed: {ping['error']}", None
    meta = ping.get("result") or {}
    credential = asdict(
        HubSpotCredential(
            access_token=token,
            hub_id=str(meta.get("portalId", "")),
            hub_domain=meta.get("uiDomain", ""),
            auth_kind="token",
        )
    )
    label = meta.get("uiDomain") or meta.get("portalId") or "HubSpot"
    return True, f"HubSpot connected: {label}", credential


_V2_TOKEN_VERIFIERS = {
    "slack": _v2_verify_slack_token,
    "notion": _v2_verify_notion_token,
    "hubspot": _v2_verify_hubspot_token,
}


def system_connect_token(system, integration_id: str, credentials: Dict[str, str]):
    """Manual-token connect for a multi-account provider: validate the token the same
    way the legacy handler's ``login()`` does, then store the credential
    through the integration system (``store_credential``) — never through the legacy
    single-account save. Returns (success, message).
    """
    # Providers may carry their own verifier (the bridge-provider pattern —
    # keeps each platform's connect logic in its provider package); the
    # central table covers the three providers that predate it.
    provider_obj = system.registry.get(integration_id)
    verifier = getattr(provider_obj, "verify_token", None) or _V2_TOKEN_VERIFIERS.get(
        integration_id
    )
    if verifier is None:
        # Mirrors legacy IntegrationHandler.connect_token for field-less
        # (OAuth-only) integrations.
        return (
            False,
            f"Token-based login not supported for "
            f"{v2_display_name(system, integration_id)}",
        )
    try:
        ok, message, credential = verifier(credentials)
    except Exception as e:
        return False, f"{integration_id} token verification failed: {e}"
    if not ok or not credential:
        return False, message

    provider = system.registry.get(integration_id)
    identity = provider.identity_of(credential)
    if not identity:
        # Refuse rather than store under the LEGACY sentinel: a second
        # identity-less connect would land on the same sentinel key and
        # silently REPLACE the first account's credential. The sentinel
        # exists only for pre-multi-account files migrating in.
        return False, (
            f"Could not determine which account this "
            f"{v2_display_name(system, integration_id)} token belongs to — "
            f"connect was aborted so an existing account can't be "
            f"overwritten. Re-check the token and try again."
        )
    system.store_credential(integration_id, identity, credential)
    # Slack has a listener; reconcile so a fresh token starts listening
    # immediately (no-op when no manager is attached / no listener exists).
    system.reconcile_listeners()
    return True, message


def platform_teardown_accounts(integration_id: str, identities) -> None:
    """Platform-specific post-removal cleanup the core can't do.

    whatsapp_web accounts own a live Node/Chromium bridge and a per-account
    session dir; core ``remove_account`` only deletes the AccountSet entry.
    Best-effort, never raises; async teardown is scheduled on the running
    loop when there is one, else run inline.
    """
    identities = [i for i in (identities or []) if i]
    if integration_id != "whatsapp_web" or not identities:
        return
    import asyncio as _asyncio

    try:
        from craftos_integrations.providers.whatsapp_web import teardown_account
    except Exception:
        return

    from craftos_integrations.logger import get_logger

    _log = get_logger(__name__)

    async def _run() -> None:
        for identity in identities:
            try:
                await teardown_account(identity)
            except Exception as e:
                _log.warning(
                    f"[INTEGRATIONS] whatsapp_web teardown for '{identity}' failed: {e}"
                )

    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(_run())
    else:
        loop = _asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


def system_disconnect(system, integration_id: str, account_id=None):
    """Disconnect a multi-account provider through the IntegrationSystem.

    - With ``account_id``: remove just that account (alias or identity
      hints both resolve). Entirely system-managed — legacy has no notion of a
      specific account.
    - Without: remove ALL accounts, then run the legacy handler logout
      as best-effort double-cleanup. Removing the last account also
      deletes the legacy credential file (IntegrationSystem prevents the
      upgrade migration from resurrecting it), so the legacy logout
      normally reports "no credentials found" — it only does real work
      when a stray/corrupt legacy file survived. A legacy failure never
      masks a successful account removal.

    Returns (success, message).
    """
    import asyncio as _asyncio

    if account_id:
        try:
            identity = system.remove_account(integration_id, account_id)
            platform_teardown_accounts(integration_id, [identity])
            return True, f"Removed account '{identity}' from {integration_id}."
        except Exception as e:
            return False, str(e)

    removed = []
    removed_identities = []
    for info in system.list_accounts(integration_id):
        try:
            system.remove_account(integration_id, info.identity)
            removed.append(info.alias or info.identity)
            removed_identities.append(info.identity)
        except Exception:
            pass
    platform_teardown_accounts(integration_id, removed_identities)

    legacy_success, legacy_message = False, ""
    try:
        from craftos_integrations import disconnect as _legacy_disconnect

        loop = _asyncio.new_event_loop()
        try:
            legacy_success, legacy_message = loop.run_until_complete(
                _legacy_disconnect(integration_id)
            )
        finally:
            loop.close()
    except Exception as e:
        legacy_message = str(e)

    if removed:
        return (
            True,
            f"Disconnected {integration_id}: removed "
            f"{len(removed)} account(s) ({', '.join(removed)}).",
        )
    # Nothing in the integration system — surface the legacy result unchanged (matches the old
    # behavior for "not connected" and for stray legacy-only files).
    return legacy_success, legacy_message


async def with_client(
    integration: str, fn: Callable, *args, **kwargs
) -> Dict[str, Any]:
    """Call ``fn(client, *args, **kwargs)`` after credential check.

    Use when an action needs to do more than a single method call:
    multiple calls in sequence, payload building, etc. ``fn`` may be
    sync or async. Wraps the return as ``{"status": "success", "result": ...}``;
    for bespoke result shapes use ``get_client_or_error`` instead.
    """
    client, err = get_client_or_error(integration)
    if err:
        return err
    try:
        result = fn(client, *args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        try:
            from app.ui_layer.metrics.collector import MetricsCollector

            collector = MetricsCollector.get_instance()
            if collector:
                collector.record_integration_call(integration)
        except Exception:
            pass
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
