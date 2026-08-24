---
name: living-ui-importer
description: Install Living UI apps from the marketplace or import Living UI projects from a ZIP, a local folder, or a git URL. Registers, launches, and verifies imported projects.
action-sets:
  - file_operations
  - living_ui
---

# Living UI Importer

Bring existing apps into this CraftBot: **marketplace installs** (pre-built
apps from the catalogue), **Living UI project imports** from a ZIP, a local folder
path, or a git URL, and **conversions** of foreign (non-Living-UI) apps —
which are REBUILDS: the original code becomes reference material and the
behavior is re-implemented on this platform. Be honest about that cost
before converting: nothing of the original code runs here.

## Which path?

| The user has… | Do this |
|---|---|
| An app name / "what's in the marketplace?" | `living_ui_marketplace_list` → match by name → `living_ui_marketplace_install(app_id=...)` |
| A `.zip`, a project folder path, or a git URL of a Living UI | `living_ui_import(source=...)` — one door for all three |
| A foreign (non-Living-UI) codebase | `living_ui_convert(source=...)` — a full REBUILD; tell the user first |

## Conversion (foreign apps)

`living_ui_convert(source=..., name?, description?)` scaffolds a fresh Living UI
project, ships the original source read-only at `reference/source/`,
synthesizes `requirements.md` FROM that source, and dispatches the normal
supervised build to the project's session — you are done after this call;
progress streams to the project tab and the system announces the result.
Pass `description` when the user said what matters ("keep the board, skip
the admin panel"). If the source turns out to BE a Living UI project the
action errors and points you to `living_ui_import`.

## Marketplace install

1. `living_ui_marketplace_list` — resolve the exact `app_id` (never guess
   ids; match the user's words against names/descriptions).
2. `living_ui_marketplace_install(app_id="...", name="...")` — downloads,
   registers, and **launches** the app in one step.
3. On success, tell the user the app name and URL. Marketplace apps are
   pre-built and pre-verified upstream — no walk-verify needed.
   NOTE: apps still in the legacy V1 format are rejected with a clear
   error — the platform only runs current-format Living UIs. Tell the user that app hasn't been
   re-published for this version of CraftBot yet; do not improvise a
   workaround.
4. On a launch error, treat it like any build failure: read ALL errors,
   fix (the project is a normal Living UI project under the ownership rules),
   `living_ui_notify_ready` again.

## Project import (ZIP / folder / git URL)

1. `living_ui_import(source="...")` — accepts an absolute `.zip` path, a
   local project folder path, or a git URL (GitHub is downloaded directly;
   other hosts are cloned). Registers a NEW delivered project (fresh id +
   port, shipped credentials stripped, kit re-vendored) and **queues a
   launch-and-verify run in the project's own session** — normally you are
   DONE after this call; the system announces the result.
   Only native Living UI projects are accepted; anything else errors.
2. Only if the action says the verify run could not be queued, drive it
   yourself: `living_ui_notify_ready(project_id="<ID>")` then
   `living_ui_walk_verify(project_id="<ID>")` — the app is delivered, so
   these run in staging mode and the walk's clean verdict deploys and
   announces it. Fix any gate errors under the usual ownership rules.
   HONESTY RULE: the import is done ONLY when the verify succeeds.
   (`living_ui_import_zip` still exists as the ZIP-only legacy door.)

## Adopting an EXTERNAL app (foreign source — runs AS-IS)

When `living_ui_import` receives a foreign (non-Living-UI) source it
registers it as an EXTERNAL project and dispatches an ADOPTION run with
these steps. The app runs UNCHANGED in its own runtime — never rebuild it,
never edit its code except configuration needed to bind the assigned port.

1. **Inspect** the source at the project path: README, dependency manifests
   (package.json / pyproject.toml / go.mod / Cargo.toml), how it starts,
   which port/env it expects, whether it has a build step.
2. **Write the pipeline verbs** into `<project>/craftbot.json` (NOT
   manifest.json — that may be the app's own file). Use `{{PORT}}` where
   the port belongs; the app must bind `127.0.0.1:{{PORT}}`:
   - node: install `npm install --ignore-scripts`; start e.g.
     `npm run dev -- --port {{PORT}} --host 127.0.0.1` or
     `PORT={{PORT}} node server.js` — whatever THIS app's scripts support.
   - python: install `pip install -r requirements.txt`; start e.g.
     `python3 -m uvicorn main:app --port {{PORT}}` / the app's own runner.
   - static: no install; start `python3 -m http.server {{PORT}}` from the
     directory holding index.html.
   - go / rust: build `go build -o app .` / `cargo build --release`; start
     the binary with its port flag/env.
   - health: default `{"strategy": "http_get", "url":
     "http://127.0.0.1:{{PORT}}/"}` — switch to `tcp` or `process_alive`
     for servers that 404 on `/`.
3. **Map the app's controllable surface** into `<project>/operations.json`
   (CraftBot's file — a stub exists) so agents can DRIVE the app over the
   A2App protocol. At launch the system substitutes a hidden internal port
   into your `{{PORT}}` verbs and serves the A2App adapter (identity,
   describe, `/api/_ops`, guarded `/api/ops/*`, passthrough for everything
   else) on the ASSIGNED port in front of the app. Probe in order:
   OpenAPI/Swagger spec shipped in the repo → route definitions in the
   code → the README. Declare the app's PUBLIC verbs with typed params;
   each op maps `executor.path` (`/api/ops/<name with dots as slashes>`)
   onto `executor.upstream` — the app's OWN endpoint:
   ```json
   { "name": "todos.create", "description": "Add a todo",
     "params": { "title": { "type": "string", "required": true } },
     "executor": { "type": "http", "method": "POST",
       "path": "/api/ops/todos/create",
       "upstream": { "method": "POST", "path": "/api/todos",
         "body": { "title": "{{title}}" } } } }
   ```
   (`body` template only when the app's field names differ from your param
   names.) Mark anything that deletes/overwrites `"destructive": true`.
   If the app has NO server API (static site, pure client-side SPA), leave
   `operations` empty and say so in `LIVING_UI.md` — never invent verbs,
   never map direct DB writes.
4. **Note what the app is** in `LIVING_UI.md` (one short section — the
   user's reference). Do NOT rewrite `reference/requirements.md`: it is
   pre-written with the adoption scope — verification covers *the app
   launches and its main screen renders*, never the foreign app's internal
   features (you can't fix those and must not try; the app ships as-is,
   quirks included).
5. `living_ui_notify_ready(project_id="<ID>")` — launches via your pipeline
   verbs. Errors come back with `logs/app.log` excerpts; fix the VERBS (or
   port binding config), not the app's features, and retry.
6. `living_ui_ops_verify(project_id="<ID>")` — invokes every
   non-destructive op FOR REAL through the adapter (destructive ops are
   shape-checked, never fired). Fix `executor.upstream` mappings — or
   remove ops that cannot work — and re-run until clean: a mapping that
   does not work must not ship.
7. `living_ui_walk_verify(project_id="<ID>")` — verifies the launch and
   announces. HONESTY RULE: adopted ONLY when this succeeds. If the app
   fundamentally cannot run here (needs a database server, private APIs,
   system deps), STOP and tell the user exactly what is missing — do not
   fake a start command that serves an error page.

Changes to a running external app apply LIVE (no staging): edit → 
`living_ui_notify_ready` relaunches it.

## Notes

- Imported/installed projects are ordinary Living UI projects afterwards:
  operate them via the lui CLI (`ops` / `run` / `data`), modify them via
  the living-ui-modify workflow. External apps speak the same ops surface
  through their adapter — `lui ops` / `lui run` (and raw HTTP with the
  project's `.agent-token`) work against them too; only the `data` verbs
  don't apply (no protocol entities in v1 — the app's own API passes
  through instead).
- Never edit `frontend/src/kit/`, `manifest.json`, or other system files
  of a Living UI project — the validation gate hashes them.
