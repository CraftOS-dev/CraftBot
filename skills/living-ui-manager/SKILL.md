---
name: living-ui-manager
description: Manage and operate Living UI projects (V2) — list, inspect, launch, stop, restart, use their data/ops, and diagnose issues. No code changes.
action-sets:
  - core
  - file_operations
  - living_ui
---

# Living UI Manager (V2)

Operate and manage existing Living UIs. **Never edit code here** — if a request
needs code changes, that's living-ui-modify.

## Inventory

- Registry: `agent_file_system/workspace/living_ui_projects.json` — id, name,
  status, port, path per project.
- Per project: `manifest.json` (port, authMode, pipeline), `LIVING_UI.md`
  (what it does), `operations.json` (its verbs).

## Lifecycle

- `living_ui_notify_ready(project_id)` — validate + launch (or relaunch).
- `living_ui_restart(project_id)` — stop then full relaunch.
- A running app serves everything on ONE port: `http://localhost:<port>` —
  the UI, the PB REST API (`/api/collections/...`), declared ops, and
  discovery at `GET /api/_ops`.

## Operating an app (using it on the user's behalf)

Use the **`lui` CLI via run_shell**. ALWAYS use the ABSOLUTE CLI path —
the shell's cwd is NOT the repo root, so relative paths fail. The CLI is
`<craftbot-root>/living-ui-v2/tools/src/cli.ts` (craftbot-root = parent of
`agent_file_system`; in a Living UI session the [INTERACTING WITH LIVING UI]
note contains the exact ready-to-run commands). `<CLI>` and `<project>` below
are absolute paths.

1. Discover what the app can do:
   `node <CLI> ops <project>`
2. Declared op exists → run it:
   `node <CLI> run <project> <op-name> --param value`
   Ops marked `DESTRUCTIVE` → confirm with the user first.
3. No op → generic data access:
   `node <CLI> data <project> <collection> list --filter '...' --sort '-created' --limit 20`
   `node <CLI> data <project> <collection> create --json '{"field":"value"}'`
   `node <CLI> data <project> <collection> update <id> --json '{...}'` / `delete <id>`
   Read freely; write only what the app's own UI offers.
4. Needs new capability → say so and offer a modification instead of hacking
   around it.

Fallback only when the shell is unavailable: the `living_ui_http` action
speaks to the same API.

## Diagnosing

- Status `error`: read the project's `error` field in the registry, then
  `logs/pocketbase.log` (server/migrations) and `logs/frontend_console.log`
  (frontend). Report findings honestly; hand fixes to living-ui-modify.
- Never start `pocketbase`/`npm` processes by hand; never touch `pb_data/`
  or `.superuser`.
