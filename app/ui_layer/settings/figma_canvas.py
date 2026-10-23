"""Allowlisted, account-bound canvas setup for browser Settings."""

from __future__ import annotations

from craftos_integrations.providers.figma.canvas_bridge import PLUGIN_URL, PORT
from craftos_integrations.contracts import AccountResolutionError

OPERATIONS = {
    "start": "start_figma_canvas",
    "connect": "connect_figma_canvas",
    "status": "get_figma_canvas_status",
    "stop": "stop_figma_canvas",
}


async def control_canvas(system, data):
    request_id = data.get("request_id")
    account = data.get("account")
    response = {
        "request_id": request_id,
        "account": account,
        "plugin_url": PLUGIN_URL,
        "port": PORT,
    }
    try:
        operation = OPERATIONS.get(data.get("action"))
        if operation is None:
            raise ValueError("Choose start, connect, status or stop.")
        if system is None:
            raise ValueError("Connect a Figma account before setting up the canvas.")
        if not isinstance(account, str) or not account:
            raise ValueError("Select a connected Figma account.")
        client = system.client_for("figma", system.resolve("figma", account))
        if data["action"] == "connect":
            outcome = await client.connect_canvas(data.get("channel", ""))
        else:
            outcome = await {
                "start": client.start_canvas,
                "status": client.canvas_status,
                "stop": client.stop_canvas,
            }[data["action"]]()
        if not outcome.get("ok"):
            return {
                **response,
                "success": False,
                "error": outcome.get("error", "Canvas setup failed."),
            }
        status = await client.canvas_status()
        state = status.get("result", {})
        if data["action"] == "connect":
            state["page_name"] = outcome["result"]["document"]["currentPage"].get(
                "name", ""
            )
        return {**response, "success": True, **state}
    except (ValueError, LookupError, TypeError, AccountResolutionError) as exc:
        return {**response, "success": False, "error": str(exc)}
