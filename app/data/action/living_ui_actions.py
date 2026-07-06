"""Living UI actions for agent to notify UI status and progress."""

from agent_core import action


@action(
    name="living_ui_scaffold",
    description=(
        "Create and register a new Living UI project from the template. "
        "Call this FIRST when building a Living UI from a chat request — i.e. "
        "when your task instruction does NOT already contain a 'Project ID' and "
        "'Project Path' (those come pre-scaffolded from the Create Living UI modal). "
        "This copies the project template (backend/, frontend/, config/), allocates "
        "ports, and registers the project so it appears in the user's Living UI list. "
        "Returns the project_id and an absolute project_path — use project_path as the "
        "base for ALL subsequent file operations so files land in the right folders."
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
            "description": "Short description of what the app does.",
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
            "description": "The created project ID. Pass this to living_ui_notify_ready.",
        },
        "project_path": {
            "type": "string",
            "example": "/workspace/living_ui/stock_forecaster_abc12345",
            "description": "Absolute base path. Use this for ALL file operations.",
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
    # _session_id is injected by the ActionManager; for a Living UI task it equals
    # the task id, which the progress/todo broadcast hooks key off of.
    session_id = input_data.get("_session_id")
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
        from app.living_ui import get_living_ui_manager, broadcast_living_ui_created

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
        )

        # Associate the project with the running task so the agent's todos and
        # progress stream to the Living UI view, then mark it as in-progress.
        if session_id:
            manager.set_project_task(project.id, session_id)
        manager.update_project_status(project.id, "creating")

        # Register it in the browser's project list immediately (modal-parity).
        await broadcast_living_ui_created(project.to_dict())

        return {
            "status": "success",
            "project_id": project.id,
            "project_path": project.path,
            "frontend_port": project.port,
            "backend_port": project.backend_port,
            "message": (
                f"Project '{project.name}' scaffolded at {project.path}. "
                f"Use this absolute path as the base for ALL file operations "
                f"(e.g. {project.path}/backend/models.py, {project.path}/frontend/). "
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
            # Notify browser that the UI is ready
            url = result.get("url", "")
            port = result.get("port", 0)
            await broadcast_living_ui_ready(project_id, url, port)
            return {
                "status": "success",
                "message": f"Living UI {project_id} is now ready at {url}",
            }
        else:
            # Return errors directly so the agent can fix them
            errors = result.get("errors", [])
            errors_str = "\n".join(errors[:10])
            return {
                "status": "error",
                "message": f"Launch failed at step: {result.get('step', 'unknown')}",
                "test_errors": errors[:10],
                "details": f"Fix these errors and call living_ui_notify_ready again:\n{errors_str}",
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
        "(use send_message for runtime narration, or the livingui CLI to read/write data)."
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
                    "the creation phase. Use send_message to narrate runtime work, or the "
                    "livingui CLI to read/write data."
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
    name="living_ui_import_external",
    description=(
        "Import an external app as a Living UI project. "
        "Use this when the user wants to add an existing app (Go, Node.js, Python, Rust, static site) "
        "to their Living UI dashboard. The agent should first analyze the app source code to determine "
        "the runtime, build/install command, start command, and health check strategy, then call this action."
    ),
    action_sets=["living_ui"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Display name for the project.",
            "example": "Glance Dashboard",
        },
        "description": {
            "type": "string",
            "description": "Brief app description.",
            "example": "Self-hosted dashboard",
        },
        "source_path": {
            "type": "string",
            "description": "Absolute path to the app source code.",
            "example": "/path/to/app",
        },
        "app_runtime": {
            "type": "string",
            "description": "Runtime: node, python, go, rust, docker, static, or unknown.",
            "example": "go",
        },
        "install_command": {
            "type": "string",
            "description": "Command to install/build the app (empty if none needed).",
            "example": "go build -o app .",
        },
        "start_command": {
            "type": "string",
            "description": "Command to start the app. Use {{PORT}} placeholder for port.",
            "example": "./app --port {{PORT}}",
        },
        "health_strategy": {
            "type": "string",
            "description": "Health check: http_get, tcp, or process_alive.",
            "example": "http_get",
        },
        "health_url": {
            "type": "string",
            "description": "Health check URL (for http_get). Use {{PORT}} placeholder.",
            "example": "http://localhost:{{PORT}}/health",
        },
        "port_env_var": {
            "type": "string",
            "description": "Env var name for port injection (e.g., PORT). Empty if app uses command-line flag.",
            "example": "PORT",
        },
        "project_id": {
            "type": "string",
            "description": (
                "If the task instruction provided a pre-created project_id "
                "(a tab already shown to the user), pass it here so the import "
                "populates that tab. Omit otherwise."
            ),
            "example": "a1b2c3d4",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "project": {"type": "object", "description": "Project info dict."},
    },
)
async def living_ui_import_external(input_data: dict) -> dict:
    """Import an external app as a Living UI project."""
    try:
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not available."}

        result = await manager.import_external_app(
            name=input_data.get("name", "External App"),
            description=input_data.get("description", ""),
            source_path=input_data["source_path"],
            app_runtime=input_data.get("app_runtime", "unknown"),
            install_command=input_data.get("install_command", ""),
            start_command=input_data.get("start_command", ""),
            health_strategy=input_data.get("health_strategy", "tcp"),
            health_url=input_data.get("health_url", ""),
            port_env_var=input_data.get("port_env_var", "PORT"),
            project_id=input_data.get("project_id") or None,
        )
        return result
    except Exception as e:
        return {"status": "error", "message": f"Import failed: {str(e)}"}


@action(
    name="living_ui_import_zip",
    description=(
        "Import a Living UI project from a ZIP file. "
        "The ZIP should contain a previously exported Living UI project. "
        "A new project ID and ports are allocated automatically. "
        "After importing, launch the project with living_ui_notify_ready."
    ),
    action_sets=["living_ui"],
    input_schema={
        "zip_path": {
            "type": "string",
            "description": "Absolute path to the ZIP file.",
            "example": "/path/to/project.zip",
        },
        "name": {
            "type": "string",
            "description": "Display name for the imported project (optional, auto-detected from manifest).",
            "example": "My App",
        },
        "project_id": {
            "type": "string",
            "description": (
                "If the task instruction provided a pre-created project_id "
                "(a tab already shown to the user), pass it here so the import "
                "populates that tab. Omit otherwise."
            ),
            "example": "a1b2c3d4",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "project_id": {"type": "string", "example": "a1b2c3d4"},
        "message": {"type": "string"},
    },
)
async def living_ui_import_zip(input_data: dict) -> dict:
    """Import a Living UI project from a ZIP file."""
    try:
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not available."}

        zip_path = input_data.get("zip_path", "")
        name = input_data.get("name", "")
        project_id = input_data.get("project_id") or None

        if not zip_path:
            return {"status": "error", "message": "zip_path is required."}

        project = await manager.import_project_zip(zip_path, name, project_id)

        # Clean up the ZIP file after successful import
        import os

        try:
            os.unlink(zip_path)
        except Exception:
            pass

        return {
            "status": "success",
            "project_id": project.id,
            "message": f"Imported '{project.name}' ({project.id}). Call living_ui_notify_ready to launch it.",
            "project": project.to_dict(),
        }
    except Exception as e:
        return {"status": "error", "message": f"ZIP import failed: {str(e)}"}
