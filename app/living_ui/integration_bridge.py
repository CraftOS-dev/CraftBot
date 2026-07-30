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

if TYPE_CHECKING:
    from app.living_ui.manager import LivingUIManager

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)


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
        app.router.add_post("/api/bridge/llm", self._handle_llm)
        app.router.add_post("/api/bridge/vlm", self._handle_vlm)
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

        from craftos_integrations import get_registered_platforms, get_client

        integrations = []
        for platform_id in get_registered_platforms():
            client = get_client(platform_id)
            connected = client.has_credentials() if client else False
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
        auth_headers = self._get_auth_headers(integration)
        if auth_headers is None:
            return web.json_response(
                {
                    "error": f"Integration '{integration}' not connected (no credentials)"
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
            return web.json_response({"error": "External API timeout"}, status=504)
        except Exception as e:
            logger.error(f"[INTEGRATION_BRIDGE] Proxy error: {e}")
            return web.json_response({"error": f"Proxy error: {str(e)}"}, status=502)

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
        "lark_calendar": ("https://open.feishu.cn", ("open.feishu.cn", "open.larksuite.com")),
        "lark_drive": ("https://open.feishu.cn", ("open.feishu.cn", "open.larksuite.com")),
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
        if not isinstance(declared, list):
            return False, (
                "manifest declares no capabilities.integrations — add "
                f'"capabilities": {{"integrations": ["{integration}"]}} to grant it'
            )
        if integration not in declared:
            return False, f"not in capabilities.integrations {declared}"
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

    def _get_auth_headers(self, platform_id: str) -> Optional[dict]:
        """
        Get authentication headers from a platform client.

        Returns:
            Dict of auth headers, or None if credentials unavailable.
        """
        from craftos_integrations import get_client

        client = get_client(platform_id)
        if not client or not client.has_credentials():
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
