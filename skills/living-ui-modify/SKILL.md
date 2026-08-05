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
5. **Record the request in the spec BEFORE editing code**: append a dated
   entry to `reference/requirements.md` under a `## Changes` section (create
   the section if absent):
   `- 2026-08-05: <the user's request, stated as a checkable capability>`.
   NEVER rewrite the existing sections — they are the delivered contract;
   `## Changes` is append-only. The verifier checks every entry there, so an
   unrecorded change is an unverified change (and a recorded one can never
   be silently dropped by a later modify).

## Rules for changing a live app

- **Ownership is unchanged**: edit only `frontend/src/app/`, `pb/pb_migrations/`
  (NEW files only — never edit, rename, or delete an applied migration: the
  filename is its identity in the live DB, and a renamed one makes the app
  unable to boot), `pb/pb_hooks/ops.pb.js` (+ new `*.pb.js` / `*.js` helper
  modules), `operations.json` (non-system), `LIVING_UI.md`.
- **Schema changes are additive migrations.** The user's data lives in
  `pb/pb_data/` — never delete it, never drop-and-recreate collections that
  hold data. To alter a collection, write a new migration that loads and
  updates it (`app.findCollectionByNameOrId(...)` → modify → `app.save(...)`).
- **Relation fields need the target collection's ID** —
  `app.findCollectionByNameOrId('<name>').id`, never the name.
- Record the delta in `LIVING_UI.md` (what changed, new entities/ops).

## Finish

```
living_ui_notify_ready(project_id="<PROJECT_ID>")   # gate + boot STAGING copy
living_ui_walk_verify(project_id="<PROJECT_ID>")    # verify staging + DEPLOY
```

On a delivered app these run in **staging mode**: `notify_ready` gates and
boots a disposable COPY of the app (code + cloned data) on a hidden port —
the user's live app keeps running the previous version, untouched. Test
freely against the staging URL it returns: every record you create there is
thrown away. `walk_verify` drives the staging copy in a real (headless)
browser; a clean verdict is what DEPLOYS your change to the live app (new
migrations apply to the real data at boot) and announces it.

- **Never run `lui validate` or `lui dev` against the real project dir of a
  delivered app** — the build overwrites the served frontend in place and
  blanks the user's live UI. `notify_ready` gates the staging copy for you.
- **Never write test data to the live app** (its DB is the user's real
  data; writes outside staging are refused). Do all testing after
  `notify_ready`, against the staging URL.

HONESTY RULE: the change is live only when `living_ui_walk_verify` returns
`status: success` — never tell the user a change is live when the relaunch,
verification or deploy failed. On failure the user's app still runs the
previous working version.
