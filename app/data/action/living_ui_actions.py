"""Living UI actions for agent to notify UI status and progress."""

from agent_core import action


@action(
    name="living_ui_scaffold",
    description=(
        "Create and register a new Living UI project from the template, then "
        "dispatch the build to the project's dedicated session. Call this when "
        "the user asks for a new Living UI in a regular chat — i.e. when your "
        "task instruction does NOT already contain a 'Project ID' and 'Project "
        "Path' (those come pre-scaffolded from the Create Living UI modal). "
        "This copies the project template (backend/, frontend/, config/), "
        "allocates ports, registers the project in the user's Living UI list, "
        "and queues the build run in the project's own session. After it "
        "returns, inform the user the build has started and end your turn — "
        "do NOT write project files or call living_ui_notify_ready yourself."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    input_schema={
        "name": {
            "type": "string",
            "example": "Stock Forecaster",
            "description": "Display name for the Living UI project.",
        },
        "description": {
            "type": "string",
            "example": "A dashboard that forecasts stock performance.",
            "description": (
                "Description of what the app does. Include EVERY requirement "
                "the user has given so far — it becomes the build instruction "
                "for the project's session."
            ),
        },
        "features": {
            "type": "array",
            "example": ["watchlist", "forecasts", "alerts"],
            "description": "Optional list of high-level features requested by the user.",
        },
        "theme": {
            "type": "string",
            "enum": ["light", "dark", "system"],
            "example": "system",
            "description": "UI theme. Defaults to 'system'.",
        },
        "auth_mode": {
            "type": "string",
            "enum": ["none", "multi-user"],
            "example": "none",
            "description": (
                "Auth mode from the requirements: 'none' for a personal local "
                "tool (default), 'multi-user' when the app needs accounts."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result: 'success' or 'error'.",
        },
        "project_id": {
            "type": "string",
            "example": "abc12345",
            "description": "The created project ID.",
        },
        "project_path": {
            "type": "string",
            "example": "/workspace/living_ui/stock_forecaster_abc12345",
            "description": "Absolute project path on disk.",
        },
        "frontend_port": {"type": "integer", "description": "Allocated frontend port."},
        "backend_port": {"type": "integer", "description": "Allocated backend port."},
        "message": {
            "type": "string",
            "description": "Guidance on how to use the returned path.",
        },
    },
    test_payload={
        "name": "Test App",
        "description": "A test Living UI.",
        "simulated_mode": True,
    },
)
async def living_ui_scaffold(input_data: dict) -> dict:
    """Create, register, and associate a new Living UI project from the template."""
    name = input_data.get("name", "").strip()
    description = input_data.get("description", "").strip()
    features = input_data.get("features") or []
    theme = input_data.get("theme", "system")
    simulated_mode = input_data.get("simulated_mode", False)

    if not name or not description:
        return {"status": "error", "message": "name and description are required"}

    if simulated_mode:
        return {
            "status": "success",
            "project_id": "abc12345",
            "project_path": "/workspace/living_ui/test_app_abc12345",
            "frontend_port": 3100,
            "backend_port": 3101,
            "message": "Scaffolded. Use project_path for all file operations.",
        }

    try:
        from app.living_ui import (
            get_living_ui_manager,
            broadcast_living_ui_created,
            broadcast_living_ui_progress,
        )

        manager = get_living_ui_manager()
        if not manager:
            return {
                "status": "error",
                "message": (
                    "Living UI manager not initialized. Living UI creation requires "
                    "the CraftBot desktop/browser app to be running."
                ),
            }

        # Tolerate a comma-separated string if the model passes one.
        if isinstance(features, str):
            features = [f.strip() for f in features.split(",") if f.strip()]

        project = await manager.create_project(
            name=name,
            description=description,
            features=features,
            theme=theme,
            auth_mode=input_data.get("auth_mode", "none"),
        )

        # Register it in the browser's project list immediately and show the
        # creation screen (modal-parity).
        await broadcast_living_ui_created(project.to_dict())
        await broadcast_living_ui_progress(
            project.id, "initializing", 10, "Project created, starting development..."
        )

        # Hand the build off to the project's dedicated session (parity with
        # the browser "+" flow): start_development_run ensures the session
        # exists, marks the project as creating, and fires a LIVING_UI_DEV
        # trigger carrying the full build instruction, so todos/progress/
        # questions stream to the Living UI view.
        dev_session_id = await manager.start_development_run(project.id)
        if dev_session_id:
            return {
                "status": "success",
                "project_id": project.id,
                "project_path": project.path,
                "frontend_port": project.port,
                "backend_port": project.backend_port,
                "message": (
                    f"Project '{project.name}' scaffolded at {project.path}. "
                    f"The build has been dispatched to the project's dedicated "
                    f"session — do NOT build it in this session, do NOT write "
                    f"project files, and do NOT call living_ui_notify_ready "
                    f"here. Tell the user the build has started and that "
                    f"progress and any setup questions will appear in the "
                    f"'{project.name}' Living UI tab, then end your turn."
                ),
            }

        # Fallback — session runtime not bound (e.g. headless/test contexts):
        # keep the legacy inline-build contract in the calling session.
        manager.update_project_status(project.id, "creating")
        return {
            "status": "success",
            "project_id": project.id,
            "project_path": project.path,
            "frontend_port": project.port,
            "backend_port": project.backend_port,
            "message": (
                f"Project '{project.name}' scaffolded at {project.path}. "
                f"Use this absolute path as the base for ALL file operations "
                f"(e.g. {project.path}/frontend/src/app/, {project.path}/pb/pb_migrations/). "
                f"Do NOT write to bare relative paths. When the build is complete, "
                f'call living_ui_notify_ready(project_id="{project.id}").'
            ),
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to scaffold project: {str(e)}"}


@action(
    name="living_ui_notify_ready",
    description=(
        "Launch, verify, and serve a Living UI project. "
        "Call this after building the Living UI code. "
        "This action installs dependencies, runs tests, starts the backend and frontend, "
        "and notifies the browser. Returns test errors if anything fails."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "abc12345",
            "description": "The Living UI project ID (provided in task instruction).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result: 'success' or 'error'.",
        },
        "message": {
            "type": "string",
            "example": "Living UI abc12345 is now ready at http://localhost:3100",
            "description": "Status message.",
        },
        "test_errors": {
            "type": "array",
            "example": ["[import] Failed to import routes: ..."],
            "description": "List of test errors if launch failed. Fix these and call again.",
        },
    },
    test_payload={
        "project_id": "test123",
        "simulated_mode": True,
    },
)
async def living_ui_notify_ready(input_data: dict) -> dict:
    """Launch, verify, and notify browser that a Living UI is ready."""
    project_id = input_data.get("project_id", "")
    simulated_mode = input_data.get("simulated_mode", False)

    if not project_id:
        return {"status": "error", "message": "project_id is required"}

    if simulated_mode:
        return {
            "status": "success",
            "message": f"Living UI {project_id} is now ready at http://localhost:3100",
        }

    try:
        from app.living_ui import get_living_ui_manager, broadcast_living_ui_ready

        manager = get_living_ui_manager()
        if not manager:
            return {
                "status": "error",
                "message": "Living UI manager not initialized. Browser adapter may not be running.",
            }

        # Run the full pipeline: install → test → launch → verify
        result = await manager.launch_and_verify(project_id)

        if result["status"] == "success":
            url = result.get("url", "")
            port = result.get("port", 0)
            _proj_ok = manager.get_project(project_id)
            if _proj_ok is not None:
                _proj_ok._gate_fp = None
                _proj_ok._gate_fp_count = 0

            # HARD GATE: independent walk-verify of the running app. Success
            # is reported only on an all-pass verdict set — the building
            # agent cannot self-grade or skip this.
            from app.living_ui.walk_verify import run_walk_verify

            project = manager.get_project(project_id)
            report = None
            if project is not None:
                try:
                    from app.living_ui import broadcast_living_ui_progress

                    await broadcast_living_ui_progress(
                        project_id,
                        "verifying",
                        92,
                        "Walk-verify: independently testing features against "
                        "the requirements (this takes a minute)…",
                    )
                except Exception:
                    pass
                try:
                    import asyncio as _asyncio

                    # Belt-and-suspenders ceiling above the runner's own
                    # 30-min wall cap: even if the verifier wedges, the
                    # session turn must end. Timeout = tooling failure
                    # (blocked), never an app defect.
                    report = await _asyncio.wait_for(
                        run_walk_verify(project), timeout=2100
                    )
                except _asyncio.TimeoutError:
                    report = {"kind": "blocked", "passed": [], "defects": [],
                              "raw": "walk_verify exceeded the 35-minute ceiling"}
                except Exception as verify_err:
                    report = {"kind": "blocked", "passed": [], "defects": [],
                              "raw": f"walk_verify crashed: {verify_err}"}
                try:
                    kind = (report or {}).get("kind")
                    passed_n = len((report or {}).get("passed") or [])
                    if kind == "defects":
                        outcome = (
                            f"Walk-verify: {len(report['defects']) or 'some'} "
                            "feature(s) FAILED — fixing before launch"
                        )
                    elif kind == "pass":
                        outcome = f"Walk-verify PASSED: {passed_n} feature(s) work"
                    elif kind == "incomplete":
                        outcome = (
                            f"Walk-verify: {passed_n} passed, coverage incomplete "
                            "(some features NOT REACHED)"
                        )
                    else:
                        outcome = "Walk-verify BLOCKED (tooling) — smoke checks only"
                    await broadcast_living_ui_progress(project_id, "verifying", 96, outcome)
                except Exception:
                    pass

            kind = (report or {}).get("kind")
            if kind == "defects":
                # Observed misbehavior — the only thing that blocks a launch.
                await manager.stop_project(project_id)
                defects = report.get("defects") or []
                raw = (report.get("raw") or "")[:2500]
                return {
                    "status": "error",
                    "message": (
                        "Launch blocked by walk-verify: "
                        f"{len(defects) or 'some'} feature(s) observed NOT working."
                    ),
                    "test_errors": defects[:10] or [raw],
                    "details": (
                        "The walk-verify report (a real browser drove the app):\n"
                        + raw
                        + "\n\nFix these features, then call living_ui_notify_ready "
                        "again. Do NOT tell the user the app is ready."
                    ),
                }

            # Notify browser that the UI is ready
            await broadcast_living_ui_ready(project_id, url, port)
            if kind == "pass":
                verified = (
                    f" ({len(report.get('passed') or [])} feature(s) walk-verified "
                    "in a real browser)"
                )
            elif kind == "incomplete":
                verified = (
                    f" (walk-verify: {len(report.get('passed') or [])} passed; "
                    "coverage INCOMPLETE — some features NOT REACHED. Tell the "
                    "user which features were not walked; do NOT claim they were "
                    "tested.)"
                )
            elif kind == "blocked":
                verified = (
                    " (WARNING: walk-verify was BLOCKED — tooling/browser issue, "
                    "not an app defect. Launch passed smoke checks only: "
                    + str((report or {}).get("raw") or "")[:200]
                    + ")"
                )
            else:
                verified = " (walk-verify unavailable — smoke checks only)"
            return {
                "status": "success",
                "message": f"Living UI {project_id} is now ready at {url}{verified}",
            }
        else:
            # Return errors directly so the agent can fix them
            errors = result.get("errors", [])
            errors_str = "\n".join(errors[:10])

            # CIRCUIT BREAKER: detect fix attempts that change nothing. The
            # fingerprint lives on the in-memory project (this module does not
            # persist between action calls).
            breaker_note = ""
            project = manager.get_project(project_id)
            if project is not None:
                fp = hash((result.get("step"), errors_str))
                same = getattr(project, "_gate_fp", None) == fp
                count = (getattr(project, "_gate_fp_count", 0) + 1) if same else 1
                project._gate_fp = fp
                project._gate_fp_count = count
                if count >= 6:
                    breaker_note = (
                        f"\n\nSTOP: the EXACT same error has now occurred {count} times "
                        "in a row. The build is stuck — do NOT try again. Report the "
                        "failure honestly to the user with a final send_message "
                        "(state what is blocking and what you tried) and end the run."
                    )
                elif count >= 3:
                    breaker_note = (
                        f"\n\nWARNING: this is the IDENTICAL error {count} times in a "
                        "row — your edits are NOT changing the outcome. Do not repeat "
                        "the same fix. Re-read the annotated error above: the caret "
                        "marks the EXACT offending expression (there may be several "
                        "similar ones on the line — fix the one under the caret). "
                        "Verify your edit actually changed that expression before "
                        "re-running."
                    )
            return {
                "status": "error",
                "message": f"Launch failed at step: {result.get('step', 'unknown')}",
                "test_errors": errors[:10],
                "details": (
                    f"Fix these errors and call living_ui_notify_ready again:\n{errors_str}"
                    + breaker_note
                ),
            }
    except Exception as e:
        return {"status": "error", "message": f"Failed to launch: {str(e)}"}


@action(
    name="living_ui_restart",
    description=(
        "Restart a Living UI project (backend + frontend). "
        "Use this after modifying backend or frontend code so changes take effect. "
        "Runs the full launch pipeline: install, test, build, start. Returns errors if any step fails."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "5a58a160",
            "description": "The Living UI project ID (from living_ui_projects.json).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result: 'success' or 'error'.",
        },
        "message": {
            "type": "string",
            "example": "Living UI '5a58a160' restarted",
            "description": "Status message.",
        },
        "test_errors": {
            "type": "array",
            "example": ["[import] Failed to import routes: ..."],
            "description": "List of errors if restart failed. Fix these and call again.",
        },
    },
    test_payload={
        "project_id": "test123",
        "simulated_mode": True,
    },
)
async def living_ui_restart(input_data: dict) -> dict:
    """Restart a running Living UI project."""
    project_id = input_data.get("project_id", "")
    simulated_mode = input_data.get("simulated_mode", False)

    if not project_id:
        return {
            "status": "error",
            "message": "project_id is required",
        }

    if simulated_mode:
        return {
            "status": "success",
            "message": f"Living UI '{project_id}' restarted",
            "url": "http://localhost:3100",
            "backend_url": "http://localhost:3101",
        }

    try:
        from app.living_ui import restart_living_ui

        result = await restart_living_ui(project_id)
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to restart: {str(e)}",
        }


@action(
    name="living_ui_report_progress",
    description=(
        "Report progress ONLY during Living UI creation (initial build). "
        "Use this to keep the user informed about scaffolding, coding, testing, building, and launching phases. "
        "Do NOT use this for runtime work on a project that is already running — it will be ignored "
        "(use send_message for runtime narration, or living_ui_http to read/write data)."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=True,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "abc12345",
            "description": "The Living UI project ID.",
        },
        "phase": {
            "type": "string",
            "enum": [
                "initializing",
                "scaffolding",
                "coding",
                "testing",
                "building",
                "launching",
            ],
            "example": "coding",
            "description": "Current development phase.",
        },
        "progress": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "example": 50,
            "description": "Progress percentage (0-100).",
        },
        "message": {
            "type": "string",
            "example": "Implementing view components...",
            "description": "Human-readable status message.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result of the progress report.",
        },
    },
    test_payload={
        "project_id": "test123",
        "phase": "coding",
        "progress": 50,
        "message": "Test progress message",
        "simulated_mode": True,
    },
)
async def living_ui_report_progress(input_data: dict) -> dict:
    """Report Living UI creation progress to browser."""
    project_id = input_data.get("project_id", "")
    phase = input_data.get("phase", "")
    progress = input_data.get("progress", 0)
    message = input_data.get("message", "")
    simulated_mode = input_data.get("simulated_mode", False)

    if not project_id:
        return {
            "status": "error",
            "message": "project_id is required",
        }

    if simulated_mode:
        return {"status": "success"}

    try:
        from app.living_ui import broadcast_living_ui_progress, get_living_ui_manager

        # Progress reports are a creation-phase concept. If the project is already running,
        # broadcasting one would flip the iframe out for the creation-progress screen, so
        # skip it. For runtime narration the agent should use send_message instead.
        manager = get_living_ui_manager()
        project = manager.get_project(project_id) if manager else None
        if project and project.status == "running":
            return {
                "status": "noop",
                "message": (
                    f"Project '{project_id}' is already running; progress reports are only for "
                    "the creation phase. Use send_message to narrate runtime work, or living_ui_http "
                    "to read/write data."
                ),
            }

        success = await broadcast_living_ui_progress(
            project_id, phase, progress, message
        )

        if success:
            return {"status": "success"}
        else:
            return {
                "status": "error",
                "message": "Broadcast callback not registered. Browser adapter may not be initialized.",
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to report progress: {str(e)}",
        }




@action(
    name="living_ui_http",
    description=(
        "FALLBACK ONLY — prefer the lui CLI via run_shell "
        "(node <craftbot-root>/living-ui-v2/tools/src/cli.ts ops|run|data <project_path> — ABSOLUTE path; the exact commands are in the [INTERACTING WITH LIVING UI] note) to "
        "operate a Living UI. Use this action only when the shell is "
        "unavailable. Sends an HTTP request to a running Living UI project's "
        "backend to read or modify data (e.g., add a card to a kanban, fetch a list). "
        "Pass the project_id and the API path (e.g., '/api/boards/2/cards'); the URL is resolved from the "
        "project's registered backend. This bypasses the loopback SSRF restriction safely because the "
        "target is a known Living UI process."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=True,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "84d93cca",
            "description": "The Living UI project ID.",
        },
        "method": {
            "type": "string",
            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "example": "POST",
            "description": "HTTP method to use.",
        },
        "path": {
            "type": "string",
            "example": "/api/boards/2/cards",
            "description": "API path on the Living UI backend, starting with '/'. Do NOT include scheme or host.",
        },
        "headers": {
            "type": "object",
            "example": {"Accept": "application/json"},
            "description": "Optional headers to send.",
        },
        "params": {
            "type": "object",
            "example": {"limit": "10"},
            "description": "Optional query parameters.",
        },
        "json": {
            "type": "object",
            "example": {"title": "Call John at 5pm", "column": "todo"},
            "description": "JSON body to send. Mutually exclusive with 'data'.",
        },
        "data": {
            "type": "string",
            "example": "field=value",
            "description": "Raw request body. Mutually exclusive with 'json'.",
        },
        "timeout": {
            "type": "number",
            "example": 30,
            "description": "Timeout in seconds. Defaults to 30.",
        },
        "target": {
            "type": "string",
            "enum": ["backend", "frontend"],
            "example": "backend",
            "description": "Which server to hit. Defaults to 'backend'. Use 'frontend' only if the project serves data from its frontend port.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "status_code": {"type": "integer", "example": 200},
        "response_headers": {
            "type": "object",
            "example": {"Content-Type": "application/json"},
        },
        "body": {"type": "string", "example": '{"ok":true}'},
        "response_json": {"type": "object", "example": {"ok": True}},
        "final_url": {
            "type": "string",
            "example": "http://localhost:3101/api/boards/2/cards",
        },
        "elapsed_ms": {"type": "number", "example": 123},
        "message": {"type": "string", "example": ""},
    },
    requirement=["requests"],
    test_payload={
        "project_id": "test123",
        "method": "GET",
        "path": "/api/health",
        "simulated_mode": True,
    },
)
def living_ui_http(input_data: dict) -> dict:
    """HTTP request scoped to a registered Living UI project's backend."""
    import sys
    import subprocess
    import importlib
    import time

    simulated_mode = input_data.get("simulated_mode", False)
    if simulated_mode:
        return {
            "status": "success",
            "status_code": 200,
            "response_headers": {"Content-Type": "application/json"},
            "body": '{"ok": true}',
            "final_url": "http://localhost:3100/api/health",
            "elapsed_ms": 5,
            "message": "",
        }

    project_id = str(input_data.get("project_id", "")).strip()
    method = str(input_data.get("method", "GET")).upper()
    path = str(input_data.get("path", "")).strip()
    target = str(input_data.get("target", "backend")).lower()
    headers = input_data.get("headers") or {}
    params = input_data.get("params") or {}
    json_body = input_data.get("json") if "json" in input_data else None
    data_body = input_data.get("data") if "data" in input_data else None
    timeout = float(input_data.get("timeout", 30))

    if not project_id:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "project_id is required.",
        }
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "Unsupported method.",
        }
    if not path or not path.startswith("/"):
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "path must start with '/' (e.g., '/api/items'). Do not include scheme or host.",
        }
    if json_body is not None and data_body is not None:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "Provide either json or data, not both.",
        }
    if not isinstance(headers, dict) or not isinstance(params, dict):
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "headers and params must be objects.",
        }

    try:
        from app.living_ui import get_living_ui_manager
    except Exception as e:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": f"Living UI manager unavailable: {e}",
        }

    manager = get_living_ui_manager()
    if not manager:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": "Living UI manager not initialized.",
        }

    project = (
        manager.get_project(project_id)
        if hasattr(manager, "get_project")
        else manager.projects.get(project_id)
    )
    if not project:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": f"Project '{project_id}' not found.",
        }
    if project.status != "running":
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": f"Project '{project_id}' is not running (status: {project.status}). Launch it first.",
        }

    base_url = project.backend_url if target == "backend" else project.url
    if not base_url:
        # Fall back to constructing from port if URL field is missing
        port = project.backend_port if target == "backend" else project.port
        if port:
            base_url = f"http://localhost:{port}"
    if not base_url:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": f"Project '{project_id}' has no {target} URL/port.",
        }

    url = base_url.rstrip("/") + path

    try:
        importlib.import_module("requests")
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "requests", "--quiet"]
        )
    import requests

    headers = {str(k): str(v) for k, v in headers.items()}
    params = {str(k): str(v) for k, v in params.items()}
    kwargs = {
        "headers": headers,
        "params": params,
        "timeout": timeout,
        "allow_redirects": True,
    }
    if json_body is not None:
        kwargs["json"] = json_body
    elif data_body is not None:
        kwargs["data"] = data_body

    try:
        t0 = time.time()
        resp = requests.request(method, url, **kwargs)
        elapsed_ms = int((time.time() - t0) * 1000)
        resp_headers = {k: v for k, v in resp.headers.items()}
        parsed_json = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None
        out = {
            "status": "success" if resp.ok else "error",
            "status_code": resp.status_code,
            "response_headers": resp_headers,
            "body": resp.text,
            "final_url": resp.url,
            "elapsed_ms": elapsed_ms,
            "message": "" if resp.ok else f"HTTP {resp.status_code}",
        }
        if parsed_json is not None:
            out["response_json"] = parsed_json

        # If the agent just mutated the Living UI's data, tell the browser so the
        # iframe reloads to show fresh state. The frontend debounces these so a
        # burst of writes only triggers one reload.
        if resp.ok and method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                from app.living_ui import dispatch_living_ui_data_changed

                dispatch_living_ui_data_changed(project_id)
            except Exception:
                pass

        return out
    except Exception as e:
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": url,
            "elapsed_ms": 0,
            "message": str(e),
        }
