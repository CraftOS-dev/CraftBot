---
name: living-ui-manager
description: Operate existing Living UI apps - populate/add/update/query their data (kanban cards, tracker entries, CRM records, board lists), fire their operations, run jobs, observe their UI. Everything goes through the livingui CLI in run_shell - discover with --help.
action-sets:
  - core
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Manager

Operate existing Living UI applications **through the `livingui` CLI**, the
way a human uses a well-made command-line tool: `--help` to discover, then
navigate. Invoke it with `run_shell` — `livingui` is on PATH inside
CraftBot's shell actions, so run it directly:

```
livingui ls
```

(If `livingui` is ever not recognized, the launcher is at
`<workspace>/bin/livingui.cmd` — but the bare command is the normal form.)

## The operating loop

```
livingui ls                       → find the project (id, name, status)
livingui <project> --help         → capability card: tables, operations, commands
livingui <project> <command> ...  → do the work
```

**Rule 1 — discover with --help, level by level.** Help exists at every
level (`<project> --help`, `<command> --help`, `run <op> --help`). Never dump
everything at once; dive only into what the task needs. Never read
models.py/routes.py/LIVING_UI.md for data operations — `--help` and `schema`
are live ground truth.

**Rule 2 — errors ARE instructions.** When a command fails, the error ends
with `Try: livingui ...` — run exactly that. Do not guess an alternative
route or start editing code because one command failed.

**Rule 3 — always batch.** One `insert --file` with 100 rows, one filtered
`update`, one `sql` aggregate. NEVER loop one-record commands.

`<project>` accepts the id (`e1e957e1`), the name (`habit-tracker`), or the
folder name — all resolve.

## Command reference (each supports --help)

### Read

```
livingui habit-tracker schema                      # tables + row counts
livingui habit-tracker schema workout_logs         # columns of one table
livingui habit-tracker select workout_logs --where "date>=2026-07-01" --columns date,exercise --limit 20
livingui habit-tracker count habits --where "archived=false"
livingui habit-tracker sql "SELECT exercise, COUNT(*) n FROM workout_logs GROUP BY 1 ORDER BY n DESC"
```

`--where` (repeatable, AND): `"id<=10"`, `"name like %press%"`,
`"status in todo,doing"`, `"deleted_at is null"`.

### Write (direct DB — works even when the app is stopped)

```
# BULK insert: write rows.json (a JSON array) with a file action, then ONE command
livingui habit-tracker insert workout_logs --file C:\...\rows.json

# Filtered bulk update/delete — the data never enters your context
livingui habit-tracker update workout_logs --where "id<=10" --set rpe=7.5 --set rest_time_seconds=90
livingui habit-tracker delete workout_logs --where "id>95"
```

update/delete **require `--where`** (or explicit `--all` for whole-table).
Destructive commands snapshot the DB first. Mutations auto-refresh the
user's iframe.

### App behavior (the app's verbs — prefer these over raw DB writes)

```
livingui habit-tracker run                          # list declared operations
livingui habit-tracker run complete_habit --help    # params for one op
livingui habit-tracker run archive_habit --habit_id 3        # bare scalars: inline is fine
livingui habit-tracker run add_card --params-file params.json # ANY text value: use a file
livingui habit-tracker api GET /api/dashboard       # raw endpoint passthrough
```

**Params rule (Windows-proof):** the moment any param value contains spaces
or punctuation (titles, descriptions, notes), do NOT quote it inline —
write the params as a JSON object to a file with a file action, then pass
`--params-file <path>`. Inline `--param value` is only for bare scalars.

**If an operation exists for the intent, use it** — ops run the app's real
logic (validation, ordering, side effects). Use raw `update`/`sql --write`
only for pure data work.

### Long-running work

`mode: job` ops return a job id immediately — never block on them:

```
livingui video-editor run render_timeline --preset final   → "job 3f2a91c0 started"
livingui video-editor job 3f2a91c0                         → status + log tail
livingui video-editor job 3f2a91c0 --cancel
```

### Schema changes & lifecycle

```
livingui habit-tracker migrate      # apply additive schema migration NOW
livingui habit-tracker restart      # full pipeline (migrates automatically first)
livingui habit-tracker start | stop
```

After ANY models.py edit: `restart` (or `migrate` for the DB alone) BEFORE
seeding data into new columns/tables. `--help` warns about schema drift and
prints the fix.

### Observe

```
livingui habit-tracker status | logs --tail 50 | snapshot
livingui habit-tracker screenshot --out shot.png    # then describe_image
livingui habit-tracker ui --data '{"type": "refresh"}'   # drive the live iframe
```

## If no capability exists

When `--help` shows no operation, no endpoint, and no table that fits, the
app needs code. Read `backend/routes.py` / `backend/models.py`, add the
capability following existing patterns (with a one-line docstring — it
becomes the op description), update `LIVING_UI.md`, then
`livingui <project> restart`. New model columns are migrated automatically
at restart. Then register the capability: `livingui <project> ops-sync
--write`, curate the description, `ops-check` until clean — an undeclared
capability is invisible.

## Rules

- **Before You Start**: read `agent_file_system/GLOBAL_LIVING_UI.md`; per-project
  `LIVING_UI.md` overrides it for design decisions.
- **The CLI is the ONLY way to operate a Living UI** — `--help` → command →
  follow error hints. No curl, no direct sqlite, no HTTP actions.
- **If a livingui command fails, fix the invocation — NEVER bypass the CLI.**
  A quoting failure means switch to `--params-file`; an unknown column means
  run the suggested `migrate`. Falling back to direct sqlite3/python scripts
  against living_ui.db is forbidden (and blocked): it corrupts ordering,
  bypasses app logic, and skips automatic backups.
- **NEVER write auth tables directly** (`users`, `memberships`, `invites`) —
  password hashing lives in the app; use `api POST /api/auth/...`.
- **NEVER start servers manually** (`npm`, `uvicorn`) — use `restart`.
- **Quote Windows paths**; put bulk payloads in files, not on the command line.
- **Format results for the user** — tables, lists, summaries; don't paste raw CLI dumps.
- **Don't create a Living UI here** — use `living-ui-creator`.
