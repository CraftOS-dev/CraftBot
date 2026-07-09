"""
CraftBot Integration Client — call external APIs through CraftBot.

Living UIs are shareable, so they never store credentials. Instead,
requests go through CraftBot which injects auth headers server-side.

Usage:
    from services.integration_client import integration

    # Check what's available
    integrations = await integration.get_integrations()

    # Make an authenticated API call
    result = await integration.request(
        integration="google_workspace",
        method="GET",
        url="https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
    )
    if result["status"] == 200:
        channels = result["data"]
"""

import os
import httpx
from typing import Any, Dict, List, Optional

BRIDGE_URL = os.environ.get("CRAFTBOT_BRIDGE_URL", "")
BRIDGE_TOKEN = os.environ.get("CRAFTBOT_BRIDGE_TOKEN", "")


class IntegrationClient:
    """Proxy client for calling external APIs through CraftBot."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    @property
    def available(self) -> bool:
        """Whether the CraftBot integration bridge is available."""
        return bool(BRIDGE_URL and BRIDGE_TOKEN)

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {BRIDGE_TOKEN}"}

    async def get_integrations(self) -> List[Dict[str, Any]]:
        """
        List available integrations and their connection status.

        Returns a list like:
        [
            {"id": "google_workspace", "connected": true},
            {"id": "slack", "connected": true},
            {"id": "discord", "connected": false},
        ]
        """
        if not self.available:
            return []
        try:
            client = self._ensure_client()
            r = await client.get(
                f"{BRIDGE_URL}/api/integrations/available",
                headers=self._auth_headers(),
            )
            if r.status_code == 200:
                return r.json().get("integrations", [])
            return []
        except Exception:
            return []

    async def request(
        self,
        integration: str,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Any = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to an external API via CraftBot proxy.

        Args:
            integration: Platform ID (e.g., "google_workspace", "slack", "discord")
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Full URL to the external API endpoint
            headers: Optional extra headers (e.g., custom Accept header)
            body: Optional request body (dict for JSON)

        Returns:
            {"status": 200, "data": {...}} on success
            {"status": 4xx/5xx, "data": "error message"} on failure
            {"error": "..."} if bridge itself fails
        """
        if not self.available:
            return {"error": "Integration bridge not available"}

        try:
            client = self._ensure_client()
            r = await client.post(
                f"{BRIDGE_URL}/api/integrations/proxy",
                headers=self._auth_headers(),
                json={
                    "integration": integration,
                    "method": method,
                    "url": url,
                    "headers": headers or {},
                    "body": body,
                },
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def llm(self, prompt: str, system_message: Optional[str] = None) -> str:
        """
        Ask CraftBot's configured LLM. Returns the response text ('' on
        failure — check `available` first and handle empty results).

        Use for in-app AI features: summarize rows, classify text, extract
        fields, draft content. Keep prompts self-contained (the model has
        no app context beyond what you pass).

            summary = await integration.llm(
                f"Summarize these tasks in 3 bullets:
{tasks_text}"
            )
        """
        if not self.available:
            return ""
        try:
            client = self._ensure_client()
            r = await client.post(
                f"{BRIDGE_URL}/api/bridge/llm",
                headers=self._auth_headers(),
                json={"prompt": prompt, "system_message": system_message},
                timeout=120,
            )
            if r.status_code == 200:
                return r.json().get("content", "")
            return ""
        except Exception:
            return ""

    async def describe_image(self, image_url: str, prompt: Optional[str] = None) -> str:
        """
        Describe an image with CraftBot's vision model. `image_url` may be
        a stored-file URL (/api/files/{id} works served from this app) or
        any http(s) image URL. Returns '' on failure.
        """
        if not self.available:
            return ""
        try:
            client = self._ensure_client()
            payload: Dict[str, Any] = {"image_url": image_url}
            if prompt:
                payload["prompt"] = prompt
            r = await client.post(
                f"{BRIDGE_URL}/api/bridge/vlm",
                headers=self._auth_headers(),
                json=payload,
                timeout=120,
            )
            if r.status_code == 200:
                return r.json().get("content", r.json().get("description", ""))
            return ""
        except Exception:
            return ""

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton — import and use directly
integration = IntegrationClient()
