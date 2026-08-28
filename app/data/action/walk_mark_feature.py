"""walk_mark_feature — the verifier's coverage boundary marker.

Records "the walker is now exercising feature X" on the DEV app's coverage
timeline (POST /api/_coverage/mark). The instrumented dev build pushes
function-hit deltas to the same timeline; folding the two after the walk
yields feature → executed functions, the evidence a later verify uses to
decide which features a diff can reach (docs/design/scoped-walk-verify.md).

Verifier-only: not in any normal action set. Harmless when the dev build
carries no instrumentation — the mark is recorded, nothing follows it.
"""

from agent_core import action


@action(
    name="walk_mark_feature",
    description=(
        "Mark the start of exercising ONE feature during a walk-verify, so "
        "the code it runs through is attributed to it (coverage evidence for "
        "future scoped verifies). Call it right before you begin a feature's "
        "flow, with the feature's exact name from your FEATURES list. Cheap; "
        "never affects the app or the verdict."
    ),
    default=False,
    mode="CLI",
    # Reachable only through the walk_verify sub-agent definition's allow
    # list (like sub_task_end) — never compiled into a task's action list.
    action_sets=[],
    parallelizable=False,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "abc12345",
            "description": "The Living UI project ID (from the query).",
        },
        "feature": {
            "type": "string",
            "example": "Column drag-and-drop reordering",
            "description": "The exact feature name you are about to exercise.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "message": {"type": "string", "example": "marked: Column drag-and-drop reordering"},
    },
    test_payload={
        "project_id": "test123",
        "feature": "Onboarding",
        "simulated_mode": True,
    },
)
async def walk_mark_feature(input_data: dict) -> dict:
    # EVERYTHING LOCAL: handlers run from registry-extracted source (see the
    # note in living_ui_actions.living_ui_walk_verify) — no module globals.
    project_id = str(input_data.get("project_id") or "").strip()
    feature = str(input_data.get("feature") or "").strip()[:200]
    if input_data.get("simulated_mode"):
        return {"status": "success", "message": f"marked: {feature} (simulated)"}
    if not project_id or not feature:
        return {"status": "error", "message": "project_id and feature are required"}
    try:
        import json as _json
        import urllib.request as _url

        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        project = manager.get_project(project_id) if manager else None
        if project is None:
            return {"status": "error", "message": f"Unknown project: {project_id}"}
        base = None
        try:
            from app.factory.host_craftbot import get_factory_host as _gfh

            record = _gfh().get_staging_record(project_id)
            if record and record.get("url"):
                base = str(record["url"]).rstrip("/")
        except Exception:
            base = None
        if base is None:
            # No dev env → the walk is against an external app (live). Marks
            # there are pointless (no instrumentation) but harmless.
            base = (getattr(project, "url", None) or f"http://127.0.0.1:{project.port}").rstrip("/")
        body = _json.dumps({"feature": feature}).encode("utf-8")
        req = _url.Request(
            base + "/api/_coverage/mark",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _url.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception as e:
            # An older app (no /api/_coverage route) or a stopped dev env:
            # the walk must not stall over bookkeeping.
            return {
                "status": "success",
                "message": f"marked: {feature} (not recorded by the app: {type(e).__name__})",
            }
        return {"status": "success", "message": f"marked: {feature}"}
    except Exception as e:
        return {"status": "success", "message": f"marked: {feature} (not recorded: {e})"}
