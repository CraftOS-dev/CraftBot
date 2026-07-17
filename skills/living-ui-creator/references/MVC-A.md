# MVC-A Architecture Guide

The Living UI pattern on the PocketBase platform. The APP is four layers
(MVC-A). The AGENT is not a layer of the app — it is CraftBot, an external
process that operates the app through the `livingui` CLI and plain HTTP.

```
CRAFTBOT AGENT / CODING AGENT        (external — never part of the app)
    │  livingui <project> ... · curl · Playwright browser tools
    ▼
┌───────────────────────────────────────────────────────────────┐
│  THE LIVING UI APP                                            │
│                                                               │
│  M - MODEL: config/schema.json → PocketBase collections       │
│      PB (single binary, SQLite) serves CRUD + realtime.       │
│      types.gen.ts / api.gen.ts regenerate on every write.     │
├───────────────────────────────────────────────────────────────┤
│  V - VIEW: components/regions/NN_slug.tsx                     │
│      Auto-mounted by MainView; vendored shadcn/ui + Tailwind. │
├───────────────────────────────────────────────────────────────┤
│  C - CONTROLLER: api.gen typed client + useEntities hooks     │
│      PB realtime is the change bus. ApiService = /api/custom. │
├───────────────────────────────────────────────────────────────┤
│  A - AGENT INTERFACE: system routes in _craftbot.pb.js        │
│      (/api/state, /api/ui-snapshot, /api/action, /api/logs)   │
│      + the verbs declared in config/operations.json           │
└───────────────────────────────────────────────────────────────┘
```

There is no hand-written backend. The old FastAPI engine (models.py,
routes.py, engine.py, main.py) does not exist — PocketBase IS the backend,
and the only server code you ever write is JS hooks in
`pb_hooks/main.pb.js`.

## M — the Model is DECLARED, not coded

Collections live in `config/schema.json` (PocketBase's native import
format — see BACKEND.md for the field-type reference). Writing that file
re-imports the collections into the RUNNING PocketBase and regenerates the
typed frontend client. The platform smooths the sharp edges for you:

- `created`/`updated` autodate fields are added to every collection.
- Missing access rules are forced PUBLIC (`""`) — PB's default of
  superuser-only would 403 the frontend. An explicit rule you write
  (e.g. `@request.auth.id != ""`) is respected.
- Relations are declared by NAME (`"collectionName": "cards"`); the
  platform resolves them to PB's required `collectionId` with stable ids,
  so re-imports are idempotent.

PB then serves, per collection, with zero code:
`GET/POST /api/collections/<name>/records` (`?filter=`, `?sort=-field`,
`?page/perPage`, `?expand=rel`), `GET/PATCH/DELETE .../records/<id>`,
realtime subscriptions, file storage. Ids are STRINGS.

Generated on every schema write (never edit):
- `frontend/types.gen.ts` — one interface per collection, field names
  exactly as declared + `id`/`created`/`updated`.
- `frontend/api.gen.ts` — typed helpers over the PB SDK:
  `api.<name>.getFullList/getOne/create/update/delete` + `use<Name>()`
  hooks and a schema-typed `useEntities`.

## V — regions auto-mount

Every `frontend/components/regions/NN_slug.tsx` with a default export is
discovered and rendered by `MainView` in filename order — you NEVER import
or wire a component into MainView by hand. Add a screen region = create
the file; change one = edit it in place; remove = delete it. Each region
renders inside an error boundary, so one crashing region cannot blank the
app (the console names the culprit region).

Build regions from the vendored shadcn/ui components in
`frontend/components/ui/` (`import { Button } from '@/components/ui/button'`;
missing one → `npx shadcn@latest add <name> --yes`) and Tailwind
token-mapped classes. `App.tsx` just renders MainView + the global
`<Toaster />` — never mount a second toaster.

## C — data access

```ts
import { api, useCards, useEntities } from '../api.gen'   // typed, generated
const cards = useCards({ filter: "done = false", sort: "-created" })
const { items, loading, create, update, remove } = useEntities('cards')
await api.cards.create({ title: "Hi", columnId: col.id })
```

- ALWAYS import from `'../api.gen'` — those versions are typed to your
  schema. The raw `services/data.ts` hook is untyped (fields become `any`).
- `useEntities(name, {filter, sort, perPage, expand})` returns
  `{items, loading, error, refresh, create, update, remove}`. Every
  mounted list subscribes to PB realtime, so a mutation ANYWHERE (another
  component, a custom route, the agent) refreshes every list — never lift
  entity state to "sync" components.
- Filters use PB syntax: `columnId = 'x' && done = false`.
- `ApiService.request(method, path, body)` is ONLY for the custom
  `/api/custom/*` endpoints; mutating calls auto-refresh mounted lists.
- localStorage is ONLY for ephemeral UI state (last tab, draft text).
  Anything that must survive a reload goes in PocketBase.

## Custom verbs — pb_hooks/main.pb.js

The only server code you write. `routerAdd` under `/api/custom/...` for
multi-record transactions, aggregations, and integration calls — never
CRUD (see BACKEND.md for the goja VM rules). Hook changes need
`livingui <id> restart`. Declare each verb as an op in
`config/operations.json` so future agents can discover and fire it —
what is declared there IS the app's control surface (see OPERATIONS.md).

## A — the agent interface

System routes served by `pb_hooks/_craftbot.pb.js` (system-managed,
present in every app):

| Endpoint | Purpose |
|----------|---------|
| `GET/PUT/DELETE /api/state`, `POST /api/state/replace` | whole-blob app state (JSON merge on PUT) |
| `GET/POST /api/ui-snapshot` | UI state the frontend reports (DOM, text, inputs) |
| `POST /api/action` | action-event log (frontend/agent events, appended to jsonl) |
| `POST /api/logs` | browser-console sink (captured for `livingui logs`) |
| `GET /health` | legacy health path (PB's own is `/api/health`) |

Entity CRUD is not listed — PB generates it from `config/schema.json`.

The `livingui` CLI wraps all of it:

```
livingui ls                                   all projects
livingui <project> --help                     capability card: tables, ops, commands
livingui <project> status                     running state + ui/api URLs
livingui <project> logs --tail 50             server + captured browser console
livingui <project> select|count|insert|update|delete|sql   direct DB (works when stopped)
livingui <project> api GET /api/...           any HTTP endpoint
livingui <project> run <op> [--param v]       declared operations
livingui <project> snapshot | screenshot      observe the live UI
livingui <project> start|stop|restart|migrate lifecycle
```

## System-managed vs agent-owned files

| Agent-OWNED (edit these) | |
|---|---|
| `config/schema.json` | THE data layer — collections declared here |
| `config/operations.json` | the app's declared verbs |
| `pb_hooks/main.pb.js` | custom endpoints + integration calls |
| `frontend/components/regions/*.tsx` | the app's screens |
| `frontend/types.ts` | app-specific NON-entity types |

| SYSTEM-MANAGED (use, never edit) | |
|---|---|
| `pb_hooks/_craftbot.pb.js` | agent-interface system routes |
| `frontend/types.gen.ts`, `frontend/api.gen.ts` | GENERATED from schema.json |
| `frontend/lib/pb.ts` | PB client singleton (same-origin) |
| `frontend/services/data.ts` | generic useEntities over the PB SDK |
| `frontend/services/ApiService.ts` | `/api/custom/*` client |
| `frontend/components/MainView.tsx` | region auto-mount shell |
| `frontend/components/ui/*` | vendored shadcn (extend via `npx shadcn add`) |
| `frontend/styles/global.css`, `styles/themes.css` | design tokens + style packs |
| `config/manifest.json`, `pb_data/` | platform-written metadata + PB's database dir |

## Platform lifecycle (what you never do yourself)

The platform (`pocketbase_runtime`) downloads a version-pinned PocketBase
binary once per machine, serves it per project
(`pocketbase serve --http=127.0.0.1:<port> --dir pb_data --hooksDir pb_hooks`),
bootstraps a local-only superuser, and imports `config/schema.json` on
every write. You never start servers, create `pb_data/`, or run
migrations by hand — `livingui <id> restart` and `migrate` are the levers.

## Data flow

```
User action
    ↓
Region component (components/regions/NN_slug.tsx)
    ↓
useEntities / api.gen create|update|remove    (entity CRUD — the standard path)
  or ApiService → /api/custom/*               (declared verbs only)
    ↓
PocketBase (generated CRUD, or pb_hooks/main.pb.js)
    ↓
SQLite (pb_data/)
    ↓
PB realtime broadcast → every mounted useEntities list refreshes
```
