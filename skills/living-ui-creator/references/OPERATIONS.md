# Operations Manifest (config/operations.json)

Every Living UI declares its **verbs** — the named, typed operations an agent
can fire — in `config/operations.json`. **Declared ops are the app's CLI
subcommands**: they appear in `livingui <project> --help` and run as
`livingui <project> run <op> --param value` (or `--params-file params.json`
for values with spaces/punctuation) — the ONLY way agents operate
Living UIs. This is how a future agent (or a different session) discovers
what the app can DO without reading source code — an undeclared capability
is invisible.

**Rule: every side-effectful capability gets a declared op.** Plain CRUD is
already covered by the built-in `data.*` ops — do not declare ops for it.
Declare ops for behavior: "render", "publish", "recalculate", "make_move",
"sync_to_shopify", "rebuild_site".

## File format

```json
{
  "operations": {
    "<op_name>": {
      "description": "One line: what this does and when to use it",
      "params": { ... },
      "executor": { ... },
      "mode": "sync" | "job",
      "safe": true
    }
  }
}
```

- `op_name`: lowercase declared-name, optionally namespaced with the app domain
  (`render_timeline`, `game.make_move`). MUST NOT start with the reserved
  prefixes `data.` `sql.` `http.` `job.` `ui.` `app.` (owned by built-ins).
- `mode`: `sync` (default) runs to completion; `job` (shell executors only)
  spawns detached with logged output and returns a `job_id` — the agent polls
  with the built-in `job.status` op. Use `job` for anything that can exceed
  ~60 seconds (renders, exports, builds).
- `safe`: mark `true` on READ-ONLY ops (status, list, report). Validation
  executes every safe op end-to-end to prove the control surface works — for
  imported external apps at least one safe op is REQUIRED, and its defaults
  must satisfy its params. NEVER mark an op with side effects as safe.

## Params

Shorthand or full form:

```json
"params": {
  "scene":  "string",                                       // required string
  "frame":  "int?",                                         // optional int
  "preset": {"enum": ["draft", "final"], "default": "draft"},
  "notes":  {"type": "string", "required": false, "description": "..."}
}
```

Types: `string`, `int`, `number`, `bool`, `object`, `array`. A param with a
`default` is implicitly optional. Params are validated BEFORE execution;
mismatches return a precise error naming the parameter.

## Executors

### http — call a backend endpoint (most common)

```json
"executor": {"type": "http", "method": "PUT", "path": "/api/custom/habits/{habit_id}/entry",
             "body": {"source": "agent"}}
```

- `{param}` placeholders in `path` are filled from params (URL-quoted) and
  removed from the payload.
- Remaining params become the JSON body (or query params for GET/DELETE),
  merged over the optional static `body` object.
- The endpoint runs the app's real business logic — validation, side effects,
  ordering. **Anything with side effects beyond a single table MUST use an
  http executor** so the logic lives in the app, not the manifest.

### sql — a parameterized statement (simple, logic-free data verbs)

```json
"executor": {"type": "sql", "sql": "UPDATE tasks SET status='archived' WHERE completed_at < :cutoff", "mode": "write"}
```

Params bind as `:named` parameters — never string-substituted. `"mode": "write"`
snapshots the database first. Use only for pure data transformations.

### shell — a declared command run in the project directory

```json
"executor": {
  "type": "shell",
  "cmd": "cli-anything-blender render {scene} --output renders/ --format PNG",
  "cwd": "assets",
  "timeout": 300,
  "env": {"BLENDER_THREADS": "4"}
}
```

- `{param}` placeholders are filled from validated params. Values containing
  shell metacharacters (quotes, `$`, `%`, `;`, `&`, `|`, `<`, `>`, backticks,
  newlines) are **rejected** — the declared command is the cage; params fill
  blanks, they can never extend the command.
- `cwd` is relative to the project directory and may not escape it.
- Combine with `"mode": "job"` for long-running work (renders, builds).
- Prefer `cli-anything-<app>` harness commands for desktop apps (Blender,
  LibreOffice, ffmpeg) — they resolve the app cross-platform.

## Examples by app type

**Kanban** (side-effectful move — ordering logic lives in the endpoint):
```json
"move_card": {
  "description": "Move a card to a column, reordering neighbors",
  "params": {"card_id": "string", "column": "string", "position": "int?"},
  "executor": {"type": "http", "method": "POST", "path": "/api/custom/cards/move"}
}
```

**Video editor** (long-running shell job):
```json
"render_timeline": {
  "description": "Render the timeline to MP4 (minutes — poll job.status)",
  "params": {"preset": {"enum": ["draft", "final"], "default": "draft"}},
  "executor": {"type": "shell", "cmd": "python scripts/render.py --preset {preset}"},
  "mode": "job"
}
```

**Game** (agent plays through the app's rules engine):
```json
"make_move": {
  "description": "Make a move; returns the new game state",
  "params": {"from": "string", "to": "string"},
  "executor": {"type": "http", "method": "POST", "path": "/api/custom/game/move"}
}
```

## Tooling: generate, don't hand-author

```
livingui <project> ops-sync            # preview ops generated from the running backend's routes
livingui <project> ops-sync --write    # merge them into operations.json (never touches existing ops)
livingui <project> ops-check           # validate: dead routes, missing path params, broken
                                       # shell templates, placeholder descriptions, coverage
```

`ops-sync` derives ops from the backend's routes where it can — but
custom pb_hooks endpoints are plain JS (`routerAdd`), with no typed
schemas to read: declare each op's `params` yourself (the hook validates
them by hand) and write descriptions worth reading. Non-CRUD routes
that should NOT be ops go in the manifest's top-level `"ignore_routes"`
list (e.g. `"ignore_routes": ["POST /api/custom/internal-recalc"]`) so the
decision is explicit and `ops-check` stays clean. The launch pipeline runs
the same checks: errors block, coverage gaps warn.

The three examples above (kanban / video editor / game) are the archetypes:
http executor for endpoint-backed verbs, shell+job for long-running work,
http for rules-engine moves.

## Maintenance rules

- When you ADD a capability to the app (new endpoint, new script), register
  it here in the same change — an undeclared capability is invisible.
- When you REMOVE or rename an endpoint, update or delete its op.
- Keep `description` accurate — the agent chooses ops by reading it.
- Document the op briefly in LIVING_UI.md's capability section too, but this
  file is the machine-read source of truth.

## Scheduled Operations

Any op may declare a `"schedule"` — the platform runs it automatically
while the app is running:

```json
"daily_digest": {
  "description": "Email the user a summary of open tasks every morning.",
  "params": {},
  "executor": {"type": "http", "method": "POST", "path": "/api/custom/digest/send"},
  "mode": "sync",
  "schedule": "daily 09:00"
}
```

Supported: `"every 15m"`, `"every 2h"`, `"hourly"`, `"daily HH:MM"`
(local time). Scheduled runs pass NO params — every required param needs
a default. Results append to `logs/schedule.log`; last-run state is
`logs/schedule_state.json` (both readable when debugging "did it fire?").
The op also stays manually runnable via `livingui <project> run <op>`.
