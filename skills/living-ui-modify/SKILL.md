---
name: living-ui-modify
description: Modify an existing Living UI application (PocketBase + React kit) — add features, change design, fix bugs — then re-validate and relaunch it.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Modify

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
5. **Record the request in the spec BEFORE editing code**: append a dated
   entry to `reference/requirements.md` under a `## Changes` section (create
   the section if absent):
   `- 2026-08-05: <the user's request, stated as a checkable capability>`.
   NEVER rewrite the existing sections — they are the delivered contract;
   `## Changes` is append-only. The verifier checks every entry there, so an
   unrecorded change is an unverified change (and a recorded one can never
   be silently dropped by a later modify).
   **SUPERSESSION — the one permitted edit to old entries**: when the new
   request REVERSES or REPLACES an earlier `## Changes` entry (the user
   changed their mind, or the old entry demanded an approach the platform
   now rejects), wrap the stale entry in `~~strikethrough~~` — do not delete
   it (it stays as history) and do not leave it live (the verifier enforces
   every unstruck line, and contradictory live entries make the spec
   unsatisfiable: an app once went STUCK three times because old entries
   demanded a handler the validation gate forbids while the new entry
   forbade it — no code could satisfy both). Strike ONLY entries the new
   request genuinely contradicts, never entries you merely failed to build.

## Rules for changing a live app

- **Ownership is unchanged**: edit only `frontend/src/app/`, `pb/pb_migrations/`
  (NEW files only — never edit, rename, or delete an applied migration: the
  filename is its identity in the live DB, and a renamed one makes the app
  unable to boot), `pb/pb_hooks/ops.pb.js` (+ new `*.pb.js` / `*.js` helper
  modules), `operations.json` (non-system), `triggers.json`, `LIVING_UI.md`.
  Adding/changing an agent trigger (app fires the agent): declare it in
  `triggers.json` first — see the creator skill's `references/TRIGGERS.md`;
  the gate re-derives `capabilities.triggers` on relaunch, and fires of
  undeclared names are refused in-app.
- **Schema changes are additive migrations.** The user's data lives in
  `pb/pb_data/` — never delete it, never drop-and-recreate collections that
  hold data. To alter a collection, write a new migration that loads and
  updates it (`app.findCollectionByNameOrId(...)` → modify → `app.save(...)`).
- **Relation fields need the target collection's ID** —
  `app.findCollectionByNameOrId('<name>').id`, never the name.
- Record the delta in `LIVING_UI.md` (what changed, new entities/ops).

## Finish

```
living_ui_notify_ready(project_id="<PROJECT_ID>")   # gate + boot DEV env
living_ui_walk_verify(project_id="<PROJECT_ID>")    # verify dev + PROMOTE
```

These run in the **dev environment**: `notify_ready` gates and boots a
disposable copy of your new CODE on a hidden port with a **FRESH, EMPTY
database** — migrations replay at boot, so only data your migrations seed
exists. The user's live app keeps running the previous version, untouched,
and its data is NEVER cloned into dev. Test freely against the dev URL it
returns (create whatever test records you need — they are thrown away).
`walk_verify` drives the dev instance in a real (headless) browser; a clean
verdict is what PROMOTES your change to the live app (new migrations apply
to the real data at its boot) and announces it.

- **The dev DB starts empty every time.** If a feature needs data to be
  visible, either seed it in a migration (survives promote) or create test
  records through the app/API after `notify_ready` (dev-only, disposable).
- **Never run `lui validate` or `lui dev` against the real project dir** —
  the build overwrites the served frontend in place and blanks the user's
  live UI. `notify_ready` gates the dev copy for you.
- **Never write test data to the live app** (its DB is the user's real
  data; agent test writes outside the dev env are refused). Do all testing
  after `notify_ready`, against the dev URL. `GET /api/_a2app` answers
  `env: "dev"` or `env: "live"` if you need to confirm which instance a
  port is.

HONESTY RULE: the change is live only when `living_ui_walk_verify` returns
`status: success` — never tell the user a change is live when the relaunch,
verification or deploy failed. On failure the user's app still runs the
previous working version.
