---
name: living-ui-importer
description: Import external apps (Go, Node.js, Python, Rust, Docker, static sites) as Living UI projects. Detects app type, generates launch configuration, and registers the app.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Importer

Import any external app into CraftBot's Living UI system. The app gets lifecycle management (start/stop/restart), health monitoring, logging, and agent observation.

## Workflow

1. **Detect** — Analyze the app source to determine runtime, build, and start commands
2. **Configure** — Generate the launch configuration; find where the app
   stores its data (`data_config`)
3. **Import** — Call `living_ui_import_external` to register the project
4. **Document** — Create LIVING_UI.md describing the app
5. **Construct the CLI** — Create config/operations.json (+ wrapper scripts if
   needed) so the app is fully operable via `livingui`; mark read-only ops
   `"safe": true`
6. **Launch** — Run `living_ui_validate` until it passes, then
   `living_ui_notify_ready`. Validation ENFORCES steps 4–5: it refuses the
   import unless LIVING_UI.md exists, operations are declared, and every op
   marked `"safe": true` executes successfully against the running app
   (at least one is required).

What the platform gives every imported app for free (via the sidecar proxy —
never modify the app's source for these): `livingui <project> snapshot` /
`screenshot` (UI observation), frontend console capture to
`logs/frontend_console.log`, health checks, lifecycle (`status/logs/restart`),
and `api` passthrough. Your job is ONLY the parts that need code
understanding: the ops manifest, the data declaration, and the docs.

## Step 1: Detect App Type

Read the root directory of the app and identify the runtime by checking for these files.

**IMPORTANT: Always prefer native builds over Docker.** Docker adds complexity (daemon dependency, container lifecycle, port mapping, line endings). Only use Docker as a last resort when no native toolchain is available.

**Priority order** (check top to bottom, use the FIRST match):

| File Found | Runtime | Install Command | Start Command |
|---|---|---|---|
| `go.mod` | go | `go build -o app .` | `./app` |
| `package.json` | node | `npm install` | Read `scripts.start` from package.json |
| `requirements.txt` + `manage.py` | python (Django) | `pip install -r requirements.txt` | `python manage.py runserver 0.0.0.0:{{PORT}}` |
| `requirements.txt` + `app.py` or `main.py` | python (Flask/FastAPI) | `pip install -r requirements.txt` | `python app.py` or `uvicorn main:app --port {{PORT}}` |
| `Cargo.toml` | rust | `cargo build --release` | Read binary name from Cargo.toml, run `./target/release/{name}` |
| `index.html` (no package.json) | static | none | `python -m http.server {{PORT}}` |
| `Dockerfile` only (no source files) | docker | `docker build -t {name} .` | `docker run -p {{PORT}}:{internal_port} {name}` |

**If the app has BOTH a Dockerfile AND source files (go.mod, package.json, etc.):**
- ALWAYS build natively using the source files
- IGNORE the Dockerfile — it's just for deployment, not for local dev
- Check if the required toolchain is installed first (e.g., `go version`, `node --version`)
- If the toolchain is NOT installed, inform the user and ask them to install it — do NOT fall back to Docker

Also read:
- **README.md** — for build/run instructions the user wrote
- **Dockerfile** — for the internal port (`EXPOSE` directive) — useful even when not using Docker
- **Makefile** — for build targets
- **.env.example** — for required environment variables

## Step 2: Determine Port Configuration

External apps handle ports differently:

1. **Environment variable** — Most apps respect `PORT=3108`. Set `port_env_var: "PORT"`
2. **Command-line flag** — Some apps use `--port 3108`. Use `{{PORT}}` in the start command
3. **Config file** — Some apps read from a config file. Modify the config file to use the allocated port
4. **Hardcoded** — Worst case. Find and replace the port number in the source

Check in this order:
1. Does the README mention a PORT environment variable?
2. Does the Dockerfile use `ENV PORT` or `EXPOSE`?
3. Does the start script accept a `--port` flag?
4. Is there a config file (YAML, JSON, TOML) with a port setting?

## Step 3: Determine Health Check

| App Type | Health Strategy | Config |
|---|---|---|
| Has `/health` or `/healthz` endpoint | `http_get` | `url: "http://localhost:{{PORT}}/health"` |
| Web app with no health endpoint | `http_get` | `url: "http://localhost:{{PORT}}"` (root page) |
| Non-web app (background service) | `process_alive` | Just check if process is running |
| TCP service | `tcp` | Check if port is listening |

## Step 3.5: Find the App's Data Store (data_config)

While reading the code, find where the app persists data — this powers the
CLI's data commands (`select`, `count`, `sql`, `schema`) on the imported app:

- **SQLite file** (most common in self-hosted apps): pass
  `data_config={"sqlite": "relative/path/to.db"}` (relative to the project
  root after import). Check the README, config files, and code for the path.
- **External DB URL** (Postgres/MySQL): `data_config={"url": "postgresql://..."}`
- **Writable?** Default is READ-ONLY — safe. Only add `"writable": true` if
  you verified the app tolerates external writes (simple schema, no in-memory
  cache that would go stale). When in doubt, leave read-only and expose writes
  as declared ops through the app's own API instead.
- **No inspectable store** (flat files, proprietary format)? Omit data_config
  and expose reads via ops.

## Step 4: Call the Import Action

```
living_ui_import_external(
    name="Glance Dashboard",
    description="Self-hosted dashboard for monitoring feeds, weather, and more",
    source_path="/absolute/path/to/app/source",
    app_runtime="go",
    install_command="go build -o glance .",
    start_command="./glance --port {{PORT}}",
    health_strategy="http_get",
    health_url="http://localhost:{{PORT}}",
    port_env_var="",
    project_id="<the project_id from the task instruction, if provided>",
    data_config={"sqlite": "data/glance.db"},
)
```

> **Adopt the pre-created tab:** the task instruction usually provides a
> `project_id` for a tab that's already showing the user a progress screen.
> ALWAYS pass that `project_id` to `living_ui_import_external` (or
> `living_ui_import_zip`) so the import populates that existing tab. Omitting
> it creates a duplicate tab and leaves the original stuck on "creating".

## Step 5: Create LIVING_UI.md

After importing, create a `LIVING_UI.md` in the project directory documenting:
- What the app does
- How to configure it
- Key files and their purpose
- API endpoints (if any)
- Configuration file format

## Step 6: Construct the App's CLI Interface (MANDATORY)

Every Living UI is operated later through the `livingui` CLI
(`livingui <project> --help` → tables + operations). For imported
third-party apps the control surface is what YOU construct: the declared
`data_config` powers the data commands, and **the operations you declare in
`config/operations.json` ARE the app's verbs — without them the user
can see the app but no agent can ever operate it. An import without a
constructed CLI interface is a FAILED import** (validation enforces this).

Build it in three steps:

1. **Enumerate the app's controllable surface.** Read its README, routes,
   CLI flags, config files. List every function a user of this app would
   want automated: create/list/export its core objects, rebuild, sync,
   backup, report.
2. **Map each function to an executor:**
   - **App serves an OpenAPI/Swagger spec?** (FastAPI, Express+swagger,
     Spring, ...) Launch it once, then `livingui <project> ops-sync --write`
     — it probes the standard spec locations (`/openapi.json`,
     `/swagger.json`, `/v3/api-docs`, ...); use `--openapi-url <URL>` for
     non-standard ones. Curate descriptions and run `ops-check`. Only
     hand-author what the generator can't see.
   - **REST API without a spec** → `http` executors for its endpoints
   - **Its own CLI / build tools** → `shell` executors (declared command with
     `{param}` placeholders; `"mode": "job"` for anything over ~60s). Prefer
     `cli-anything-<app>` harness commands for desktop apps.
   - **No API and no CLI?** Write small wrapper scripts into
     `<project>/scripts/` (like draw.io's `scripts/diagram_tool.py`) and
     declare shell ops that call them — creating the missing interface is
     part of the import, not optional polish.
   - **Config-file driven** → declare a `reload`/`apply` op if the app has one
3. **Minimum viable CLI** — every import must declare at least:
   a `status`-style read op, the app's 2–5 core domain verbs, and any
   export/backup capability it has. Mark every READ-ONLY op `"safe": true`
   (with param defaults that make it runnable as-is) — validation executes
   the safe ops end-to-end and REFUSES the import if none exist or any
   fails. Never mark side-effecting ops safe.

Format spec: `skills/living-ui-creator/references/OPERATIONS.md`. Example for
an imported static-site generator:

```json
{
  "operations": {
    "list_posts": {
      "description": "List the site's content files with dates and titles",
      "params": {},
      "executor": {"type": "shell", "cmd": "hugo list all", "timeout": 60},
      "safe": true
    },
    "rebuild_site": {
      "description": "Rebuild the static site after content changes",
      "params": {},
      "executor": {"type": "shell", "cmd": "hugo --minify", "timeout": 120}
    }
  }
}
```

**Verify before finishing**: `living_ui_validate` runs these gates for real
(LIVING_UI.md present, ops declared, safe ops executed against the running
app) and returns step `import.adoption` with exact errors if any fail. Also
run `livingui <project_id> --help` via run_shell — the OPERATIONS section
must cover the app's main functions — and `livingui <project_id> select
<table> --limit 3` if you declared a data_config. Only then is the import
complete.

## Examples

### Node.js Express App
```
App detected: Node.js (package.json found)
Install: npm install
Start: npm start (from package.json scripts.start)
Port: PORT env var (common for Express)
Health: http_get on http://localhost:{{PORT}}
```

### Go Binary (Glance)
```
App detected: Go (go.mod found)
Install: go build -o glance .
Start: ./glance
Port: --port flag or config file
Health: http_get on http://localhost:{{PORT}}
```

### Static HTML Site
```
App detected: Static (index.html, no package.json)
Install: (none)
Start: python -m http.server {{PORT}}
Port: command-line argument
Health: http_get on http://localhost:{{PORT}}
```

### Docker App
```
App detected: Docker (Dockerfile found)
Install: docker build -t myapp .
Start: docker run --rm -p {{PORT}}:8080 myapp
Port: mapped via -p flag
Health: http_get on http://localhost:{{PORT}}
```

## FORBIDDEN

- NEVER use Docker to build or run an app if native source files exist (go.mod, package.json, requirements.txt, Cargo.toml). Build natively instead.
- NEVER ask the user to install Docker. If the native toolchain (Go, Node, Python, Rust) isn't installed, ask the user to install THAT instead.
- NEVER modify the original app source code during import (that's for the modify skill later)
- NEVER skip reading the README — it often has the correct build/run instructions
- NEVER assume a port — always detect it from the app's configuration
- NEVER use `living_ui_scaffold` for external apps — register them with `living_ui_import_external` (or `living_ui_import_zip` for exported projects). After the import succeeds, run `living_ui_validate` until it passes, then `living_ui_notify_ready` to launch (notify_ready refuses unvalidated projects).
