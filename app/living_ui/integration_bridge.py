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
from typing import TYPE_CHECKING, Optional

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
        self._http_client = httpx.AsyncClient(timeout=30, follow_redirects=True)

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
            return error_json_response(
                make_error("CONNECTION_TIMEOUT", target="the integration API"), status=504
            )
        except Exception as e:
            logger.error(f"[INTEGRATION_BRIDGE] Proxy error: {e}")
            return error_json_response(
                make_error("PROXY_ERROR", detail=f"Proxy error: {str(e)}"), status=502
            )

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
