"""Living UI actions for agent to notify UI status and progress."""

import logging

from agent_core import action

logger = logging.getLogger(__name__)


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
        "and runs a requirements check: if the chat already answers everything "
        "a builder needs, the build is dispatched immediately — otherwise "
        "setup questions open in a popup in the user's browser (the same "
        "interview the Create Living UI wizard uses) and the build starts "
        "automatically when the user answers them. Follow the returned "
        "message either way. Do NOT write project files or call "
        "living_ui_notify_ready yourself."
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
        "chat_context": {
            "type": "string",
            "example": (
                'User: "I run a small pottery studio" / User: "no existing '
                'tools, maybe a marketplace app could help"'
            ),
            "description": (
                "The user's OWN words from the conversation that led here — "
                "verbatim quotes of what they asked for, constraints they "
                "stated, and hints they dropped. The requirements interviewer "
                "reads this to avoid asking what the user already answered; "
                "your description alone is a summary and loses their intent."
            ),
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
            "description": (
                "The created project ID. ABSENT when setup questions opened "
                "in the user's browser instead — the project is created when "
                "they answer."
            ),
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

        # Requirements phase FIRST — modal parity end to end (Chat →
        # Interview → Finalize → Scaffold). The chat path used to skip the
        # interview entirely: the agent authored the binding spec from its
        # own summary, and infeasible features like "search Google for
        # leads" sailed into walk-verify unchallenged. The interviewer asks
        # ONLY what the chat left genuinely open (marketplace reuse check
        # included). Open questions → NO project is created here; the
        # wizard UI is summoned and its finalize creates the project
        # exactly as the Add Living UI modal does. A cancelled popup, like
        # a cancelled modal wizard, leaves nothing behind.
        from app.living_ui import wizard

        chat_context = str(input_data.get("chat_context") or "").strip()
        wizard_config = {
            "name": name,
            "description": description,
            # Prompt-only material (never stored as the project description).
            "context": (
                ("Requested features: " + ", ".join(map(str, features)) + "\n\n")
                if features
                else ""
            )
            + (
                "From the chat (user's own words):\n" + chat_context
                if chat_context
                else ""
            ),
            "layout": "free",
            "authMode": input_data.get("auth_mode", "none"),
        }
        try:
            questions = await wizard.generate_interview(
                wizard_config, [], allow_empty=True
            )
        except Exception:
            # Fail-open: the interviewer must never block creation.
            questions = []

        if questions:
            # Summon the SAME Create Custom wizard UI the Add Living UI
            # modal uses, opened at the interview step. Fail-open: no
            # browser to show the popup (headless) → fall through and
            # build without questions.
            import uuid as _uuid

            from app.living_ui import broadcast_living_ui_wizard_open

            _opened = False
            try:
                _opened = await broadcast_living_ui_wizard_open(
                    {
                        "wizardId": f"chat_{_uuid.uuid4().hex[:12]}",
                        "config": wizard_config,
                        "questions": questions,
                        # Round-tripped through the wizard to finalize, which
                        # notifies this session of the created project.
                        "originSessionId": input_data.get("_session_id") or "",
                    }
                )
            except Exception:
                _opened = False
            if _opened:
                return {
                    "status": "success",
                    "message": (
                        f"No project created yet: {len(questions)} setup "
                        "question(s) just opened in a popup in the user's "
                        "browser. The project is created and the build "
                        "starts automatically when the user answers them — "
                        "you will be notified with the project_id then "
                        "(and living_ui_list_projects finds any project "
                        "later). Tell the user to answer the setup "
                        "questions that just appeared, then end your turn. "
                        "Do NOT relay the questions in chat, do NOT build "
                        "anything, and do NOT call this action again for "
                        "the same app."
                    ),
                }

        project = await manager.create_project(
            name=name,
            description=description,
            features=features,
            theme=theme,
            auth_mode=input_data.get("auth_mode", "none"),
        )

        # Remember which chat asked for this app. The wizard-finalize path
        # records this via originSessionId; without it here the delivery
        # announce has no origin chat to notify and the requesting
        # conversation never learns the build finished (observed live
        # 2026-08-05, Rock Bottom Outreach).
        try:
            from app.factory.host_craftbot import get_factory_host

            _origin = str(input_data.get("_session_id") or "").strip()
            if _origin:
                get_factory_host().set_origin_session(project.id, _origin)
        except Exception:
            pass

        # Register it in the browser's project list immediately and show the
        # creation screen (modal-parity).
        await broadcast_living_ui_created(project.to_dict())

        # Nothing open — synthesize the binding spec now so the build and
        # walk-verify work from a platform-aware document instead of the
        # agent's prose. Fail-open: a synthesis error falls back to the
        # legacy description-only build rather than blocking creation.
        try:
            await wizard.synthesize_to_project(project.path, wizard_config, [])
        except Exception:
            pass

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
    name="living_ui_list_projects",
    description=(
        "List the user's Living UI projects: id, name, status, URL, path, "
        "and whether the app is delivered. Call this FIRST whenever the "
        "user refers to a Living UI you don't have a project_id for ('the "
        "app', 'my tracker', 'add it to the living UI') — never ask the "
        "user for a project id or path, and never search the filesystem "
        "for projects."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=True,
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result: 'success' or 'error'.",
        },
        "projects": {
            "type": "array",
            "description": (
                "One entry per project: {id, name, description, status, "
                "url, path, delivered}."
            ),
        },
        "message": {"type": "string", "description": "Summary line."},
    },
    test_payload={"simulated_mode": True},
)
async def living_ui_list_projects(input_data: dict) -> dict:
    """Compact registry listing so any session can resolve 'the app' to a
    project_id instead of asking the user or grepping the workspace."""
    if input_data.get("simulated_mode", False):
        return {"status": "success", "projects": [], "message": "0 project(s)."}
    try:
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not initialized"}

        def _delivered(project_id: str) -> bool:
            # Structural: an app with a live environment has been delivered
            # (promoted or installed) — no stored flag to go stale.
            try:
                from app.factory.host_craftbot import get_factory_host as _gfh
                from app.living_ui.lifecycle import has_live_env as _hle

                p = manager.projects.get(project_id)
                return p is not None and _hle(p, _gfh())
            except Exception:
                return False

        projects = []
        for p in manager.projects.values():
            projects.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "description": (p.description or "")[:160],
                    "status": p.status,
                    "url": p.url or (f"http://127.0.0.1:{p.port}" if p.port else ""),
                    "path": p.path,
                    "delivered": _delivered(p.id),
                }
            )
        return {
            "status": "success",
            "projects": projects,
            "message": f"{len(projects)} Living UI project(s).",
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to list projects: {str(e)}"}


@action(
    name="living_ui_notify_ready",
    description=(
        "Gate and boot a Living UI project's DEV environment after a CODE "
        "change: installs dependencies, runs the validation gate, and serves "
        "your new code on a hidden port with a FRESH empty database "
        "(migrations replay at boot — no real data is ever cloned into it). "
        "Returns the dev URL: test there. The user's live app (if any) keeps "
        "running the previous version until walk_verify passes and promotes "
        "the change. Call this ONLY after CREATING or CHANGING the app's CODE "
        "(migrations, hooks, frontend) — adding, editing or deleting DATA "
        "never requires it. EXTERNAL apps relaunch live instead (no dev env). "
        "Returns test errors if anything fails."
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
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {
                "status": "error",
                "message": "Living UI manager not initialized. Browser adapter may not be running.",
            }

        # ONE flow for first builds and modifies: native apps are gated and
        # served in a DEV environment — the project's code on a hidden port
        # with a FRESH schema-only DB (migrations replay at boot; live data
        # is never cloned). The live app (if any) keeps running the previous
        # working version until walk_verify passes and PROMOTES the change.
        # The gate's vite build overwrites the served pb_public in place, so
        # running the pipeline on the real dir would blank a live UI — the
        # dev copy also absorbs that. EXTERNAL apps have no dev env (nothing
        # pb/-shaped) — they always (re)launch live via their own pipeline.
        _proj_pre = manager.get_project(project_id)
        _is_external = (
            _proj_pre is not None
            and getattr(_proj_pre, "project_type", "native") == "external"
        )
        _live_exists = False
        try:
            from app.living_ui.lifecycle import live_db_exists as _lde

            _live_exists = _proj_pre is not None and _lde(_proj_pre.path)
        except Exception:
            pass

        if _is_external:
            # Run the external pipeline live: changes apply directly.
            result = await manager.launch_and_verify(project_id)
        else:
            result = await manager.open_dev(project_id)

        if result["status"] == "success":
            url = result.get("url", "")
            _proj_ok = manager.get_project(project_id)
            if _proj_ok is not None:
                _proj_ok._gate_fp = None
                _proj_ok._gate_fp_count = 0

            # Launched, healthy, smoke-passed — but NOT yet feature-verified.
            # Verification is its own visible step: living_ui_walk_verify.
            # Tell the machine the pipeline is clean → it now expects a
            # verifier verdict (and will redispatch if this run just stops).
            try:
                from app.factory.host_craftbot import get_factory_host

                get_factory_host().report_launch_success(project_id)
            except Exception:
                pass
            env_note = (
                (
                    "This is the DEV environment: your new code with a FRESH, "
                    "empty database (migrations replayed — only data your "
                    "migrations seed exists; create any test records you "
                    "need). "
                    + (
                        "The user's live app is untouched and still runs the "
                        "previous version; a passing walk_verify deploys your "
                        "change to it. "
                        if _live_exists
                        else "A passing walk_verify delivers the app to the "
                        "user with a clean database. "
                    )
                    + "Test ONLY against this dev URL. "
                )
                if not _is_external
                else (
                    "This EXTERNAL app runs live in its own runtime — changes "
                    "apply directly; evidence is in logs/app.log. "
                )
            )
            # Warn-only spec belt (LIFECYCLE-PLAN Phase 1): a modify whose
            # request never reached requirements.md gets verified against a
            # stale contract — the verifier can't cover a change nobody
            # recorded. Never blocks a launch; everything here fails open.
            spec_note = ""
            if _live_exists and not _is_external and _proj_ok is not None:
                try:
                    from pathlib import Path as _Path

                    from app.factory.host_craftbot import get_factory_host as _gfh3

                    _req = _Path(str(_proj_ok.path)) / "reference" / "requirements.md"
                    _delivered_ts = _gfh3().delivered_at(project_id)
                    if (
                        _req.exists()
                        and _delivered_ts
                        and _req.stat().st_mtime < _delivered_ts
                        and "## Changes"
                        not in _req.read_text(encoding="utf-8", errors="replace")
                    ):
                        spec_note = (
                            "WARNING: reference/requirements.md has not been "
                            "updated since delivery — append this change to "
                            "its '## Changes' section (dated bullet) BEFORE "
                            "verifying, or the verifier will check a stale "
                            "spec and skip your change. "
                        )
                except Exception:
                    spec_note = ""
            _dir_note = (
                f"Its files and logs are at {result.get('dir')} (read logs "
                "THERE — your edits still go in the real project dir; "
                "notify_ready syncs them in). "
                if result.get("dir")
                else ""
            )
            return {
                "status": "success",
                "message": (
                    f"App launched at {url} — gate, health and smoke checks "
                    f"passed. {env_note}{_dir_note}{spec_note}NOT VERIFIED "
                    "YET: now call "
                    f'living_ui_walk_verify(project_id="{project_id}") to run '
                    "the independent verifier against the running app. The "
                    "build is complete ONLY when that returns success — do "
                    "NOT tell the user the app is ready before then."
                ),
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
    name="living_ui_walk_verify",
    description=(
        "Run the independent walk-verify sub-agent against the project's "
        "DEV environment: a real browser (headless) drives the app "
        "feature-by-feature against reference/requirements.md. A clean "
        "verdict PROMOTES the verified code to the live app (first build: "
        "creates its live database fresh from migrations; update: applies "
        "new migrations to the real data) and announces it — the ONLY way a "
        "Living UI change completes. Observed defects return the failure "
        "report: fix, relaunch with living_ui_notify_ready, then call this "
        "again. Requires living_ui_notify_ready first (it boots the dev "
        "env; external apps verify live instead). "
        "ONLY after building or modifying the app's CODE, never after a "
        "plain data change: it clicks through the UI creating test records "
        "(in the dev env's disposable DB, but pointless for data edits)."
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
            "description": "'success' = app verified and announced ready.",
        },
        "message": {
            "type": "string",
            "example": "Living UI abc12345 is now ready (5 features walk-verified).",
            "description": "Outcome summary.",
        },
        "test_errors": {
            "type": "array",
            "example": ["- Onboarding — FAIL — form does not save"],
            "description": "Observed defects when verification fails.",
        },
    },
    test_payload={
        "project_id": "test123",
        "simulated_mode": True,
    },
)
async def living_ui_walk_verify(input_data: dict) -> dict:
    """Independent feature verification of the running app; announces the
    app on a clean verdict."""
    project_id = input_data.get("project_id", "")
    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "message": f"Living UI {project_id} verified (simulated).",
        }
    if not project_id:
        return {"status": "error", "message": "project_id is required"}

    try:
        import asyncio as _asyncio

        from app.living_ui import (
            broadcast_living_ui_progress,
            broadcast_living_ui_ready,
            get_living_ui_manager,
        )
        from app.living_ui.walk_verify import run_walk_verify

        manager = get_living_ui_manager()
        project = manager.get_project(project_id) if manager else None
        if project is None:
            return {"status": "error", "message": f"Unknown project: {project_id}"}

        # NATIVE apps always verify against their DEV environment (new code,
        # fresh schema-only DB, hidden port) — never against the live app,
        # whose DB holds real user data. `url` stays the REAL app's address:
        # it is what gets announced after the promote. EXTERNAL apps have no
        # dev env (no pb_data to protect) — they always verify live.
        _is_external = getattr(project, "project_type", "native") == "external"
        _dev_record = None
        if not _is_external:
            try:
                from app.factory.host_craftbot import get_factory_host as _gfh

                _dev_record = _gfh().get_staging_record(project_id)
            except Exception:
                _dev_record = None
            if not _dev_record:
                return {
                    "status": "error",
                    "message": (
                        "Verification runs against the DEV environment, and "
                        "none exists. Call living_ui_notify_ready first (it "
                        "boots your code in the dev env), then verify."
                    ),
                }
        if _is_external and project.status != "running":
            return {
                "status": "error",
                "message": (
                    "The app is not running — call living_ui_notify_ready "
                    "first, then verify."
                ),
            }
        url = f"http://127.0.0.1:{project.port}"
        verify_url = str(_dev_record.get("url")) if _dev_record else url
        verify_path = str(_dev_record.get("dir")) if _dev_record else None

        try:
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
            # Belt-and-suspenders ceiling above the runner's own 30-min wall
            # cap: even if the verifier wedges, the turn must end. Timeout =
            # tooling failure (blocked), never an app defect.
            report = await _asyncio.wait_for(
                run_walk_verify(project, base_url=verify_url, project_path=verify_path),
                timeout=2100,
            )
        except _asyncio.TimeoutError:
            report = {
                "kind": "blocked",
                "passed": [],
                "defects": [],
                "raw": "walk_verify exceeded the 35-minute ceiling",
            }
        except Exception as verify_err:
            report = {
                "kind": "blocked",
                "passed": [],
                "defects": [],
                "raw": f"walk_verify crashed: {verify_err}",
            }

        kind = (report or {}).get("kind")
        passed_n = len((report or {}).get("passed") or [])
        try:
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

        # Distinguish a genuinely blocked verifier (browser/tooling died —
        # legitimate announce-with-warning) from an UNPARSEABLE report (the
        # sub-agent produced nonsense): announcing on nonsense is the
        # fail-open hole the factory closes (FACTORY-PLAN §3.3).
        if kind == "blocked":
            from app.living_ui.walk_verify import _reads_as_blocked

            raw_text = str((report or {}).get("raw") or "")
            if raw_text.strip() and not _reads_as_blocked(raw_text):
                kind = "unparseable"

        # The verifier's own LLM was throttled/unavailable — the app was
        # never judged. Say so and have the agent retry after a pause,
        # WITHOUT advancing the machine: burning the one unparseable retry
        # on a provider rate limit stuck a healthy modify (observed live
        # 2026-08-06, two walkers dead 4s apart). Bounded: after 3 throttled
        # deaths in an hour it falls through to the stuck belt for real.
        if kind == "throttled":
            from app.factory.host_craftbot import get_factory_host

            _throttles = get_factory_host().bump_throttle_retry(project_id)
            if _throttles <= 3:
                return {
                    "status": "error",
                    "message": (
                        "The verifier could not run: its LLM provider is "
                        "rate-limiting (NOT an app defect — nothing was "
                        "judged). Do other useful work for at least a minute "
                        "(re-read the requirements, check the server log), "
                        "then call living_ui_walk_verify again. Do NOT "
                        "change app code because of this error."
                    ),
                }
            _throttle_exhausted = True
            kind = "unparseable"  # provider stayed down — escalate honestly
        else:
            _throttle_exhausted = False

        # An "incomplete" with ZERO passed features is not a coverage
        # caveat — nothing at all stands behind "ready" but smoke checks
        # (observed live 2026-08-05: "✅ ready — ⚠️ 0 feature(s) verified").
        # Route it through the same one-retry-then-stuck belt as
        # unparseable, with its own honest message.
        _zero_verified = kind == "incomplete" and passed_n == 0
        if _zero_verified:
            kind = "unparseable"

        if kind == "unparseable":
            from app.factory.host_craftbot import get_factory_host

            decision = get_factory_host().report_verify(project_id, "unparseable")
            if _throttle_exhausted:
                _what = (
                    "The verifier's LLM provider stayed rate-limited across "
                    "repeated attempts (the app itself was never judged)"
                )
            elif _zero_verified:
                _what = (
                    "The verifier finished with ZERO features verified (all "
                    "NOT REACHED) — that is not deliverable"
                )
            else:
                _what = "The verifier's report was unparseable (not a browser failure)"
            if decision is not None and decision.payload.get("redo") == "verify":
                return {
                    "status": "error",
                    "message": f"{_what}. Call living_ui_walk_verify once more.",
                }
            return {
                "status": "error",
                "message": (
                    f"{_what} — twice. The system has reported the build as "
                    "stuck to the user. End the run."
                ),
            }

        if kind == "defects":
            # Observed misbehavior — the only thing that blocks a promote.
            # Native: the LIVE app (if any) runs the previous working
            # version and stays up — availability wins; only the broken
            # change (in the dev env, which stays up for the fix mission) is
            # withheld. External: stop the live app as before.
            if _is_external:
                await manager.stop_project(project_id)
            defects = report.get("defects") or []
            raw = (report.get("raw") or "")[:2500]
            # The browser report says WHAT failed; the server log says WHY
            # (hook exceptions, bad queries — logged via the console.error
            # pattern). Without it, agents invent causes: one read a bare
            # failure and diagnosed "no outbound internet access".
            #
            # EVERYTHING LOCAL: action handlers run from REGISTRY-EXTRACTED
            # SOURCE, not as this module — module-level imports/globals do
            # not exist at execution time. A module-level `Path` silently
            # broke this block once, and a module-level `logger` then took
            # down every walk_verify call in a run.
            server_log = ""
            try:
                from pathlib import Path as _Path

                # The dev instance under test wrote ITS OWN log — quoting
                # the live app's log here would attribute the old version's
                # lines to the new code.
                _log_root = str(verify_path or project.path)
                pb_log = _Path(_log_root) / "logs" / "pocketbase.log"
                # External apps log to app.log (their own runtime, no PB).
                _app_log = _Path(_log_root) / "logs" / "app.log"
                if not pb_log.exists() and _app_log.exists():
                    pb_log = _app_log
                if pb_log.exists():
                    lines = pb_log.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()[-400:]
                    # Errors FIRST, then newest lines: a naive tail once
                    # shipped realtime chatter while "cannot be blank" errors
                    # sat just above the 30-line window.
                    error_lines = [
                        ln
                        for ln in lines
                        if any(
                            k in ln.lower()
                            for k in ("error", "failed", "panic", "cannot be")
                        )
                    ][-25:]
                    tail = [ln for ln in lines[-8:] if ln not in error_lines]
                    server_log = (
                        "\n\npocketbase.log (recent — the server-side causes):\n"
                        + "\n".join(error_lines + tail)
                    )
                else:
                    import logging as _logging

                    _logging.getLogger(__name__).warning(
                        f"[WALK_VERIFY] no pocketbase.log at {pb_log} — "
                        "defect report ships without server-side causes"
                    )
            except Exception as e:
                # Never break the report — but never eat the reason either.
                try:
                    import logging as _logging

                    _logging.getLogger(__name__).warning(
                        f"[WALK_VERIFY] could not attach pocketbase.log: {e}"
                    )
                except Exception:
                    pass
            full_details = (
                "The walk-verify report (a real browser drove the app):\n"
                + raw
                + server_log
            )
            # The MACHINE owns the fix arc now (FACTORY-PLAN Phase 1): it
            # records the failure, applies caps, and dispatches a FRESH fix
            # mission carrying this evidence. This run's job is over.
            from app.factory.host_craftbot import get_factory_host

            decision = get_factory_host().report_verify(
                project_id,
                "defects",
                defects=defects,
                details=full_details,
                walk_report=raw,
                server_log=server_log,
            )
            _stopped_note = (
                "The app was stopped. "
                if _is_external
                else (
                    "The change was NOT deployed — the user's live app still "
                    "runs the previous working version. "
                )
            )
            if decision is None:
                # Machine done (a re-verify after delivery, outside a modify
                # arc): report_verify ignored the verdict and dispatched
                # NOTHING. Falling through to the "mission queued" text here
                # made the agent end the run waiting for a mission that
                # never comes. (Stuck machines no longer land here — a fresh
                # verify re-arms them and dispatches a real mission.)
                return {
                    "status": "error",
                    "message": (
                        f"Walk-verify FAILED: {len(defects) or 'some'} "
                        f"feature(s) observed NOT working. {_stopped_note}"
                        "The build machine is not tracking this arc, so the "
                        "system did NOT queue a fix mission and will NOT "
                        "retry on its own — do not claim otherwise. Report "
                        "the remaining failures (test_errors below) to the "
                        "user honestly, then end the run."
                    ),
                    "test_errors": defects[:10] or [raw],
                }
            if decision.next_state == "stuck":
                return {
                    "status": "error",
                    "message": (
                        f"Walk-verify FAILED: {len(defects) or 'some'} feature(s) "
                        "NOT working — and the retry cap is reached. The system "
                        "has reported the build as stuck to the user, with the "
                        "full history. Do NOT retry and do NOT send a status "
                        "message. End the run."
                    ),
                    "test_errors": defects[:10] or [raw],
                }
            return {
                "status": "error",
                "message": (
                    f"Walk-verify FAILED: {len(defects) or 'some'} feature(s) "
                    f"observed NOT working. {_stopped_note}A FRESH fix "
                    "mission carrying the full evidence has been queued by the "
                    "system — do NOT fix in this run and do NOT send a status "
                    "message. End the run now."
                ),
                "test_errors": defects[:10] or [raw],
            }

        # Clean verdict (pass / incomplete / tooling-blocked): the MACHINE
        # announces to the user (FACTORY-PLAN §3.6 — no agent-authored
        # status); this run just ends.
        #
        # PROMOTE comes FIRST, before any user-facing signal
        # (docs/plans/living-ui-unified-lifecycle-plan.md): the real app
        # boots with the verified code — pb_data absent (first delivery) →
        # the migration chain creates it fresh; pb_data present (update) →
        # new migrations apply on top and the data is otherwise untouched —
        # then the dev env and every test record in it are destroyed. There
        # is NO other path that touches a live database.
        promoted = await manager.promote(project_id)
        if promoted.get("status") != "success":
            return {
                "status": "error",
                "message": (
                    "Verification PASSED in the dev environment, but "
                    "deploying the change to the live app failed at step "
                    f"'{promoted.get('step', 'unknown')}'. The dev env was "
                    "kept. Fix the errors below, then call "
                    "living_ui_notify_ready and living_ui_walk_verify again."
                ),
                "test_errors": promoted.get("errors", [])[:10],
            }

        await broadcast_living_ui_ready(project_id, url, project.port)
        if kind == "pass":
            caveat = ""
        elif kind == "incomplete":
            caveat = (
                f"Coverage incomplete: {passed_n} feature(s) verified; some "
                "were NOT exercised (see the report). Unverified features may "
                "not work yet."
            )
        elif kind == "blocked":
            caveat = (
                "The independent verifier could not run (browser/tooling "
                "issue) — the app passed launch and smoke checks only; no "
                "feature was browser-verified."
            )
        else:
            caveat = "Verifier unavailable — smoke checks only."

        from app.factory.host_craftbot import get_factory_host

        _pass_decision = get_factory_host().report_verify(
            project_id,
            kind if kind in ("pass", "incomplete", "blocked") else "blocked",
            url=url,
            verified=report.get("passed") or [],
            caveat=caveat,
        )
        if _pass_decision is None:
            # Machine done (re-verify after delivery, outside a modify arc):
            # report_verify ignored the verdict, so no ready announcement
            # went out — telling the agent "the system has announced this"
            # would swallow a successful fix silently.
            return {
                "status": "success",
                "message": (
                    f"Living UI {project_id} is ready at {url}, but the "
                    "build machine is already in a terminal state, so the "
                    "system did NOT announce it. Send the user a short "
                    "ready message yourself (include the caveat, if any), "
                    "then end the run." + (f" Caveat: {caveat}" if caveat else "")
                ),
            }
        return {
            "status": "success",
            "message": (
                f"Living UI {project_id} is ready at {url}. The system has "
                "announced this to the user (including any caveats). Do NOT "
                "send your own summary — end the run, or answer only direct "
                "questions."
            ),
        }
    except Exception as e:
        return {"status": "error", "message": f"walk-verify failed to run: {str(e)}"}


@action(
    name="living_ui_ops_verify",
    description=(
        "Verify an EXTERNAL (adopted third-party) app's A2App operation "
        "mappings against the RUNNING app: validates operations.json "
        "structurally, probes the adapter's identity endpoint, then invokes "
        "every non-destructive operation FOR REAL through /api/ops/* with "
        "synthesized parameters (destructive ops are shape-checked, never "
        "invoked). Call during adoption AFTER living_ui_notify_ready and "
        "after every operations.json edit; a mapping that does not work "
        "must be fixed or removed — the import is not done until this "
        "passes. Only meaningful for external projects (natives verify ops "
        "through the build gate)."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "abc12345",
            "description": "The external Living UI project ID.",
        },
        "op_names": {
            "type": "array",
            "example": ["todos.create"],
            "description": (
                "Optional: verify only these operations. Default: all "
                "declared operations."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": (
                "'success' = manifest valid, identity answers, every "
                "checked op passed (or is destructive and was shape-checked)."
            ),
        },
        "checked": {"type": "integer", "example": 4},
        "passed": {"type": "integer", "example": 3},
        "failed": {"type": "integer", "example": 0},
        "results": {
            "type": "array",
            "example": [
                {"op": "todos.create", "outcome": "pass", "status": 200}
            ],
            "description": (
                "Per-op outcome: pass | skipped_destructive | "
                "unknown_operation | upstream_not_found | rejected_params | "
                "upstream_error | unreachable | failed, with detail."
            ),
        },
        "message": {
            "type": "string",
            "example": "A2App surface verified: 3 op(s) invoked live.",
            "description": "Outcome summary with fix guidance on failure.",
        },
    },
    test_payload={
        "project_id": "test123",
        "simulated_mode": True,
    },
)
async def living_ui_ops_verify(input_data: dict) -> dict:
    """Live verification of an external app's declared A2App operations."""
    project_id = str(input_data.get("project_id", "")).strip()
    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "checked": 1,
            "passed": 1,
            "failed": 0,
            "results": [{"op": "todos.create", "outcome": "pass", "status": 200}],
            "message": f"A2App surface of {project_id} verified (simulated).",
        }
    if not project_id:
        return {"status": "error", "message": "project_id is required"}
    try:
        from app.living_ui import get_living_ui_manager
        from app.living_ui.ops_verify import verify_external_ops

        manager = get_living_ui_manager()
        project = manager.get_project(project_id) if manager else None
        if project is None:
            return {"status": "error", "message": f"Unknown project: {project_id}"}
        if getattr(project, "project_type", "native") != "external":
            return {
                "status": "error",
                "message": (
                    f"'{project_id}' is a native Living UI — its operations "
                    "are gate-verified at build; this action is for adopted "
                    "external apps."
                ),
            }
        if project.status != "running" or not project.port:
            return {
                "status": "error",
                "message": (
                    f"Project '{project_id}' is not running — call "
                    "living_ui_notify_ready first."
                ),
            }
        op_names = input_data.get("op_names") or None
        return await verify_external_ops(project, op_names)
    except Exception as e:
        return {"status": "error", "message": f"ops verify failed: {e}"}


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
        "(node <craftbot-root>/living-ui/tools/src/cli.ts ops|run|data <project_path> — ABSOLUTE path; call living_ui_usage(project_id) for the exact commands and the data schema) to "
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
    # While a DEV environment exists, ALL agent/verifier HTTP goes to it —
    # this action resolves the REAL app's port on its own, and without the
    # redirect a verifier would write test records straight into real user
    # data through this side door. With NO dev env, intent decides: mid-arc
    # (factory machine non-terminal — a code change is being built) a
    # mutating call is agent test traffic and is refused toward the dev env;
    # arc closed (machine terminal) it is normal OPERATION of the app — the
    # write IS user data ("add this lead for me") and belongs in the live
    # app. Refusing those too routed real records into the disposable dev
    # copy, where the promote destroys them (observed live 2026-08-05, RBS
    # Leads Tracker).
    _dev_url = None
    _mid_arc = False
    try:
        from app.factory.host_craftbot import get_factory_host as _gfh

        _rec = _gfh().get_staging_record(project_id)
        if _rec and _rec.get("url"):
            _dev_url = str(_rec["url"])
        _machine = _gfh().machine_for(project_id)
        _mid_arc = _machine is not None and not _machine.terminal
    except Exception:
        _dev_url = None

    if _dev_url is None and _mid_arc and method != "GET":
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": (
                f"A code change is in progress for project '{project_id}' — "
                "its live data is real user data, and agent test writes "
                "outside the dev environment are refused. For the code "
                "change, call living_ui_notify_ready first (it boots the dev "
                "env), then retry against it. If you meant to store REAL "
                "data the user asked for, wait until the change arc finishes "
                "— live data writes resume then."
            ),
        }

    if _dev_url is None and project.status != "running":
        return {
            "status": "error",
            "status_code": 0,
            "response_headers": {},
            "body": "",
            "final_url": "",
            "elapsed_ms": 0,
            "message": f"Project '{project_id}' is not running (status: {project.status}). Launch it first.",
        }

    base_url = _dev_url or (project.backend_url if target == "backend" else project.url)
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
        if resp.status_code in (401, 403):
            # Observed live 2026-08-05: the chat agent probed the superuser-only
            # /api/collections, read the 401 as "the app's API is closed", and
            # downgraded a data-import request to a CSV file. The recovery path
            # must ride in the error itself.
            out["message"] += (
                " — this action sends no auth, and PocketBase admin endpoints "
                "(e.g. /api/collections) are superuser-only on every app, even "
                "authMode 'none'. Do not conclude the app's data is locked: "
                "use the lui CLI instead — call living_ui_usage(project_id) "
                "for the exact run_shell commands, or target the app's record "
                "endpoints (/api/collections/<name>/records)."
            )
        if parsed_json is not None:
            out["response_json"] = parsed_json

        # If the agent just mutated the Living UI's data, tell the browser so the
        # iframe reloads to show fresh state. The frontend debounces these so a
        # burst of writes only triggers one reload. Dev-env writes hit the
        # disposable copy — the user's iframe shows the LIVE app, so a reload
        # would be noise about data it can't even see.
        if (
            resp.ok
            and method in {"POST", "PUT", "PATCH", "DELETE"}
            and _dev_url is None
        ):
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


@action(
    name="living_ui_usage",
    description=(
        "Get the operating manual for a Living UI project: its path, data "
        "schema, and the exact lui CLI commands (run via run_shell) to read/"
        "write its data and run its operations. Call this FIRST whenever a "
        "chat request involves an existing Living UI's data (add/change/"
        "fetch records) — the manual is not in your prompt outside the "
        "project's own session."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=True,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "84d93cca",
            "description": "The Living UI project ID (living_ui_list_projects resolves names to ids).",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "usage": {
            "type": "string",
            "description": "Project path, data model, and CLI commands to operate the app.",
        },
        "message": {"type": "string", "example": ""},
    },
    test_payload={"project_id": "test123", "simulated_mode": True},
)
def living_ui_usage(input_data: dict) -> dict:
    """Return the same operating note the project's dedicated session gets."""
    if input_data.get("simulated_mode", False):
        return {
            "status": "success",
            "usage": "[INTERACTING WITH LIVING UI: test123]",
            "message": "",
        }

    project_id = str(input_data.get("project_id", "")).strip()
    if not project_id:
        return {"status": "error", "usage": "", "message": "project_id is required."}

    try:
        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager or not manager.get_project(project_id):
            return {
                "status": "error",
                "usage": "",
                "message": (
                    f"Project '{project_id}' not found. Use "
                    "living_ui_list_projects to resolve the id."
                ),
            }

        from app.agent_base import AgentBase

        return {
            "status": "success",
            "usage": AgentBase._build_living_ui_note(project_id),
            "message": "",
        }
    except Exception as e:
        return {
            "status": "error",
            "usage": "",
            "message": f"Failed to build usage note: {e}",
        }


@action(
    name="living_ui_marketplace_list",
    description=(
        "List the Living UI marketplace catalogue: pre-built apps the user "
        "can install by id. Use when the user asks what apps are available "
        "or wants to install something by name (list first to resolve the id)."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=True,
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "apps": {
            "type": "array",
            "example": [
                {
                    "id": "kanban-board",
                    "name": "Kanban Board",
                    "description": "Tasks in columns",
                }
            ],
            "description": "Catalogue entries (id, name, description, ...).",
        },
        "message": {"type": "string", "description": "Summary line."},
    },
    test_payload={"simulated_mode": True},
)
async def living_ui_marketplace_list(input_data: dict) -> dict:
    """Fetch the marketplace catalogue (GitHub-hosted JSON)."""
    if input_data.get("simulated_mode"):
        return {"status": "success", "apps": [], "message": "0 apps (simulated)."}
    import asyncio
    import json as _json
    import re as _re
    import ssl
    import urllib.request

    CATALOGUE_URL = (
        "https://raw.githubusercontent.com/CraftOS-dev/"
        "living-ui-marketplace/main/catalogue.json"
    )

    def _fetch() -> dict:
        try:
            import certifi

            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(CATALOGUE_URL, headers={"User-Agent": "CraftBot"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            raw = r.read().decode()
        # Tolerate trailing commas in hand-edited JSON.
        return _json.loads(_re.sub(r",\s*([}\]])", r"\1", raw))

    try:
        catalogue = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        apps = catalogue.get("apps", [])
        return {
            "status": "success",
            "apps": apps,
            "message": (
                f"{len(apps)} marketplace app(s) available. Install with "
                'living_ui_marketplace_install(app_id="<id>").'
            ),
        }
    except Exception as e:
        return {
            "status": "error",
            "apps": [],
            "message": f"Could not fetch catalogue: {e}",
        }


@action(
    name="living_ui_approve_triggers",
    description=(
        "Approve a Living UI app's declared agent triggers (its triggers.json "
        "— requests the app may fire at the agent). Call this ONLY after the "
        "user has explicitly agreed to the listed triggers in chat: it is the "
        "user's consent being recorded, not yours to infer. Apps built here "
        "are pre-approved; this is for marketplace/imported apps, whose fires "
        "are refused until approved."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    input_schema={
        "project_id": {
            "type": "string",
            "example": "84d93cca",
            "description": "The Living UI project whose triggers the user approved.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "approved": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The trigger names now allowed to fire.",
        },
        "message": {"type": "string", "example": ""},
    },
    test_payload={"project_id": "test123", "simulated_mode": True},
)
def living_ui_approve_triggers(input_data: dict) -> dict:
    """Record the user's consent for an app's declared agent triggers."""
    if input_data.get("simulated_mode", False):
        return {"status": "success", "approved": ["restock_needed"], "message": ""}

    project_id = str(input_data.get("project_id", "")).strip()
    if not project_id:
        return {"status": "error", "approved": [], "message": "project_id is required."}

    try:
        import json as _json
        from pathlib import Path

        from app.living_ui import get_living_ui_manager

        manager = get_living_ui_manager()
        project = manager.get_project(project_id) if manager else None
        if project is None:
            return {
                "status": "error",
                "approved": [],
                "message": f"Project '{project_id}' not found.",
            }

        try:
            declared = (
                _json.loads(
                    (Path(project.path) / "triggers.json").read_text(encoding="utf-8")
                ).get("triggers")
                or {}
            )
        except FileNotFoundError:
            declared = {}
        except Exception as e:
            return {
                "status": "error",
                "approved": [],
                "message": f"triggers.json unreadable: {e}",
            }
        if not declared:
            return {
                "status": "error",
                "approved": [],
                "message": (
                    "This app declares no triggers — nothing to approve. "
                    "(Approval is per-app and covers its triggers.json.)"
                ),
            }

        from app.factory.host_craftbot import get_factory_host

        get_factory_host().set_triggers_approved(project_id)
        names = sorted(declared.keys())
        return {
            "status": "success",
            "approved": names,
            "message": (
                f"Approved {len(names)} trigger(s) for '{project.name}': "
                + ", ".join(names)
                + ". Fires now reach the agent (the app's own cooldowns and "
                "rate caps still apply)."
            ),
        }
    except Exception as e:
        return {"status": "error", "approved": [], "message": f"Approval failed: {e}"}


@action(
    name="living_ui_marketplace_install",
    description=(
        "Install a pre-built Living UI app from the marketplace by id "
        "(resolve ids with living_ui_marketplace_list). Downloads the app, "
        "registers it as a project, and runs the full launch pipeline. "
        "Inside a Living UI build session, the install ADOPTS the current "
        "project (same tab/id/port) instead of creating a duplicate. "
        "Pass will_adapt=true when the requirements say the installed app "
        "must be adapted afterwards. Marketplace apps are pre-built — no "
        "walk-verify needed for an as-is install; the system announces it."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    irreversible=True,
    input_schema={
        "app_id": {
            "type": "string",
            "example": "kanban-board",
            "description": "The app id from the marketplace catalogue.",
        },
        "name": {
            "type": "string",
            "example": "My Kanban",
            "description": "Optional display name (defaults to the catalogue name/app id).",
        },
        "description": {
            "type": "string",
            "example": "Team task board",
            "description": "Optional project description.",
        },
        "will_adapt": {
            "type": "boolean",
            "example": False,
            "description": (
                "True when the requirements demand adaptations AFTER the "
                "install (MARKETPLACE DECISION ... adapt: yes) — the build "
                "then continues with the modify flow instead of completing."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "message": {
            "type": "string",
            "description": "Outcome with the app URL on success.",
        },
        "project_id": {
            "type": "string",
            "description": "The new project id on success.",
        },
    },
    test_payload={"app_id": "test-app", "simulated_mode": True},
)
async def living_ui_marketplace_install(input_data: dict) -> dict:
    """Download, register and launch a marketplace app."""
    app_id = (input_data.get("app_id") or "").strip()
    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "project_id": "abc12345",
            "message": f"Installed '{app_id}' at http://localhost:3100 (simulated).",
        }
    if not app_id:
        return {"status": "error", "message": "app_id is required"}

    try:
        from app.living_ui import (
            broadcast_living_ui_created,
            broadcast_living_ui_ready,
            get_living_ui_manager,
        )

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not initialized."}

        will_adapt = bool(input_data.get("will_adapt"))

        # ADOPT the current build session's project instead of minting a
        # duplicate: a wizard-created project already owns the tab, port and
        # session this run lives in. Only undelivered scaffolds are adopted
        # — a project with a live database (or an already-installed
        # marketplace app) means the user is installing a separate new app,
        # which stays a fresh project. (Observed live 2026-08-05: installing
        # without adoption left an orphan project whose factory machine
        # redispatched a from-scratch build of the same app.)
        adopt_id = None
        _sid = str(input_data.get("_session_id") or "")
        if _sid.startswith("lui_"):
            _candidate = _sid[4:]
            _proj = manager.get_project(_candidate)
            if _proj is not None and _proj.path:
                _delivered = False
                try:
                    import json as _json2
                    from pathlib import Path as _P2

                    from app.living_ui.lifecycle import live_db_exists as _lde

                    _delivered = _lde(_proj.path)
                    if not _delivered:
                        _mf2 = _json2.loads(
                            (_P2(str(_proj.path)) / "manifest.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        _delivered = bool(_mf2.get("marketplaceAppId"))
                except Exception:
                    _delivered = False
                if not _delivered:
                    adopt_id = _candidate
                else:
                    # IDEMPOTENCE: this project already holds an installed
                    # marketplace app. If it is the SAME app, a resumed run
                    # (crash between install and build completion → the
                    # factory redispatches "continue build") must not mint a
                    # duplicate through the fresh-install path — the work
                    # left is the adaptations, not another install.
                    try:
                        import json as _json
                        from pathlib import Path as _P

                        _mf = _json.loads(
                            (_P(str(_proj.path)) / "manifest.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        if _mf.get("marketplaceAppId") == app_id:
                            return {
                                "status": "success",
                                "project_id": _candidate,
                                "already_installed": True,
                                "message": (
                                    f"Marketplace app '{app_id}' is ALREADY "
                                    "installed in this project — do NOT "
                                    "install again. If reference/"
                                    "requirements.md lists adaptations, "
                                    "apply them now (edit → "
                                    "living_ui_notify_ready → "
                                    "living_ui_walk_verify); otherwise the "
                                    "app is done — end the run."
                                ),
                            }
                    except Exception:
                        pass

        result = await manager.install_from_marketplace(
            app_id=app_id,
            app_name=input_data.get("name") or app_id,
            app_description=input_data.get("description") or "",
            project_id=adopt_id,
        )
        if result.get("status") != "success":
            return {
                "status": "error",
                "message": result.get("error") or "Installation failed.",
            }

        project = result.get("project") or {}
        project_id = project.get("id", "")
        url = result.get("url") or project.get("url") or ""
        # Consent surfacing (spec TRIGGERS-PLAN): marketplace apps arrive
        # third-party — their declared agent triggers need the user's yes.
        _triggers_brief = ""
        try:
            _live = manager.get_project(project_id)
            if _live is not None:
                _triggers_brief = manager.declared_triggers_brief(_live)
        except Exception:
            _triggers_brief = ""
        # Surface it in the sidebar + viewport like the UI-driven install.
        try:
            await broadcast_living_ui_created(project)
            live = manager.get_project(project_id)
            if live is not None and live.port:
                await broadcast_living_ui_ready(project_id, url, live.port)
        except Exception:
            pass

        if adopt_id and not will_adapt:
            # As-is install completed THIS session's build: close the factory
            # arc so the machine announces and never redispatches a ghost
            # "continue build" for a project that is already done.
            try:
                from app.factory.host_craftbot import get_factory_host as _gfh2

                _gfh2().report_verify(
                    project_id,
                    "pass",
                    url=url,
                    verified=[],
                    caveat="Installed from the marketplace — pre-built and pre-verified.",
                )
            except Exception:
                pass
            return {
                "status": "success",
                "project_id": project_id,
                "message": (
                    f"Marketplace app '{app_id}' installed into this project "
                    f"and running at {url}. The system has announced it to "
                    "the user — do NOT send your own summary. End the run."
                    + _triggers_brief
                ),
            }
        if adopt_id and will_adapt:
            return {
                "status": "success",
                "project_id": project_id,
                "message": (
                    f"Marketplace app '{app_id}' installed into this project "
                    f"at {url}. NOT DONE: now apply ONLY the adaptations "
                    "listed in reference/requirements.md "
                    "(living_ui_notify_ready will boot your changes in the "
                    "dev environment), then living_ui_walk_verify to deploy "
                    "and announce. If the requirements list no concrete "
                    "adaptations, ask the user what to change with a final "
                    "send_message instead of guessing." + _triggers_brief
                ),
            }
        return {
            "status": "success",
            "project_id": project_id,
            "message": (
                f"Marketplace app '{app_id}' installed and running at {url}. "
                "Tell the user it is ready." + _triggers_brief
            ),
        }
    except Exception as e:
        return {"status": "error", "message": f"Install failed: {str(e)}"}


@action(
    name="living_ui_import_zip",
    description=(
        "Import a Living UI project from an exported ZIP file (round-trip "
        "with export): registers it as a NEW project with fresh identity and "
        "port, strips shipped credentials, and re-vendors the kit. The "
        "project is registered STOPPED — launch it with "
        "living_ui_notify_ready, then living_ui_walk_verify. Only Living "
        "UI exports are supported (foreign apps/repos are not)."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    irreversible=True,
    input_schema={
        "zip_path": {
            "type": "string",
            "example": "/Users/me/Downloads/my-app-export.zip",
            "description": "Absolute path to the exported Living UI ZIP.",
        },
        "name": {
            "type": "string",
            "example": "My Imported App",
            "description": "Optional display name (defaults to the export's name).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "project_id": {"type": "string", "description": "The new project id."},
        "project_path": {"type": "string", "description": "Absolute project path."},
        "message": {"type": "string", "description": "Next steps."},
    },
    test_payload={"zip_path": "/tmp/test.zip", "simulated_mode": True},
)
async def living_ui_import_zip(input_data: dict) -> dict:
    """Import an exported Living UI ZIP as a new registered project."""
    zip_path = (input_data.get("zip_path") or "").strip()
    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "project_id": "abc12345",
            "project_path": "/workspace/living_ui/imported_abc12345",
            "message": "Imported (simulated).",
        }
    if not zip_path:
        return {"status": "error", "message": "zip_path is required"}

    import os

    if not os.path.isfile(zip_path):
        return {"status": "error", "message": f"File not found: {zip_path}"}

    try:
        from app.living_ui import broadcast_living_ui_created, get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not initialized."}

        project = await manager.import_project_zip(
            zip_path, name=input_data.get("name")
        )
        try:
            await broadcast_living_ui_created(project.to_dict())
        except Exception:
            pass
        return {
            "status": "success",
            "project_id": project.id,
            "project_path": project.path,
            "message": (
                f"Imported as '{project.name}' ({project.id}) at {project.path}. "
                f'Now launch it: living_ui_notify_ready(project_id="{project.id}"), '
                f'then living_ui_walk_verify(project_id="{project.id}").'
            ),
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Import failed: {str(e)}"}


@action(
    name="living_ui_import",
    description=(
        "Import a Living UI project from ANY source: an exported ZIP "
        "file, a local folder path, or a git URL (GitHub downloads fast; "
        "other hosts are cloned depth-1). Registers it as a NEW delivered "
        "project with fresh identity and port, strips shipped credentials, "
        "re-vendors the kit, and queues a launch-and-verify run in the "
        "project's own session — you normally do NOT need to launch it "
        "yourself. Only Living UI projects import (a foreign app/repo is "
        "a REBUILD, not an import — say so instead of forcing it)."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    irreversible=True,
    input_schema={
        "source": {
            "type": "string",
            "example": "https://github.com/someone/my-lui-app",
            "description": ("A .zip path, a local project folder path, or a git URL."),
        },
        "name": {
            "type": "string",
            "example": "My Imported App",
            "description": "Optional display name (defaults to the app's name).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "project_id": {"type": "string", "description": "The new project id."},
        "project_path": {"type": "string", "description": "Absolute project path."},
        "message": {"type": "string", "description": "Outcome and what happens next."},
    },
    test_payload={"source": "/tmp/test.zip", "simulated_mode": True},
)
async def living_ui_import(input_data: dict) -> dict:
    """Import a Living UI project from zip/folder/git and queue its verify run."""
    source = (input_data.get("source") or "").strip()
    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "project_id": "abc12345",
            "project_path": "/workspace/living_ui/imported_abc12345",
            "message": "Imported (simulated).",
        }
    if not source:
        return {"status": "error", "message": "source is required"}

    try:
        from app.living_ui import broadcast_living_ui_created, get_living_ui_manager

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not initialized."}

        project = await manager.import_project_source(
            source, name=input_data.get("name")
        )
        try:
            await broadcast_living_ui_created(project.to_dict())
        except Exception:
            pass

        # The import is only DONE when the app runs and verifies — queue
        # that run in the project's own session (LIFECYCLE-PLAN Phase 4)
        # instead of hoping the current agent follows written instructions.
        # Foreign sources register as EXTERNAL projects and get the ADOPTION
        # brief (write the pipeline verbs, then launch+verify) — one
        # composer in the manager so this and the UI path never drift.
        _is_ext = getattr(project, "project_type", "native") == "external"
        _dispatched = None
        try:
            from app.triggers import TriggerSource as _TS

            _dispatched = await manager.start_development_run(
                project.id,
                brief=manager.post_import_brief(project),
                trigger_source=_TS.LIVING_UI_IMPORT,
                workflow_skill=(
                    "living-ui-importer" if _is_ext else "living-ui-modify"
                ),
                status=("creating" if _is_ext else None),
            )
        except Exception:
            _dispatched = None

        _what = (
            "Registered EXTERNAL app (runs as-is in its own runtime)"
            if _is_ext
            else "Imported"
        )
        _next = (
            (
                "An adoption run has been queued in its session — the agent "
                "is setting it up to run; the system will announce the "
                "result."
                if _is_ext
                else "A launch-and-verify run has been queued in its session "
                "— the system will announce the result; do not launch it "
                "yourself."
            )
            if _dispatched
            else (
                "Now finish it yourself following this brief:\n"
                + manager.post_import_brief(project)
            )
        )
        return {
            "status": "success",
            "project_id": project.id,
            "project_path": project.path,
            "message": (
                f"{_what}: '{project.name}' ({project.id}) at {project.path}. {_next}"
            ),
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Import failed: {str(e)}"}


@action(
    name="living_ui_convert",
    description=(
        "REBUILD a foreign (non-Living-UI) app as a Living UI: scaffolds a "
        "fresh Living UI project, ships the original source (zip / folder / git "
        "URL) as read-only reference material, synthesizes the requirements "
        "FROM that source, and dispatches the standard supervised build to "
        "the project's session. Use when the user wants an existing app "
        "'imported' but living_ui_import rejected it as not a Living UI — this is a "
        "full rebuild (only the behavior carries over, never the code) and "
        "costs a full build run; tell the user that before calling. For "
        "actual Living UI projects use living_ui_import instead."
    ),
    default=False,
    mode="CLI",
    action_sets=["living_ui"],
    parallelizable=False,
    irreversible=True,
    input_schema={
        "source": {
            "type": "string",
            "example": "https://github.com/someone/express-todo-app",
            "description": "A .zip path, a local folder path, or a git URL of the foreign app.",
        },
        "name": {
            "type": "string",
            "example": "My Todo Board",
            "description": "Optional display name (defaults to the repo/folder name).",
        },
        "description": {
            "type": "string",
            "example": "Keep the kanban view, skip the admin panel",
            "description": "Optional user note on what matters in the rebuild.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "project_id": {"type": "string", "description": "The new project id."},
        "project_path": {"type": "string", "description": "Absolute project path."},
        "message": {"type": "string", "description": "Outcome and what happens next."},
    },
    test_payload={"source": "/tmp/foreign-app", "simulated_mode": True},
)
async def living_ui_convert(input_data: dict) -> dict:
    """Scaffold + source-derived requirements + dispatch the supervised build."""
    source = (input_data.get("source") or "").strip()
    if input_data.get("simulated_mode"):
        return {
            "status": "success",
            "project_id": "abc12345",
            "project_path": "/workspace/living_ui/converted_abc12345",
            "message": "Conversion build dispatched (simulated).",
        }
    if not source:
        return {"status": "error", "message": "source is required"}

    try:
        from app.living_ui import (
            broadcast_living_ui_created,
            broadcast_living_ui_progress,
            get_living_ui_manager,
        )

        manager = get_living_ui_manager()
        if not manager:
            return {"status": "error", "message": "Living UI manager not initialized."}

        project = await manager.convert_foreign_source(
            source,
            name=input_data.get("name"),
            description=(input_data.get("description") or "").strip(),
        )
        try:
            await broadcast_living_ui_created(project.to_dict())
            await broadcast_living_ui_progress(
                project.id,
                "initializing",
                10,
                "Source analyzed — starting the rebuild...",
            )
        except Exception:
            pass

        # The conversion is a normal pre-delivery BUILD: classic instruction,
        # creator skill, full factory supervision, baseline data-safety.
        _dispatched = await manager.start_development_run(project.id)
        _next = (
            "The supervised rebuild has been dispatched to the project's "
            "session — progress appears in its tab and the system announces "
            "the result. Do not build it in this session."
            if _dispatched
            else (
                "The session runtime is not bound — the rebuild was NOT "
                "dispatched. Build it via the living-ui-creator workflow "
                "against reference/requirements.md."
            )
        )
        return {
            "status": "success",
            "project_id": project.id,
            "project_path": project.path,
            "message": (
                f"Converted source registered as '{project.name}' "
                f"({project.id}); requirements were synthesized from the "
                f"original code (reference/source/). {_next}"
            ),
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Conversion failed: {str(e)}"}
