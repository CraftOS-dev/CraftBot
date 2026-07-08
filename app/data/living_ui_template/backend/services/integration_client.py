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
            {"id": "google_workspace", "connected": true, "granted": true},
            {"id": "slack", "connected": true, "granted": false},
            {"id": "discord", "connected": false, "granted": false},
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

    async def fire_trigger(
        self, trigger: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Fire one of this app's declared triggers at the CraftBot agent.

        Use this from business logic — a threshold crossed, a record created,
        a scheduled check failed — to have CraftBot act on it. The trigger
        must be declared in config/triggers.json; `params` are validated
        against its declared param spec.

        Returns:
            {"status": "ok", "routed": ...} on success
            {"error": "..."} when rejected (undeclared trigger, bad params,
            cooldown) or when no CraftBot host is available.
        """
        if not self.available:
            return {"error": "Integration bridge not available"}
        try:
            client = self._ensure_client()
            r = await client.post(
                f"{BRIDGE_URL}/api/bridge/trigger",
                headers=self._auth_headers(),
                json={"trigger": trigger, "params": params or {}},
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton — import and use directly
integration = IntegrationClient()
