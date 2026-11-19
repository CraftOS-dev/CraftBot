"""Host services for the Agent Apps CraftBot launches.

An app's hooks reach CraftBot's language model, its integration actions and
credentialed integration requests through the toolkit's `_craftbot_bridge.js`,
which reads CRAFTBOT_BRIDGE_URL and CRAFTBOT_BRIDGE_TOKEN from the environment
of the process it runs in. Every Agent-App CLI command CraftBot runs that
starts an app (`serve`, `dev`, and `install` or `import` unless `--no-start`)
carries both: the address of this server and a token issued for that app's
folder (see `launch_env`).

Apps keep running after CraftBot exits, so a token outlives the process that
issued it: tokens are kept in the host store and the same folder is always
given the same token. What a token may reach is decided by the app's own
manifest at call time: `capabilities.integrations` for requests and
`capabilities.actions` for actions. The language model answers every app
CraftBot launched.
"""

from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import os
import secrets
from pathlib import Path
from typing import Dict, Optional, Sequence
from urllib.parse import urlparse

import httpx
from aiohttp import web

from app.errors import make_error
from app.errors.web import error_json_response
from app.logger import logger

TOKEN_KIND = "bridge_token"
_LOOPBACK = {"127.0.0.1", "::1"}

# RFC 2606 / 6761 reserved names: values built on these are placeholders by
# definition ("you@example.com" validates and mails nobody).
_PLACEHOLDER_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "example.edu",
    ".example",
    ".test",
    ".invalid",
    "@example.",
)

# Where each integration's credentials may be sent: (base, allowed hosts). A
# path resolves against `base` and cannot escape it; a full URL must be https
# and its host must equal an allowed host or end with "." + one. Omission
# denies.
PROXY_DESTINATIONS: Dict[str, tuple] = {
    "github": ("https://api.github.com", ("api.github.com",)),
    "gmail": ("https://www.googleapis.com", ("googleapis.com",)),
    "google_calendar": ("https://www.googleapis.com", ("googleapis.com",)),
    "google_docs": ("https://docs.googleapis.com", ("googleapis.com",)),
    "google_drive": ("https://www.googleapis.com", ("googleapis.com",)),
    "google_youtube": ("https://www.googleapis.com", ("googleapis.com",)),
    "google_workspace": ("https://www.googleapis.com", ("googleapis.com",)),
    "outlook": ("https://graph.microsoft.com", ("graph.microsoft.com",)),
    "slack": ("https://slack.com", ("slack.com",)),
    "discord": ("https://discord.com", ("discord.com", "discordapp.com")),
    "notion": ("https://api.notion.com", ("api.notion.com",)),
    # PostHog's host lives on the credential (US or EU cloud); the suffix
    # match admits both. PostHog actions resolve their own host.
    "posthog": ("https://us.posthog.com", ("posthog.com",)),
    "hubspot": ("https://api.hubapi.com", ("api.hubapi.com",)),
    "jira": ("https://api.atlassian.com", ("atlassian.net", "api.atlassian.com")),
    "linkedin": ("https://api.linkedin.com", ("api.linkedin.com",)),
    "stripe": ("https://api.stripe.com", ("api.stripe.com",)),
    "line": ("https://api.line.me", ("api.line.me",)),
    "lark": ("https://open.feishu.cn", ("open.feishu.cn", "open.larksuite.com")),
    "lark_calendar": ("https://open.feishu.cn", ("open.feishu.cn", "open.larksuite.com")),
    "lark_drive": ("https://open.feishu.cn", ("open.feishu.cn", "open.larksuite.com")),
    "telegram_bot": ("https://api.telegram.org", ("api.telegram.org",)),
    "telegram_user": ("https://api.telegram.org", ("api.telegram.org",)),
    "twitter": ("https://api.twitter.com", ("api.twitter.com", "api.x.com")),
    "whatsapp_business": ("https://graph.facebook.com", ("graph.facebook.com",)),
}

_url: Optional[str] = None
_store = None


# ---------------------------------------------------------------- tokens


def configure(port: Optional[int]) -> None:
    """Set (or, with None, clear) the address launched apps reach the bridge at."""
    global _url
    _url = f"http://127.0.0.1:{int(port)}" if port else None


def _host_store():
    global _store
    if _store is None:
        from app.agent_app.framework_store import HostStore

        _store = HostStore()
    return _store


def _key(folder: Path) -> str:
    return os.path.normcase(str(folder))


def issue(folder: Path) -> str:
    """The token for an app folder: the one it was given before, else a new one."""
    store = _host_store()
    folder = Path(folder).resolve()
    token = secrets.token_urlsafe(32)
    store.insert(TOKEN_KIND, _key(folder), {"path": str(folder), "tokens": [token]})
    return store.get(TOKEN_KIND, _key(folder))["tokens"][0]


def bind(folder: Path, token: str) -> None:
    """Make `token` (given to a process before its folder was known) name `folder`."""
    store = _host_store()
    folder = Path(folder).resolve()
    if store.insert(TOKEN_KIND, _key(folder), {"path": str(folder), "tokens": [token]}):
        return
    entry = store.get(TOKEN_KIND, _key(folder))
    if token not in entry["tokens"]:
        entry["tokens"].append(token)
        store.put(TOKEN_KIND, _key(folder), entry)


def folder_of(token: str) -> Optional[Path]:
    """The app folder a presented token was issued for, or None."""
    if not token:
        return None
    # Constant-time, as bytes: the value arrives from an HTTP header.
    presented = token.encode("utf-8", "surrogateescape")
    for entry in _host_store().all(TOKEN_KIND):
        for known in entry.get("tokens", []):
            if hmac.compare_digest(presented, known.encode("utf-8", "surrogateescape")):
                return Path(entry["path"])
    return None


def _flag(argv: Sequence[str], name: str) -> Optional[str]:
    if name in argv:
        at = list(argv).index(name) + 1
        if at < len(argv):
            return argv[at]
    return None


def _app_folder(arg: str, home: Path) -> Optional[Path]:
    """An app named by its absolute folder, or by its id in the registry."""
    candidate = Path(arg)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    try:
        registry = json.loads((Path(home) / "registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for app in registry.get("apps", []):
        if isinstance(app, dict) and app.get("id") == arg and isinstance(app.get("path"), str):
            return Path(app["path"])
    return None


def launch_env(argv: Sequence[str], home: Path) -> tuple[dict, Optional[str]]:
    """The bridge environment for an `agent-app` command, and a token still to
    be bound to the folder an install reports when it chose the folder itself.

    Only commands that start an app get it; a command run while no bridge is
    serving (CraftBot without its browser interface) gets nothing.
    """
    if _url is None or not argv:
        return {}, None

    def env(token: str) -> dict:
        return {"CRAFTBOT_BRIDGE_URL": _url, "CRAFTBOT_BRIDGE_TOKEN": token}

    if argv[0] == "install":
        if "--no-start" in argv:
            return {}, None
        into = _flag(argv, "--into")
        if into and Path(into).is_absolute():
            return env(issue(Path(into))), None
        token = secrets.token_urlsafe(32)
        return env(token), token
    if len(argv) >= 2 and argv[1] in {"serve", "dev", "import"}:
        if argv[1] == "import" and "--no-start" in argv:
            return {}, None
        folder = _app_folder(argv[0], home)
        return (env(issue(folder)), None) if folder else ({}, None)
    return {}, None


def bind_installed(stdout: str, token: str) -> None:
    """Bind an install's token to the folder its result reports."""
    docs = []
    try:
        docs.append(json.loads(stdout))
    except ValueError:
        for line in stdout.splitlines():
            try:
                docs.append(json.loads(line))
            except ValueError:
                continue
    for doc in reversed(docs):
        if isinstance(doc, dict) and isinstance(doc.get("dir"), str) and doc["dir"]:
            bind(Path(doc["dir"]), token)
            return


# ---------------------------------------------------------------- grants


def _manifest(folder: Path) -> tuple[Optional[dict], str]:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"manifest unreadable ({error})"
    if not isinstance(manifest, dict):
        return None, "manifest is not an object"
    return manifest, ""


def _granted(folder: Path, kind: str, name: str) -> tuple[bool, str]:
    """Does the app at `folder` declare `name` in `capabilities.<kind>`? Fails closed."""
    manifest, why = _manifest(folder)
    if manifest is None:
        return False, why
    declared = (manifest.get("capabilities") or {}).get(kind)
    if not isinstance(declared, list) or name not in declared:
        return False, f"'{name}' is not declared in the app manifest's capabilities.{kind}"
    return True, ""


def resolve_destination(integration: str, url: str) -> tuple[bool, str]:
    """(ok, resolved url or reason) for where this integration's credentials may go."""
    entry = PROXY_DESTINATIONS.get(integration)
    if not entry:
        return False, "integration has no permitted destinations"
    base, allowed = entry
    raw = (url or "").strip()
    if not raw:
        return False, "empty url"
    # "//host" is protocol-relative, not a path.
    if raw.startswith("/") and not raw.startswith("//"):
        return True, base.rstrip("/") + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False, "unparseable url"
    if parsed.scheme != "https":
        return False, f"scheme {parsed.scheme!r} is not https"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "no host in url"
    if any(host == candidate or host.endswith("." + candidate) for candidate in allowed):
        return True, raw
    return False, f"host {host!r} is not one of {', '.join(allowed)}"


def _dry_run_param_problems(input_schema: dict, params: dict) -> list:
    """Unknown keys against the action's schema, and placeholder values."""
    problems = []
    known = set(input_schema.keys())
    for key in params:
        if known and key not in known:
            problems.append(
                f"unknown param '{key}'; this action's schema has: " + ", ".join(sorted(known))
            )
    for key, value in params.items():
        if isinstance(value, str) and any(m in value.lower() for m in _PLACEHOLDER_DOMAINS):
            problems.append(
                f"param '{key}' looks like a placeholder ({value!r}); reserved example "
                "domains reach nobody. Use a real value, or omit the param if the action resolves it."
            )
    return problems


def _auth_headers(platform_id: str, account: Optional[str]) -> Optional[dict]:
    """Auth headers from the platform's credentialed client, or None."""
    from app.data.action.integrations._helpers import system_for

    system = system_for(platform_id)
    if system is None:
        return None
    try:
        client = system.client_for(platform_id, system.resolve(platform_id, account))
    except Exception:
        return None
    for method in ("_headers", "_bot_headers"):
        if hasattr(client, method):
            try:
                return getattr(client, method)()
            except Exception as error:
                logger.warning(f"[INTEGRATION_BRIDGE] {platform_id} headers failed: {error}")
                return None
    logger.warning(f"[INTEGRATION_BRIDGE] no auth header method for {platform_id}")
    return None


# ---------------------------------------------------------------- routes


class IntegrationBridge:
    """The bridge's HTTP routes on CraftBot's browser server."""

    def __init__(self, port: int):
        configure(port)
        # Redirects are never followed: an allowed host could redirect, and the
        # injected credentials would follow it elsewhere.
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=False)

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/integrations/available", self._handle_available)
        app.router.add_post("/api/integrations/proxy", self._handle_proxy)
        app.router.add_post("/api/integrations/action", self._handle_action)
        app.router.add_post("/api/bridge/llm", self._handle_llm)

    async def cleanup(self) -> None:
        configure(None)
        await self._http.aclose()

    async def _caller(self, request: web.Request) -> Optional[Path]:
        """The app folder behind a request from this machine, or None."""
        if request.remote not in _LOOPBACK:
            return None
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        folder = await asyncio.to_thread(folder_of, auth[7:])
        if folder is None or not await asyncio.to_thread((folder / "manifest.json").is_file):
            return None
        return folder

    @staticmethod
    def _unauthorized() -> web.Response:
        return web.json_response({"error": "Unauthorized"}, status=401)

    @staticmethod
    async def _body(request: web.Request) -> Optional[dict]:
        try:
            data = await request.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    async def _handle_available(self, request: web.Request) -> web.Response:
        """Every integration and whether an account is connected."""
        if await self._caller(request) is None:
            return self._unauthorized()
        from craftos_integrations import get_registered_platforms
        from app.data.action.integrations._helpers import system_for

        def listing() -> list:
            rows = []
            for platform_id in get_registered_platforms():
                system = system_for(platform_id)
                try:
                    connected = bool(system and system.list_accounts(platform_id))
                except Exception:
                    connected = False
                rows.append({"id": platform_id, "connected": connected})
            return rows

        return web.json_response({"integrations": await asyncio.to_thread(listing)})

    async def _handle_proxy(self, request: web.Request) -> web.Response:
        """Forward a request to an integration's API with the user's credentials.

        Body: {"integration", "method", "url", "headers"?, "body"?, "account"?}.
        """
        folder = await self._caller(request)
        if folder is None:
            return self._unauthorized()
        data = await self._body(request)
        if data is None:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        integration = str(data.get("integration") or "")
        method = str(data.get("method") or "GET").upper()
        url = str(data.get("url") or "")
        extra_headers = data.get("headers") or {}
        body = data.get("body")
        account = str(data.get("account") or "").strip() or None
        if not integration or not url:
            return web.json_response({"error": "Missing required fields: integration, url"}, status=400)
        if not isinstance(extra_headers, dict):
            return web.json_response({"error": "headers must be an object"}, status=400)

        granted, why = await asyncio.to_thread(_granted, folder, "integrations", integration)
        if not granted:
            logger.warning(f"[INTEGRATION_BRIDGE] BLOCKED proxy app={folder.name} integration={integration!r}: {why}")
            return web.json_response({"error": f"This app is not permitted to use '{integration}': {why}"}, status=403)
        allowed, resolved = resolve_destination(integration, url)
        if not allowed:
            logger.warning(f"[INTEGRATION_BRIDGE] BLOCKED proxy app={folder.name} integration={integration!r} url={url!r}: {resolved}")
            return web.json_response({"error": f"Destination not permitted for '{integration}': {resolved}"}, status=403)

        # A worker thread: building headers can refresh an OAuth token over HTTP.
        headers = await asyncio.to_thread(_auth_headers, integration, account)
        if headers is None:
            detail = f" (account {account!r} not found?)" if account else ""
            return web.json_response({"error": f"Integration '{integration}' not connected (no credentials){detail}"}, status=424)
        try:
            response = await self._http.request(
                method=method,
                url=resolved,
                headers={**headers, **{str(k): str(v) for k, v in extra_headers.items()}},
                json=body if body and method in ("POST", "PUT", "PATCH") else None,
                params=body if body and method == "GET" else None,
            )
        except httpx.TimeoutException:
            return error_json_response(make_error("CONNECTION_TIMEOUT", target="the integration API"), status=504)
        except Exception as error:
            logger.error(f"[INTEGRATION_BRIDGE] proxy error: {error}")
            return error_json_response(make_error("PROXY_ERROR", detail=f"Proxy error: {error}"), status=502)
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return web.json_response({"status": response.status_code, "data": payload})

    async def _handle_action(self, request: web.Request) -> web.Response:
        """Run one of CraftBot's own integration actions for the app.

        Body: {"action", "params", "confirm_irreversible"?, "dry_run"?}.
        """
        folder = await self._caller(request)
        if folder is None:
            return self._unauthorized()
        data = await self._body(request)
        if data is None:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        name = str(data.get("action") or "")
        params = data.get("params") or {}
        if not name:
            return web.json_response({"error": "Missing required field: action"}, status=400)
        if not isinstance(params, dict):
            return web.json_response({"error": "params must be an object"}, status=400)
        dry_run = bool(data.get("dry_run") or data.get("dryRun"))

        from agent_core.core.action_framework.registry import ActionRegistry

        impl = ActionRegistry().get_action_implementation(name)
        if impl is None:
            return web.json_response({"error": f"Unknown action '{name}'"}, status=404)
        # Only integration actions: an action's action_sets carry its
        # integration id by convention (["gmail_mail", "gmail"] -> gmail).
        sets = set(getattr(impl.metadata, "action_sets", None) or [])
        integration = next((i for i in sorted(PROXY_DESTINATIONS) if i in sets), None)
        if integration is None:
            return web.json_response({"error": f"'{name}' is not an integration action; only integration actions are callable through the bridge"}, status=403)
        granted, why = await asyncio.to_thread(_granted, folder, "actions", name)
        if not granted:
            logger.warning(f"[INTEGRATION_BRIDGE] BLOCKED action app={folder.name} action={name!r}: {why}")
            return web.json_response({"error": f"This app is not permitted to call '{name}': {why}"}, status=403)
        if not dry_run and getattr(impl.metadata, "irreversible", False) and not data.get("confirm_irreversible"):
            logger.warning(f"[INTEGRATION_BRIDGE] REFUSED irreversible action without confirmation app={folder.name} action={name!r}")
            return web.json_response({"error": f"'{name}' is irreversible (it acts on the user's real account). Retry with \"confirm_irreversible\": true."}, status=400)
        if dry_run:
            problems = _dry_run_param_problems(getattr(impl.metadata, "input_schema", None) or {}, params)
            if problems:
                return web.json_response({"error": "Dry-run found problems: " + "; ".join(problems)}, status=400)
            return web.json_response({
                "status": 200,
                "dry_run": True,
                "would_execute": name,
                "integration": integration,
                "note": "Checks passed (grant, params). Nothing was executed.",
            })
        try:
            if inspect.iscoroutinefunction(impl.handler):
                result = await impl.handler(params)
            else:
                result = await asyncio.to_thread(impl.handler, params)
        except Exception as error:
            logger.error(f"[INTEGRATION_BRIDGE] action {name!r} failed: {error}")
            return web.json_response({"error": f"Action failed: {error}"}, status=502)
        return web.json_response({"status": 200, "data": result})

    async def _handle_llm(self, request: web.Request) -> web.Response:
        """A completion from CraftBot's configured language model.

        Body: {"prompt", "system_message"?, "json_mode"?}.
        """
        folder = await self._caller(request)
        if folder is None:
            return self._unauthorized()
        data = await self._body(request)
        if data is None:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            return web.json_response({"error": "Missing required field: prompt"}, status=400)
        system_message = data.get("system_message")
        try:
            from app.internal_action_interface import InternalActionInterface

            result = await InternalActionInterface.use_llm(
                prompt,
                system_message if isinstance(system_message, str) and system_message else None,
                json_mode=data.get("json_mode") is True,
            )
        except Exception as error:
            logger.error(f"[INTEGRATION_BRIDGE] LLM error for app={folder.name}: {error}")
            return web.json_response({"error": f"LLM error: {error}"}, status=502)
        reply = result.get("llm_response", "")
        content = reply.get("content", "") if isinstance(reply, dict) else str(reply)
        return web.json_response({"content": content})
