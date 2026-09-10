"""Headless-browser probe of a running Agent App (walk-verify's hands)."""

from agent_core import action


@action(
    name="browser_probe",
    description=(
        "Drive a RUNNING Agent App in a headless browser (invisible — no "
        "window). Executes a scripted sequence of steps and returns per-step "
        "results, page text, screenshot file paths, and console errors. Use "
        "this to verify UI flows a user would perform: navigate, click "
        "buttons, fill forms, read what rendered."
    ),
    default=False,
    mode="CLI",
    action_sets=["agent_app"],
    parallelizable=False,
    input_schema={
        "url": {
            "type": "string",
            "example": "http://127.0.0.1:3100",
            "description": "Base URL of the running app.",
        },
        "steps": {
            "type": "array",
            "example": [
                {"op": "goto", "value": "/"},
                {"op": "click", "selector": "button:has-text('Add')"},
                {"op": "type", "selector": "input", "value": "hello"},
                {"op": "read", "selector": "main"},
                {"op": "screenshot", "value": "after-add"},
            ],
            "description": (
                "Ordered steps (max 40). op: goto|click|type|read|wait|screenshot. "
                "selector: CSS/Playwright selector. value: path for goto, text "
                "for type, ms for wait, filename for screenshot. read with no "
                "selector returns the whole page text."
            ),
        },
        "project_path": {
            "type": "string",
            "description": "Project dir — screenshots are saved under its logs/verify/.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "steps": {"type": "array", "description": "Per-step {op, ok, detail} results."},
        "console_errors": {"type": "array", "description": "Console/page errors seen."},
    },
    test_payload={
        "url": "http://127.0.0.1:3100",
        "steps": [{"op": "goto", "value": "/"}],
        "simulated_mode": True,
    },
)
async def browser_probe(input_data: dict) -> dict:
    from pathlib import Path

    if input_data.get("simulated_mode", False):
        return {
            "status": "success",
            "steps": [{"op": "goto", "ok": True, "detail": "/"}],
            "console_errors": [],
        }

    url = (input_data.get("url") or "").strip()
    steps = input_data.get("steps") or []
    if not url or not isinstance(steps, list) or not steps:
        return {
            "status": "error",
            "message": "url and a non-empty steps array are required",
        }

    from app.agent_app.probe_pool import ProbeUnavailable, get_probe_pool

    out_dir = str(Path(input_data.get("project_path") or "/tmp") / "logs" / "verify")
    pool = get_probe_pool()
    try:
        result = await pool.probe(url, steps, out_dir)
    except ProbeUnavailable as e:
        return {
            "status": "error",
            "message": (
                f"No browser can run on this machine ({e}) — UI probing is "
                "unavailable; rely on the server-side evidence instead."
            ),
        }
    except (RuntimeError, ValueError) as e:
        return {"status": "error", "message": f"browser probe failed: {e}"}

    # The probe RAN against this port — record it on the shadow whose
    # environment it exercised, so the walk action's probe-first mandate
    # has a structural fact to check (port equality, nothing inferred).
    try:
        from urllib.parse import urlsplit

        from app.agent_app import get_agent_app_manager
        from app.factory.host_craftbot import get_factory_host

        probed_port = urlsplit(url).port
        mgr = get_agent_app_manager()
        host = get_factory_host()
        if mgr is not None and probed_port is not None:
            for _pid in list(getattr(mgr, "projects", {})):
                record = host.get_staging_record(_pid)
                if record and int(record.get("port") or 0) == int(probed_port):
                    import time as _time

                    record["probed_at"] = _time.time()
                    host.set_staging_record(_pid, record)
                    break
    except Exception:
        pass  # bookkeeping must never fail a successful probe

    return {
        "status": "success",
        "steps": result.get("steps", []),
        "console_errors": result.get("consoleErrors", []),
    }
