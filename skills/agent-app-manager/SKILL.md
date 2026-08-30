---
name: agent-app-manager
description: Manage and operate Agent App projects — list, inspect, launch, stop, restart, use their data/ops, and diagnose issues. No code changes.
action-sets:
  - core
  - file_operations
  - agent_app
---

# Agent App Manager

Operate and manage existing Agent Apps. **Never edit code here** — if a request
needs code changes, that's agent-app-modify.

## Inventory

- Registry: `agent_file_system/workspace/agent_app_projects.json` — id, name,
  status, port, path per project.
- Per project: `manifest.json` (port, authMode, pipeline), `AGENT_APP.md`
  (what it does), `operations.json` (its verbs).

## Lifecycle

- `agent_app_notify_ready(project_id)` — validate + launch (or relaunch).
- `agent_app_restart(project_id)` — stop then full relaunch.
- A running app serves everything on ONE port: `http://localhost:<port>` —
  the UI, the PB REST API (`/api/collections/...`), declared ops, and
  discovery at `GET /api/_ops`.

## Operating an app (using it on the user's behalf)

Use the **`lui` CLI via run_shell**. ALWAYS use the ABSOLUTE CLI path —
the shell's cwd is NOT the repo root, so relative paths fail. The CLI is
`<craftbot-root>/agent-app/tools/src/cli.ts` (craftbot-root = parent of
`agent_file_system`; in a Agent App session the [INTERACTING WITH AGENT APP]
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

Fallback only when the shell is unavailable: the `agent_app_http` action
speaks to the same API.

## Diagnosing

- Status `error`: read the project's `error` field in the registry, then
  `logs/pocketbase.log` (server/migrations) and `logs/frontend_console.log`
  (frontend). Report findings honestly; hand fixes to agent-app-modify.
- Never start `pocketbase`/`npm` processes by hand; never touch `pb_data/`
  or `.superuser`.
