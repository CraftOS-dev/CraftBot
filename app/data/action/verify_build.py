from agent_core import action


@action(
    name="verify_build",
    description=(
        "Build the app and get back whether it WORKS, with failures grouped "
        "by ROOT CAUSE. This is your source of truth — call it after edits "
        "and before ending. A cascade of hundreds of identical errors (e.g. "
        "every file failing to resolve one import) comes back as ONE cause to "
        "fix, not hundreds of lines. Pass the project path."
    ),
    # Sub-agent-only (like sub_task_todos): not compiled into normal task lists.
    action_sets=[],
    mode="CLI",
    parallelizable=False,
    irreversible=False,
    input_schema={
        "project_path": {
            "type": "string",
            "example": "/path/to/living_ui/my_app",
            "description": "Absolute path to the project root to build.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' when the check ran.",
        },
        "ok": {
            "type": "boolean",
            "example": False,
            "description": "True when the app builds.",
        },
        "failures": {
            "type": "array",
            "example": [
                "TS2307: Cannot find module '@/lib/utils' — 590× (e.g. …); ONE root cause, fix it once"
            ],
            "description": "One line per ROOT CAUSE (empty when ok).",
        },
    },
    test_payload={"project_path": "/tmp/nonexistent", "simulated_mode": True},
)
def verify_build(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "ok": True, "failures": []}

    from pathlib import Path

    from app.workflows.living_ui.verifiers import BuildVerifier
    from app.workflows.living_ui.workspace import Workspace

    raw = str(input_data.get("project_path", "")).strip()
    if not raw or not Path(raw).is_dir():
        return {
            "status": "error",
            "message": f"project_path not found: {raw!r}. Pass the project root.",
        }

    result = BuildVerifier().verify(Workspace(raw))
    if result.ok:
        return {
            "status": "success",
            "ok": True,
            "failures": [],
            "summary": "Build passes.",
        }
    return {
        "status": "success",
        "ok": False,
        "failures": result.failures,
        "summary": f"{len(result.failures)} root cause(s) to fix.",
    }
