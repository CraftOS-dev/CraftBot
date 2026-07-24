"""Headless-browser probe of a running Living UI (walk-verify's hands)."""

from agent_core import action


@action(
    name="browser_probe",
    description=(
        "Drive a RUNNING Living UI in a headless browser (invisible — no "
        "window). Executes a scripted sequence of steps and returns per-step "
        "results, page text, screenshot file paths, and console errors. Use "
        "this to verify UI flows a user would perform: navigate, click "
        "buttons, fill forms, read what rendered."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
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
    import asyncio
    import json
    from pathlib import Path

    if input_data.get("simulated_mode", False):
        return {"status": "success", "steps": [{"op": "goto", "ok": True, "detail": "/"}], "console_errors": []}

    url = (input_data.get("url") or "").strip()
    steps = input_data.get("steps") or []
    if not url or not isinstance(steps, list) or not steps:
        return {"status": "error", "message": "url and a non-empty steps array are required"}

    from app.config import PROJECT_ROOT

    cli = Path(PROJECT_ROOT) / "living-ui-v2" / "tools" / "src" / "cli.ts"
    out_dir = str(Path(input_data.get("project_path") or "/tmp") / "logs" / "verify")
    proc = await asyncio.create_subprocess_exec(
        "node", str(cli), "probe", "--url", url, "--steps", json.dumps(steps), "--out", out_dir,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        return {"status": "error", "message": "browser probe timed out after 180s"}

    text = out.decode(errors="replace").strip()
    try:
        payload = json.loads(text.splitlines()[-1])
    except Exception:
        return {"status": "error", "message": f"probe output unparseable: {text[-500:]}"}
    if "error" in payload:
        return {"status": "error", "message": str(payload["error"])}
    return {
        "status": "success",
        "steps": payload.get("steps", []),
        "console_errors": payload.get("consoleErrors", []),
    }
