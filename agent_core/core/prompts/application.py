# -*- coding: utf-8 -*-
"""
Application-specific prompt templates.

Contains prompt templates for Living UI and other application features.
"""

LIVING_UI_TASK_INSTRUCTION = """Create a Living UI application (V2 — PocketBase + React kit).

Project ID: {project_id}
Project Name: {project_name}
Description: {description}
Features: {features}
Theme: {theme}
Project Path: {project_path}

Follow the living-ui-creator skill. Workflow:

1. Read agent_file_system/GLOBAL_LIVING_UI.md — apply its colors, fonts, and rules
2. Read {project_path}/LIVING_UI.md (plan/index) and {project_path}/reference/requirements.md if present
3. QnA PHASE — MANDATORY unless the requirements are already detailed and
   unambiguous: ask the user 1-2 batches of clarifying questions (data to track,
   must-have features, design preferences, single- vs multi-user) using
   send_message as your FINAL message (continue_work=false — the reply wakes the session), ALWAYS passing the `options`
   param with quick-answer choices when the answer space is enumerable
   (they render as tap-to-answer chips on the creation screen). Write the agreed requirements to
   {project_path}/reference/requirements.md and mirror the feature checklist
   into LIVING_UI.md BEFORE any coding. Writing reference/requirements.md is
   MANDATORY — it is the binding spec for verification.
3b. This build IS substantial work — the standard run protocol applies as-is
   (scope, plan, execute, verify, deliver). Do not skip it because these
   numbered steps exist; they only describe the Living-UI-specific parts.
4. OWNERSHIP RULE (the gate enforces this by hashing):
   - You may edit ONLY: frontend/src/app/, pb/pb_migrations/, pb/pb_hooks/ (ops.pb.js
     and new *.pb.js files), operations.json (non-system entries), LIVING_UI.md
   - NEVER touch: frontend/src/kit/, frontend/src/main.tsx, frontend/src/config.gen.ts,
     pb/pb_hooks/_system.pb.js, manifest.json, vite/tsconfig files.
     Need a component variant? Wrap the kit component in frontend/src/app/ instead.
5. Build order per feature:
   - Schema: add a NEW migration in pb/pb_migrations/ (never edit an applied one);
     follow the starter migration's field/rule pattern and the project's authMode
   - Custom verbs (beyond CRUD): routerAdd route in pb/pb_hooks/ops.pb.js + a matching
     entry in operations.json (the gate fails orphan ops; see items.clear-done example)
   - UI: build in frontend/src/app/ from kit parts (import from '../kit/index.ts');
     data via useCollection (realtime — never poll or reload); writes via
     getPbClient().call(...) (errors toast automatically)
   - Update LIVING_UI.md — mark the feature done, record entities/ops/components
6. Quality bar: empty states with a next action, loading states, confirmation dialog
   for destructive actions, toasts on CRUD, responsive layout, kit tokens only
   (never hardcoded colors — theming is host-owned)
7. Call living_ui_notify_ready(project_id="{project_id}") — it runs the validation
   gate (types, build, migrations-on-fresh-db, ops structure, ownership) and launches.
   If it returns errors: read ALL of them, fix ALL of them, call it again.

RUN RULE: this run IS the build — there is no "continue in a later turn".
The ONLY valid ways this run ends: a question to the user (a FINAL
send_message, continue_work=false — the reply wakes the session) or
living_ui_notify_ready returning success. Never end_turn mid-build.

HONESTY RULE: the app is ready ONLY when living_ui_notify_ready returns
status=success. If you cannot make it pass, tell the user the build FAILED and
exactly what is blocking — NEVER claim the app is ready or usable when the
launch failed. A false "ready" is the worst possible outcome.

Schema gotcha: relation fields require the TARGET COLLECTION'S ID, not its
name — save the target collection first, then reference
app.findCollectionByNameOrId("<name>").id in the dependent collection.

Debugging: frontend runtime errors are relayed to {project_path}/logs/frontend_console.log;
the PocketBase server log is {project_path}/logs/pocketbase.log."""
