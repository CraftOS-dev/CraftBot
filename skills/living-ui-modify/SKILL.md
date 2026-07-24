---
name: living-ui-modify
description: Modify an existing Living UI application (V2 — PocketBase + React kit) — add features, change design, fix bugs — then re-validate and relaunch it.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Modify (V2)

You are changing an EXISTING app. Everything in the living-ui-creator skill
applies (ownership rule, schema/verbs/UI order, kit usage, honesty rule) —
this skill covers only what differs.

## Step 0: Locate and understand

1. Find the project: read `agent_file_system/workspace/living_ui_projects.json`
   or use the project id/path given in your instruction.
2. Read the project's `LIVING_UI.md` (current plan/entities/ops) and
   `reference/requirements.md`. Read `manifest.json` for `authMode` and port.
3. If something broke, read the logs FIRST:
   `{project_path}/logs/frontend_console.log` and
   `{project_path}/logs/pocketbase.log`.
4. If the request is ambiguous, ask 1 batch of clarifying questions
   (a FINAL `send_message` (`continue_work=false` — the reply wakes the session)).

## Rules for changing a live app

- **Ownership is unchanged**: edit only `frontend/src/app/`, `pb/pb_migrations/`
  (NEW files only — never edit applied migrations), `pb/pb_hooks/ops.pb.js`
  (+ new `*.pb.js`), `operations.json` (non-system), `LIVING_UI.md`.
- **Schema changes are additive migrations.** The user's data lives in
  `pb/pb_data/` — never delete it, never drop-and-recreate collections that
  hold data. To alter a collection, write a new migration that loads and
  updates it (`app.findCollectionByNameOrId(...)` → modify → `app.save(...)`).
- **Relation fields need the target collection's ID** —
  `app.findCollectionByNameOrId('<name>').id`, never the name.
- Record the delta in `LIVING_UI.md` (what changed, new entities/ops).

## Finish

```
living_ui_notify_ready(project_id="<PROJECT_ID>")
```

Runs the gate (types, build, migrations-on-fresh-db, ops, ownership), restarts
the app, health-checks and smoke-verifies it. Fix ALL returned errors and call
again. HONESTY RULE: success only when it returns `status: success` — never
tell the user a change is live when the relaunch failed.
