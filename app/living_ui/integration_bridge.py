# -*- coding: utf-8 -*-
"""
Integration Bridge — proxy for Living UI ↔ External API calls.

Living UI backends call CraftBot via this bridge to make authenticated
requests to external APIs (YouTube, Discord, Slack, etc.). Credentials
never leave CraftBot — the bridge injects auth headers server-side.

Routes are registered on the browser adapter's aiohttp app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from aiohttp import web
import httpx

from app.errors import make_error
from app.errors.web import error_json_response

if TYPE_CHECKING:
    from app.living_ui.manager import LivingUIManager

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)


# RFC 2606 / 6761 reserved names: values built on these are placeholders by
# definition — "you@example.com" compiles, validates, and mails nobody. A
# standards-based check, not a per-integration rule.
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


def _dry_run_param_problems(input_schema: dict, params: dict) -> list:
    """Pure param validation for dry-run: unknown keys against the action's
    schema, and placeholder values that would 'succeed' into a void."""
    problems = []
    known = set(input_schema.keys())
    for key in params.keys():
        if known and key not in known:
            problems.append(
                f"unknown param '{key}' — this action's schema has: "
                + ", ".join(sorted(known))
            )
    for key, value in params.items():
        if isinstance(value, str):
            lowered = value.lower()
            if any(marker in lowered for marker in _PLACEHOLDER_DOMAINS):
                problems.append(
                    f"param '{key}' looks like a PLACEHOLDER ({value!r}) — "
                    "RFC-reserved example domains reach nobody. Use a real "
                    "value, or omit the param if the action resolves it "
                    "(send_gmail with no 'to' goes to the account owner)."
                )
    return problems


class IntegrationBridge:
    """
    HTTP proxy that lets Living UI backends make authenticated API calls
    to external services through CraftBot.

    Flow:
        Living UI Backend → POST /api/integrations/proxy → CraftBot
        CraftBot validates token, injects auth, forwards to external API.
    """

    def __init__(self, manager: "LivingUIManager"):
        self._manager = manager
        # follow_redirects is OFF for the proxy: an allowed host could 302 to an
        # attacker-controlled host and the injected credentials would follow it.
        self._http_client = httpx.AsyncClient(timeout=30, follow_redirects=False)

    def register_routes(self, app: web.Application) -> None:
        """Register integration bridge routes on the aiohttp app."""
        app.router.add_get("/api/integrations/available", self._handle_available)
        app.router.add_post("/api/integrations/proxy", self._handle_proxy)
        app.router.add_post("/api/integrations/action", self._handle_action)
        app.router.add_post("/api/bridge/llm", self._handle_llm)
        app.router.add_post("/api/bridge/vlm", self._handle_vlm)
        app.router.add_post("/api/bridge/agent_request", self._handle_agent_request)
        logger.info("[INTEGRATION_BRIDGE] Routes registered")

    async def cleanup(self) -> None:
        """Close the HTTP client."""
        await self._http_client.aclose()

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    async def _handle_available(self, request: web.Request) -> web.Response:
        """List available integrations and their connection/grant status."""
        project_id = self._validate_token(request)
        if not project_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        from craftos_integrations import get_registered_platforms
        from app.data.action.integrations._helpers import system_for

        integrations = []
        for platform_id in get_registered_platforms():
            system = system_for(platform_id)
            try:
                connected = bool(system and system.list_accounts(platform_id))
            except Exception:
                connected = False
            integrations.append(
                {
                    "id": platform_id,
                    "connected": connected,
                }
            )

        return web.json_response({"integrations": integrations})

    async def _handle_proxy(self, request: web.Request) -> web.Response:
        """
        Proxy an API request to an external service with injected auth.

        Expected JSON body:
        {
            "integration": "google_workspace",
            "method": "GET",
            "url": "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
            "headers": {},       // optional extra headers
            "body": null         // optional request body
        }
        """
        project_id = self._validate_token(request)
        if not project_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        integration = data.get("integration", "")
        method = data.get("method", "GET").upper()
        url = data.get("url", "")
        extra_headers = data.get("headers") or {}
        body = data.get("body")
        # Optional multi-account selector: identity, alias, or unique
        # fragment (same resolution as agent actions). Omitted = primary.
        account = (data.get("account") or "").strip() or None

        if not integration or not url:
            return web.json_response(
                {"error": "Missing required fields: integration, url"}, status=400
            )

        # Gate 1 — capability. An app may only use integrations its manifest
        # declares. Without this, any app that can reach the bridge can use
        # every credential the user has connected: a kanban board could send
        # mail as them. The declaration is the hook the Phase 5 consent flow
        # attaches to; until then it is at least an explicit, reviewable list.
        granted, why = self._project_grants(project_id, integration)
        if not granted:
            logger.warning(
                f"[INTEGRATION_BRIDGE] BLOCKED (capability) project={project_id} "
                f"integration={integration!r}: {why}"
            )
            return web.json_response(
                {"error": f"This app is not permitted to use '{integration}': {why}"},
                status=403,
            )

        # Gate 2 — destination. Without it this endpoint is a credential
        # exfiltration primitive: `url` is caller-controlled and the user's real
        # OAuth token is injected into whatever host is named, so one line in a
        # third-party app's pb_hooks could ship a Gmail token anywhere. Fails
        # CLOSED — an integration with no entry cannot be proxied at all.
        allowed, resolved = self._resolve_destination(integration, url)
        if not allowed:
            logger.warning(
                f"[INTEGRATION_BRIDGE] BLOCKED proxy from project={project_id} "
                f"integration={integration!r} url={url!r}: {resolved}"
            )
            return web.json_response(
                {"error": f"Destination not permitted for '{integration}': {resolved}"},
                status=403,
            )
        url = resolved

        # Get auth headers from platform client
        auth_headers = self._get_auth_headers(integration, account)
        if auth_headers is None:
            detail = f" (account {account!r} not found?)" if account else ""
            return web.json_response(
                {
                    "error": (
                        f"Integration '{integration}' not connected "
                        f"(no credentials){detail}"
                    )
                },
                status=424,
            )

        # Merge headers: auth + extra (extra can override Content-Type etc.)
        merged_headers = {**auth_headers, **extra_headers}

        # Forward request to external API
        try:
            response = await self._http_client.request(
                method=method,
                url=url,
                headers=merged_headers,
                json=body if body and method in ("POST", "PUT", "PATCH") else None,
                params=body if body and method == "GET" else None,
            )

            # Return proxied response
            try:
                response_body = response.json()
            except Exception:
                response_body = response.text

            return web.json_response(
                {
                    "status": response.status_code,
                    "data": response_body,
                },
                status=200,
            )

        except httpx.TimeoutException:
            return error_json_response(
                make_error("CONNECTION_TIMEOUT", target="the integration API"),
                status=504,
            )
        except Exception as e:
            logger.error(f"[INTEGRATION_BRIDGE] Proxy error: {e}")
            return error_json_response(
                make_error("PROXY_ERROR", detail=f"Proxy error: {str(e)}"), status=502
            )

    async def _handle_action(self, request: web.Request) -> web.Response:  # noqa: C901
        """Execute one of CRAFTBOT'S OWN integration actions for a Living UI.

        The raw proxy below makes apps speak each provider's native API —
        which made an agent hand-roll Gmail MIME envelopes and, when its
        invented endpoint 404'd, conclude the bridge was broken. CraftBot
        already owns tested implementations of every integration operation
        (send_gmail, send_slack_message, …): this endpoint exposes THEM, so
        apps pass semantic params ({to, subject, body}) and provider-API
        knowledge stays in one place.

        Body: {"action": "send_gmail", "params": {...},
               "confirm_irreversible": true?}
        Grants: the gate derives capabilities.actions from callAction
        literals in the app's hooks — same derive-from-code flow as
        external_hosts/integrations. Only actions tied to a known
        integration are callable; irreversible ones need the explicit flag.
        """
        project_id = self._validate_token(request)
        if not project_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        name = str(data.get("action") or "")
        params = data.get("params") or {}
        if not name:
            return web.json_response(
                {"error": "Missing required field: action"}, status=400
            )
        if not isinstance(params, dict):
            return web.json_response({"error": "params must be an object"}, status=400)

        dry_run = bool(data.get("dry_run") or data.get("dryRun"))

        from agent_core.core.action_framework.registry import ActionRegistry

        impl = ActionRegistry().get_action_implementation(name)
        if impl is None:
            logger.warning(
                f"[INTEGRATION_BRIDGE] REFUSED (unknown action) project={project_id} action={name!r}"
            )
            return web.json_response({"error": f"Unknown action '{name}'"}, status=404)

        # Only INTEGRATION actions are exposed: the action's action_sets carry
        # its integration id by convention (["gmail_mail", "gmail"] → gmail).
        sets = set(getattr(impl.metadata, "action_sets", None) or [])
        integration = next(
            (i for i in sorted(self.PROXY_DESTINATIONS) if i in sets), None
        )
        if integration is None:
            logger.warning(
                f"[INTEGRATION_BRIDGE] REFUSED (not an integration action) "
                f"project={project_id} action={name!r}"
            )
            return web.json_response(
                {
                    "error": f"'{name}' is not an integration action — only integration "
                    "actions are callable through the bridge"
                },
                status=403,
            )

        granted, why = self._project_action_grants(project_id, name)
        if not granted:
            logger.warning(
                f"[INTEGRATION_BRIDGE] BLOCKED (action) project={project_id} "
                f"action={name!r}: {why}"
            )
            return web.json_response(
                {"error": f"This app is not permitted to call '{name}': {why}"},
                status=403,
            )

        if getattr(impl.metadata, "irreversible", False) and not data.get(
            "confirm_irreversible"
        ):
            # A refused send with no server-side log line is how an app once
            # shipped a cron that logged "sent" while nothing ever left.
            logger.warning(
                f"[INTEGRATION_BRIDGE] REFUSED (irreversible, no confirm) "
                f"project={project_id} action={name!r}"
            )
            return web.json_response(
                {
                    "error": f"'{name}' is irreversible (it acts on the user's real "
                    'account). Retry with "confirm_irreversible": true.'
                },
                status=400,
            )

        if dry_run:
            # Everything above ran: token, action exists, integration mapped,
            # grant present, irreversible confirmed. Now validate params
            # WITHOUT executing, so build-time verification can exercise
            # paths that must never fire for real (emails, posts, deletes).
            problems = _dry_run_param_problems(
                getattr(impl.metadata, "input_schema", None) or {}, params
            )
            if problems:
                logger.warning(
                    f"[INTEGRATION_BRIDGE] DRY-RUN found problems "
                    f"project={project_id} action={name!r}: {problems}"
                )
                return web.json_response(
                    {"error": "Dry-run found problems: " + "; ".join(problems)},
                    status=400,
                )
            return web.json_response(
                {
                    "status": 200,
                    "dry_run": True,
                    "would_execute": name,
                    "integration": integration,
                    "note": "All checks passed (grant, params, confirmation). "
                    "Nothing was executed.",
                },
                status=200,
            )

        try:
            import asyncio as _asyncio
            import inspect as _inspect

            if _inspect.iscoroutinefunction(impl.handler):
                result = await impl.handler(params)
            else:
                result = await _asyncio.to_thread(impl.handler, params)
            return web.json_response({"status": 200, "data": result}, status=200)
        except Exception as e:
            logger.error(f"[INTEGRATION_BRIDGE] action '{name}' failed: {e}")
            return web.json_response({"error": f"Action failed: {str(e)}"}, status=502)

    def _project_action_grants(self, project_id: str, action_name: str) -> tuple:
        """(ok, reason) — is `action_name` in the manifest's derived
        capabilities.actions? Fails closed, mirror of _project_grants."""
        import json as _json

        try:
            project = self._manager.get_project(project_id)
        except Exception as e:
            return False, f"unknown project ({e})"
        if project is None:
            return False, "unknown project"
        try:
            manifest_path = Path(project.path) / "manifest.json"
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"manifest unreadable ({e})"

        declared = (manifest.get("capabilities") or {}).get("actions")
        if not isinstance(declared, list) or action_name not in declared:
            return False, (
                f"'{action_name}' is not in capabilities.actions. The gate derives "
                "the list from callAction literals in your hooks — call "
                f"bridge.callAction('{action_name}', {{…}}) with a literal name and "
                "relaunch with living_ui_notify_ready."
            )
        return True, ""

    async def _handle_agent_request(self, request: web.Request) -> web.Response:
        """A Living UI's nudge hook reports a new agent_requests row (spec
        TRIGGERS-PLAN). The payload carries ONLY {request_id, trigger} — the
        instruction the agent will execute is read from the project's
        triggers.json on disk by the manager, so nothing app-controlled can
        steer the agent beyond what its author declared at build time.

        Gate order: token → capability → consent → era. Every refusal fails
        closed and leaves the queue row pending (harmless, inspectable)."""
        project_id = self._validate_token(request)
        if not project_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        trigger = str(data.get("trigger") or "").strip()
        request_id = str(data.get("request_id") or "").strip()
        if not trigger or not request_id:
            return web.json_response(
                {"error": "Missing required fields: trigger, request_id"}, status=400
            )

        # Gate 2 — capability. Mirror of the integrations gate: an app may
        # only fire triggers its manifest declares. The gate derives
        # capabilities.triggers from triggers.json, so an undeclared name
        # cannot acquire the capability by being sent.
        granted, why = self._project_trigger_grants(project_id, trigger)
        if not granted:
            logger.warning(
                f"[INTEGRATION_BRIDGE] BLOCKED (capability) project={project_id} "
                f"trigger={trigger!r}: {why}"
            )
            return web.json_response(
                {"error": f"This app may not fire '{trigger}': {why}"}, status=403
            )

        # Gate 3 — consent. First-party builds are approved at creation;
        # marketplace/imported apps need the user's explicit yes.
        try:
            from app.factory.host_craftbot import get_factory_host

            host = get_factory_host()
            if not host.is_triggers_approved(project_id):
                logger.warning(
                    f"[INTEGRATION_BRIDGE] BLOCKED (consent) project={project_id} "
                    f"trigger={trigger!r}"
                )
                # A silent refusal reads as a broken button (observed live
                # 2026-08-06: three consent-blocks, user saw nothing). Ask
                # the user via the project session — at most once an hour,
                # never letting the ask fail the refusal response, and never
                # consuming the hourly slot on a FAILED ask (a silent
                # failure once suppressed every retry for an hour).
                try:
                    if host.consent_nudge_due(project_id):
                        ask = await self._manager.notify_trigger_consent_needed(
                            project_id, trigger
                        )
                        if ask.get("status") == "success":
                            host.mark_consent_nudged(project_id)
                        else:
                            logger.warning(
                                f"[INTEGRATION_BRIDGE] consent ask failed for "
                                f"{project_id}: {ask.get('message')}"
                            )
                except Exception as e:
                    logger.warning(f"[INTEGRATION_BRIDGE] consent ask failed: {e}")
                return web.json_response(
                    {
                        "error": (
                            "The user has not approved this app's agent triggers. "
                            "Ask them to approve via living_ui_approve_triggers."
                        )
                    },
                    status=403,
                )

            # Gate 4 — era. While a DEV environment exists, fires are
            # agent/verifier test traffic (the walk verifier clicks ⚡
            # buttons in the dev instance, which aliases to the real project
            # id through the shared bridge token) — they must not start real
            # agent runs; the dev copy and its rows die at promote anyway.
            # With no dev env there is nothing mid-change that could fire
            # falsely: during a first build the live app does not run yet,
            # and after a promote fires are legitimate operation. NOT keyed
            # on the factory machine: machine_for lazily creates a BUILDING
            # machine for any project, so a marketplace install (which never
            # builds here) would read as mid-arc forever.
            dev_env = host.get_staging_record(project_id)
            if dev_env:
                logger.info(
                    f"[INTEGRATION_BRIDGE] trigger fire deferred (era) "
                    f"project={project_id} trigger={trigger!r} "
                    f"dev_env=True"
                )
                return web.json_response(
                    {
                        "status": "deferred",
                        "message": (
                            "A build/modify is in progress — fires do not start "
                            "agent runs until the app is delivered and live."
                        ),
                    }
                )
        except Exception as e:
            # Fail closed: if the gates cannot be evaluated, no agent run.
            logger.warning(f"[INTEGRATION_BRIDGE] trigger gates unavailable: {e}")
            return web.json_response({"error": "Trigger gates unavailable"}, status=503)

        result = await self._manager.notify_app_trigger(project_id, trigger, request_id)
        if result.get("status") != "success":
            return web.json_response(
                {"error": result.get("message", "dispatch failed")}, status=422
            )
        return web.json_response({"status": "ok"})

    def _project_trigger_grants(self, project_id: str, trigger: str) -> tuple:
        """(ok, reason) — does this project declare `trigger` in its
        manifest's `capabilities.triggers`? Fails closed, mirror of
        _project_grants."""
        import json as _json

        try:
            project = self._manager.get_project(project_id)
        except Exception as e:
            return False, f"unknown project ({e})"
        if project is None:
            return False, "unknown project"
        try:
            manifest_path = Path(project.path) / "manifest.json"
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"manifest unreadable ({e})"

        declared = (manifest.get("capabilities") or {}).get("triggers")
        if not isinstance(declared, list) or trigger not in declared:
            return False, (
                f"'{trigger}' is not in capabilities.triggers. The gate derives "
                "the list from triggers.json — declare the trigger there and "
                "relaunch with living_ui_notify_ready."
            )
        return True, ""

    async def _handle_llm(self, request: web.Request) -> web.Response:
        """Proxy LLM completion request through CraftBot's configured LLM."""
        project_id = self._validate_token(request)
        if not project_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        prompt = data.get("prompt", "")
        system_message = data.get("system_message")

        if not prompt:
            return web.json_response(
                {"error": "Missing required field: prompt"}, status=400
            )

        try:
            import app.internal_action_interface as iai

            result = await iai.InternalActionInterface.use_llm(prompt, system_message)
            llm_response = result.get("llm_response", "")
            if isinstance(llm_response, dict):
                response_text = llm_response.get("content", "")
            else:
                response_text = str(llm_response)
            return web.json_response({"content": response_text})
        except Exception as e:
            logger.error(f"[INTEGRATION_BRIDGE] LLM error: {e}")
            return web.json_response({"error": f"LLM error: {str(e)}"}, status=502)

    async def _handle_vlm(self, request: web.Request) -> web.Response:
        """Proxy VLM image description through CraftBot's configured VLM."""
        project_id = self._validate_token(request)
        if not project_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        image_url = data.get("image_url", "")
        prompt = data.get("prompt", "Describe this image.")

        if not image_url:
            return web.json_response(
                {"error": "Missing required field: image_url"}, status=400
            )

        try:
            # Download image to temp file
            import tempfile
            import os

            response = await self._http_client.get(image_url)
            if response.status_code != 200:
                return web.json_response(
                    {"error": f"Failed to download image: HTTP {response.status_code}"},
                    status=424,
                )

            # Save to temp file for VLM
            suffix = ".jpg"
            if "png" in response.headers.get("content-type", ""):
                suffix = ".png"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(response.content)
            tmp.close()

            try:
                import app.internal_action_interface as iai

                description = iai.InternalActionInterface.describe_image(
                    tmp.name, prompt
                )
                return web.json_response({"description": description})
            finally:
                os.unlink(tmp.name)
        except Exception as e:
            logger.error(f"[INTEGRATION_BRIDGE] VLM error: {e}")
            return web.json_response({"error": f"VLM error: {str(e)}"}, status=502)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_token(self, request: web.Request) -> Optional[str]:
        """
        Validate the bridge token from the Authorization header.

        Returns:
            project_id if valid, None if invalid.
        """
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None

        token = auth[7:]
        return self._manager.validate_bridge_token(token)

    # Where each integration's credentials may be sent: (base, allowed hosts).
    #
    # `base` also REPAIRS the proxy. Callers pass a path — the shipped apps do
    # `callIntegration('gmail','POST','/gmail/v1/users/me/messages/send',…)` —
    # and nothing ever resolved it, so httpx got a relative URL and every call
    # failed. crm-system even carries a "Gmail integration unavailable" fallback
    # because of it. Resolving against `base` fixes that, and a path can never
    # escape the base, so it is also the safe form.
    #
    # Host matching is exact-or-dot-suffix, so "api.github.com.evil.com" does
    # not pass as "api.github.com". Omission denies — the safe direction.
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
        "hubspot": ("https://api.hubapi.com", ("api.hubapi.com",)),
        "jira": ("https://api.atlassian.com", ("atlassian.net", "api.atlassian.com")),
        "linkedin": ("https://api.linkedin.com", ("api.linkedin.com",)),
        "stripe": ("https://api.stripe.com", ("api.stripe.com",)),
        "line": ("https://api.line.me", ("api.line.me",)),
        "lark": ("https://open.feishu.cn", ("open.feishu.cn", "open.larksuite.com")),
        "lark_calendar": (
            "https://open.feishu.cn",
            ("open.feishu.cn", "open.larksuite.com"),
        ),
        "lark_drive": (
            "https://open.feishu.cn",
            ("open.feishu.cn", "open.larksuite.com"),
        ),
        "telegram_bot": ("https://api.telegram.org", ("api.telegram.org",)),
        "telegram_user": ("https://api.telegram.org", ("api.telegram.org",)),
        "twitter": ("https://api.twitter.com", ("api.twitter.com", "api.x.com")),
        "whatsapp_business": ("https://graph.facebook.com", ("graph.facebook.com",)),
    }

    def _project_grants(self, project_id: str, integration: str) -> tuple:
        """(ok, reason) — does this project declare `integration` in its
        manifest's `capabilities.integrations`? Fails closed."""
        import json as _json

        try:
            project = self._manager.get_project(project_id)
        except Exception as e:
            return False, f"unknown project ({e})"
        if project is None:
            return False, "unknown project"

        try:
            manifest_path = Path(project.path) / "manifest.json"
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"manifest unreadable ({e})"

        capabilities = manifest.get("capabilities") or {}
        declared = capabilities.get("integrations")
        # The grant is DERIVED, not hand-written: the validation gate scans
        # the hooks for callIntegration('<id>' literals and writes the list
        # into the (system-managed) manifest. So the fix for a missing grant
        # is always the same: make the call in code, re-run the gate.
        if not isinstance(declared, list):
            return False, (
                f"'{integration}' is not granted: the manifest has no "
                "capabilities.integrations. The gate derives it from your "
                f"hooks — call bridge.callIntegration('{integration}', …) with "
                "a literal id and relaunch with living_ui_notify_ready."
            )
        if integration not in declared:
            return False, (
                f"'{integration}' is not in capabilities.integrations "
                f"{declared}. The gate derives the list from callIntegration "
                "literals in your hooks — use a literal id and relaunch with "
                "living_ui_notify_ready."
            )
        return True, ""

    def _resolve_destination(self, integration: str, url: str) -> tuple:
        """(ok, resolved_url_or_reason) for this integration's credentials."""
        from urllib.parse import urlparse

        entry = self.PROXY_DESTINATIONS.get(integration)
        if not entry:
            return False, "integration has no permitted destinations"
        base, allowed = entry

        raw = (url or "").strip()
        if not raw:
            return False, "empty url"

        # A path resolves against the base and cannot escape it. Note "//host"
        # is protocol-relative, NOT a path — urljoin would happily send it to
        # another host, so it must be rejected here.
        if raw.startswith("/") and not raw.startswith("//"):
            return True, base.rstrip("/") + raw

        try:
            parsed = urlparse(raw)
        except Exception:
            return False, "unparseable url"

        if parsed.scheme != "https":
            return False, f"scheme {parsed.scheme!r} is not https"

        host = (parsed.hostname or "").lower()
        if not host:
            return False, "no host in url"

        for candidate in allowed:
            if host == candidate or host.endswith("." + candidate):
                return True, raw
        return False, f"host {host!r} is not one of {', '.join(allowed)}"

    def _client_for_platform(self, platform_id: str, account: Optional[str] = None):
        """Credentialed client for a platform, or None.

        Multi-account provider ids resolve ``account`` (identity / alias /
        unique fragment, None = primary) through the IntegrationSystem —
        the bound client subclasses the legacy client, so the
        header-extraction below works unchanged. Platforms without a v2
        provider keep the legacy single-account client.
        """
        from app.data.action.integrations._helpers import system_for

        system = system_for(platform_id)
        if system is not None:
            try:
                identity = system.resolve(platform_id, account)
                return system.client_for(platform_id, identity)
            except Exception:
                # Not connected / bad account hint (AccountResolutionError)
                # or build failure.
                return None
        return None

    def _get_auth_headers(
        self, platform_id: str, account: Optional[str] = None
    ) -> Optional[dict]:
        """
        Get authentication headers from a platform client.

        Returns:
            Dict of auth headers, or None if credentials unavailable.
        """
        client = self._client_for_platform(platform_id, account)
        if client is None:
            return None

        # Most clients expose _headers() — use it
        if hasattr(client, "_headers"):
            try:
                headers = client._headers()
                if callable(headers):
                    headers = headers()
                return headers
            except Exception as e:
                logger.warning(
                    f"[INTEGRATION_BRIDGE] Failed to get headers for {platform_id}: {e}"
                )
                return None

        # Discord uses _bot_headers()
        if hasattr(client, "_bot_headers"):
            try:
                return client._bot_headers()
            except Exception as e:
                logger.warning(
                    f"[INTEGRATION_BRIDGE] Failed to get bot headers for {platform_id}: {e}"
                )
                return None

        logger.warning(
            f"[INTEGRATION_BRIDGE] No auth header method found for {platform_id}"
        )
        return None
