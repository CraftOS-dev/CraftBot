---
name: living-ui-creator
description: Create custom Living UI applications on a PocketBase backend. Scaffolds, develops, tests, and launches dynamic web apps with persistent state.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Creator

Create interactive web applications that persist state and survive page reloads.

> **Routing note:** the direct chat entry for ALL Living UI development
> (create, update, fix) is the `living_ui_develop` conversation action —
> it starts the platform-driven development workflow. This skill and
> living-ui-modify remain as the fallback signal when a request arrives
> via generic `task_start` (the platform then attaches the same
> workflow), and as the reference library (`references/`) the build
> agents read.

## Architecture Overview

A Living UI is a **declared backend, typed frontend** app. The backend is
**PocketBase** (a single binary with SQLite) — the platform downloads it,
boots it, health-checks it, imports your collections from
`config/schema.json`, and bootstraps a superuser. There is **no `backend/`
directory and no hand-written server**: you declare collections, PocketBase
serves the data API, and the only server code you ever write is a small
hooks file.

```
┌─────────────────────────────────────────────────────────────────┐
│   BACKEND (PocketBase, single binary + SQLite)                  │
│   - Booted and managed by the platform (never launched by hand) │
│   - Collections declared in config/schema.json                  │
│   - PB serves CRUD/filter/sort/realtime/files per collection    │
│   - Custom logic ONLY in pb_hooks/main.pb.js (/api/custom/...)  │
├─────────────────────────────────────────────────────────────────┤
│   FRONTEND (Vite + React + TypeScript + Tailwind)               │
│   - Talks to PB through the GENERATED typed client (api.gen.ts) │
│   - Screens are auto-mounted region files (components/regions/) │
│   - shadcn/ui vendored in frontend/components/ui/               │
│   - localStorage only for ephemeral UI state                    │
└─────────────────────────────────────────────────────────────────┘
```

**Key principle**: PocketBase owns all durable state. Data a user would
expect to still be there after a reload lives in PB, never in React state
or localStorage.

## Reference Index (read the right file BEFORE acting)

| When you are about to... | Read |
|---|---|
| Declare collections / query the generated API / write pb_hooks | [BACKEND.md](references/BACKEND.md) |
| Write ANY frontend component (shadcn/ui usage, styling, theming) | [COMPONENTS.md](references/COMPONENTS.md) |
| Declare/curate the app's operations | [OPERATIONS.md](references/OPERATIONS.md) |
| Judge quality | [STANDARDS.md](references/STANDARDS.md) |
| Debug a failure (logs, common errors) | [TROUBLESHOOTING.md](references/TROUBLESHOOTING.md) |

## Project Layout

Files YOU edit (paths relative to the project root — always write with the
absolute `{project_path}/...`, never a bare relative path):

| File | Purpose |
|---|---|
| `config/schema.json` | Declared PocketBase collections — the data layer |
| `pb_hooks/main.pb.js` | Custom endpoints beyond CRUD (`/api/custom/...`) |
| `frontend/components/regions/NN_slug.tsx` | One auto-mounted region per screen |
| `frontend/components/*.tsx` | Supporting components |
| `config/operations.json` | Declared operations for the `livingui` CLI |
| `LIVING_UI.md` | Documentation of what was built |

SYSTEM-MANAGED — never edit:

- `config/manifest.json` (pipeline config: `engine: pocketbase`, ports, build commands)
- `pb_hooks/_craftbot.pb.js`, anything in `pb_data/`
- `frontend/lib/pb.ts`, `frontend/services/data.ts`
- `frontend/types.gen.ts`, `frontend/api.gen.ts` (regenerated from the schema)
- `frontend/components/MainView.tsx` (auto-mounts regions), `frontend/main.tsx`
- `frontend/components/ui/*` (vendored shadcn/ui — import from it; add a
  missing component with `npx shadcn@latest add <name> --yes`, never hand-write one)
- `vite.config.ts` (`@/` = `frontend/`, `build:debug` mode), `tailwind.config.js`, `postcss.config.js`, `frontend/styles/themes.css`

## The Data Layer Is Declared, Not Coded (MANDATORY)

Declare every collection in `config/schema.json` using PocketBase's native
import format. Writing this file re-imports the collections into the
**running** PocketBase and regenerates `frontend/types.gen.ts` +
`frontend/api.gen.ts`. You NEVER write models, CRUD routes, or migrations.

```json
{
  "collections": [
    {
      "name": "cards", "type": "base",
      "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": "",
      "fields": [
        {"name": "title", "type": "text", "required": true},
        {"name": "dueDate", "type": "date"},
        {"name": "columnId", "type": "relation", "collectionName": "boardColumns",
         "cascadeDelete": true, "maxSelect": 1}
      ]
    }
  ]
}
```

- Field types: `text`, `number`, `bool`, `date`, `select` (+`values`),
  `relation` (+`collectionName`, `maxSelect`, `cascadeDelete`), `json`,
  `file`, `email`, `url`.
- Rules `""` = public — correct for these local single-user apps.
- `id` is a STRING; `created`/`updated` are automatic. Never declare them.
- Field names are used EXACTLY as declared (camelCase recommended — the
  same names appear on the wire and in `types.gen.ts`).

PB then serves, per collection, for free (never write these):
`GET/POST /api/collections/<name>/records` (`?filter=`, `?sort=-field`,
`?page/perPage`, `?expand=rel`), `GET/PATCH/DELETE .../records/<id>`,
realtime subscriptions, and file storage. Full spec: [BACKEND.md](references/BACKEND.md).

### Frontend data access — the generated typed client

```ts
import { api, useEntities } from '../api.gen'   // typed against YOUR schema
const { items, loading, create, update, remove } = useEntities('cards', { sort: '-created' })
await api.cards.create({ title: 'Hi', columnId: col.id })
```

- ALWAYS import from `'../api.gen'` (not from `services/data` — that raw
  hook is untyped). Every mounted list auto-refreshes on any mutation.
- Filters use PB syntax: `done = false && n > 3`. Ids are strings.
- NEVER hand-write per-entity fetch methods or entity interfaces —
  `types.gen.ts`/`api.gen.ts` are regenerated on every schema write.

## Custom Server Logic — pb_hooks/main.pb.js ONLY

For behavior CRUD cannot express (multi-record transactions, computed
aggregations, external fetches, domain verbs) — never for CRUD:

```js
routerAdd("POST", "/api/custom/archive-done", (e) => {
  const body = e.requestInfo().body
  const cards = $app.findRecordsByFilter(
    "cards", `columnId = '${body.columnId}' && done = true`, "-created", 500, 0)
  cards.forEach((c) => { c.set("archived", true); $app.save(c) })
  return e.json(200, { archived: cards.length })
})
```

- Embedded JS VM (goja): plain JavaScript, NO npm imports, NO node APIs.
  Globals: `$app`, `$os`, `$http`, `$security` (full ambient API in
  `pb_data/types.d.ts`).
- Paths live under `/api/custom/...`; reply with `return e.json(status, obj)`.
- Hook changes need a backend restart: `livingui <id> restart`.
- **In-app AI is one call**: the `callLLM(prompt, systemMessage?)` helper
  already in `main.pb.js` (bridges to the CraftBot host; returns `""` on
  failure — degrade gracefully, never crash the request).
- The frontend calls custom endpoints through `ApiService` — its ONLY job:
  `await ApiService.request('POST', '/custom/archive-done', { columnId })`
  (path without the `/api` prefix; mutating calls auto-refresh every
  mounted `useEntities` list).

## Frontend Rules

**Screens are AUTO-MOUNTED region files.** Each screen is
`frontend/components/regions/NN_slug.tsx` with a default-exported
component; MainView discovers and renders every region in filename order,
each inside its own error boundary. You NEVER edit MainView or wire a
region by hand — creating the file puts it on screen.

**Use the vendored shadcn/ui for all standard UI** — read
[COMPONENTS.md](references/COMPONENTS.md) before writing any component:

```typescript
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from 'sonner'
```

- Forms: react-hook-form + zod + `@/components/ui/form`, typed against
  `types.gen`. Tables: `@/components/ui/table`. Confirmation:
  `<AlertDialog>` — never browser `confirm()`/`alert()`/`prompt()`.
- Style with the semantic Tailwind colors (`bg-background`, `bg-card`,
  `text-muted-foreground`, `bg-primary`, ...) — never arbitrary hex; they
  follow the user's live theme and style pack.
- `localStorage` is ONLY for ephemeral UI state (last tab, draft text).
- Nothing may overflow horizontally (`min-w-0`, `truncate`,
  `overflow-x-auto` on wide content).

### External data & device APIs

The app runs in a cross-origin iframe on localhost. Two patterns fail
there and must never be load-bearing:

1. **Frontend `fetch()` to third-party APIs** — CORS blocks most of them.
   ALL external data is fetched by a `pb_hooks` endpoint using
   `$http.send`, returning cached/normalized JSON to the frontend. No
   CORS, no exposed keys, and it degrades gracefully offline (return the
   last cached value or an empty payload — never a 500).
2. **Browser permission APIs** (`navigator.geolocation`, notifications,
   camera) — prompts inside the embedded tab are unreliable. A denied
   permission must never be a dead-end. Location: default to a keyless
   IP lookup from a `pb_hooks` endpoint (`https://ipapi.co/json/`),
   with browser geolocation at most an optional refinement and a
   user-editable location field (persisted in the schema) as override.

## How the Platform Builds an App

The build is **step-driven by the platform** (a code-side workflow step
program) — no human or LLM orchestrates phases. Knowing the loop explains
what the platform expects of the code:

1. **Scaffold** — `living_ui_scaffold(name, description)` copies the
   template, allocates ports, and registers the project; it returns
   `project_id` and an absolute `project_path`. The requirements spec is
   the task instruction, with a copy at
   `{project_path}/reference/requirements.md`. Everything after the
   scaffold is platform-driven.
2. **Build rounds** — the platform spawns ONE `coding_agent` per round: a
   complete software engineer that owns every file, builds feature by
   feature, and self-tests in a real browser (Playwright: navigate,
   snapshot, click/type, console). `verify_build` — the project's
   `npm run build:debug` (dev-mode, unminified React, so runtime errors
   name real components) — is the compile truth, with failures grouped by
   root cause. The agent cannot exit until the build passes AND it has
   actually driven the app. After each round the pipeline builds and
   launches the app (imports the schema into PB, health-checks, serves the
   frontend).
3. **Independent verification** — a read-only `walk_verify` agent drives
   the RUNNING app in a real browser against
   `reference/requirements.md` and returns `VERDICT: PASS|FAIL|BLOCKED`
   with a per-feature list. **This is the only thing that marks the app
   done** — the coding agent's self-report is never trusted. It checks
   persistence by reloading the app: data that vanishes on reload is a
   FAIL (PocketBase, not localStorage). FAIL verdicts become the next
   round's work order; a fix ledger records every attempt so no failed
   approach is retried blind.
4. **Present** — once the walk passes, the platform presents the app
   (`living_ui_notify_ready`) and ends the task.

Consequences for anyone writing app code:

- "It compiles" is never done — a compiling shell with dead UI fails the
  walk. Every feature must work end to end with real, persisted data.
- Never seed fake/sample data to look done — empty states are the no-data
  content, and the walk tests real flows.
- Never launch servers by hand (`npm run dev`/`preview`, the pocketbase
  binary) — the platform boots PB and serves the frontend;
  `livingui <id> status` shows the URLs, `livingui <id> logs --tail 100`
  the logs.

## Operations (config/operations.json)

Living UIs are operated later through the `livingui` CLI:
`livingui <project> --help` shows the app's tables and declared
operations. Plain CRUD needs no ops — the CLI's built-in data commands
cover every schema collection. Declare typed verbs for your custom
`/api/custom/...` endpoints (http executors point at those paths);
generate and curate them with `livingui <id> ops-sync --write` /
`ops-check`. See [OPERATIONS.md](references/OPERATIONS.md).

## Debugging

Read the logs first: `livingui <id> logs --tail 100`, plus
[TROUBLESHOOTING.md](references/TROUBLESHOOTING.md).

## FORBIDDEN Actions

- NEVER write to bare relative paths — always the absolute
  `{project_path}/...` so files land in the project, not the CraftBot root
- NEVER hand-write CRUD, models, or migrations — declaring the collection
  in `config/schema.json` IS the CRUD; never write CRUD in pb_hooks
- NEVER declare `id`, `created`, or `updated` fields — PocketBase provides them
- NEVER edit system-managed files: `config/manifest.json`,
  `pb_hooks/_craftbot.pb.js`, `pb_data/`, `frontend/lib/pb.ts`,
  `frontend/services/data.ts`, `*.gen.ts`, `MainView.tsx`,
  `frontend/main.tsx`, `frontend/components/ui/*`, `vite.config.ts`,
  `tailwind.config.js`, `postcss.config.js`
- NEVER hand-edit or delete the PocketBase data directory (`pb_data/`) —
  data structure lives in `config/schema.json`
- NEVER wire a screen into MainView by hand — regions auto-mount from
  `frontend/components/regions/NN_slug.tsx`
- NEVER hand-write entity types or per-entity fetch code — import from
  `types.gen.ts`/`api.gen.ts`; `ApiService` is only for `/api/custom/*`
- NEVER store durable state only in React or localStorage — anything that
  must survive a reload goes in PocketBase
- NEVER use raw HTML controls (`<button>`, `<input>`, `<select>`) or
  browser dialogs (`prompt()`, `confirm()`, `alert()`) — shadcn components
  and `Dialog`/`AlertDialog`
- NEVER pick arbitrary colors — use the semantic Tailwind classes
- NEVER fetch third-party APIs from the frontend (CORS) and NEVER make a
  browser permission load-bearing — external data comes from a `pb_hooks`
  endpoint
- NEVER seed fake/sample/demo data to pass verification or showcase UI
- NEVER run `npm run dev`/`npm run preview` or the pocketbase binary
  manually — the platform builds, launches, and serves; compile-check with
  `verify_build` / `npm run build:debug` from the project root only
- NEVER leave `LIVING_UI.md` with placeholder content, HTML comments, or
  example data
- NEVER hand-author operations.json paths/params — `livingui <id>
  ops-sync --write`, then curate descriptions and run `ops-check`

## References

- [Backend (PocketBase)](references/BACKEND.md) - Schema spec, generated API, pb_hooks rules, frontend data access, operations
- [UI Components](references/COMPONENTS.md) - shadcn/ui usage, styling rules, theming, accent discipline
- [Operations Manifest](references/OPERATIONS.md) - Declaring the app's verbs (config/operations.json)
- [Quality Standards](references/STANDARDS.md) - Professional standards for Living UIs
- [Troubleshooting](references/TROUBLESHOOTING.md) - Debug common issues, log files
