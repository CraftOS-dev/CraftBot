# MVC-A Architecture Guide

The Living UI pattern for building agent-aware web applications.

## The Pattern

The APP is four layers (MVC-A). The AGENT is not a layer of the app — it
is CraftBot, an external process, and it reaches the app through ONE tool:
the `livingui` CLI.

```
CRAFTBOT AGENT                     (external — never part of the app)
    │
    │  run_shell: livingui <project> ...
    ▼
livingui CLI                       (the agent's ONLY way to operate a
    │                               running Living UI)
    ├── select/insert/sql…  ──────► the app's database (works even stopped)
    ├── api / run / snapshot ─────► the app's backend over HTTP
    └── restart / status ────────► the CraftBot platform (lifecycle)
    ▼
┌─────────────────────────────────────────────────────────────┐
│  THE LIVING UI APP                                          │
│                                                             │
│  M - MODEL (schema.json → engine → SQLite + REST CRUD)      │
│  Source of truth. Persists data. Generated API.             │
├─────────────────────────────────────────────────────────────┤
│  V - VIEW (React Frontend)                                  │
│  Stateless UI. Renders data. Captures user input.           │
├─────────────────────────────────────────────────────────────┤
│  C - CONTROLLER (useEntities / AppController)               │
│  Orchestrates. Calls APIs. Manages local state cache.       │
├─────────────────────────────────────────────────────────────┤
│  A - AGENT INTERFACE (the app's HTTP surface FOR the agent) │
│  GET /api/ui-snapshot     - Observe UI state                │
│  GET /api/ui-screenshot   - Visual observation              │
│  GET/PUT /api/state       - Application data                │
│  POST /api/action         - Trigger named actions           │
│  (system_routes.py — built into every app, never edited)    │
└─────────────────────────────────────────────────────────────┘
```

Read it top-down: the agent invokes the CLI; the CLI talks to the app's
database, its HTTP endpoints (generated CRUD, custom ops, and the A-layer
routes), or the platform. The A layer is NOT the agent — it is the part of
the app that exists so an agent can observe and drive it.

## The Model is DECLARED, not coded

Entities live in `config/schema.json`; the backend engine materializes the
SQLAlchemy models and a full REST CRUD API per entity (list with filters +
ordering, get, create, update, delete, bulk) at startup. `GET
/api/_meta/schema` returns the schema and generated routes. Hand-written
code is only for BEHAVIOR: custom endpoints in `routes.py`, declared as ops
in `config/operations.json`.

## Agent Communication Protocol

**All agent communication uses HTTP** (via the CLI) - no WebSocket required.

### The A Layer: Standard Agent-Interface Endpoints

Built into every app by `system_routes.py` (system-managed — never edit):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/state` | GET | Get application data state |
| `/api/state` | PUT | Update application state |
| `/api/ui-snapshot` | GET | Get UI state (DOM, text, inputs) |
| `/api/ui-screenshot` | GET | Get UI screenshot (PNG base64) |
| `/api/action` | POST | Trigger named action |

Entity CRUD is NOT listed here because it is generated per entity from
`config/schema.json` (`/api/<plural>` + bulk/search/stats).

### UI Snapshot (GET /api/ui-snapshot)

Returns current UI state captured by the frontend:

```json
{
  "htmlStructure": "<body>...",
  "visibleText": ["Welcome", "Click here", ...],
  "inputValues": {"search": "query", "email": "user@..."},
  "componentState": {"App": {"initialized": true}},
  "currentView": "/dashboard",
  "viewport": {"width": 1200, "height": 800, "scrollX": 0, "scrollY": 100},
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Use for:** Observing what the user sees, monitoring form inputs, tracking navigation

### UI Screenshot (GET /api/ui-screenshot)

Returns a screenshot of the current UI:

```json
{
  "imageData": "iVBORw0KGgo...",  // Base64 PNG
  "width": 1200,
  "height": 800,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Use for:** Visual verification, debugging layout issues, documentation

**To display:** `<img src="data:image/png;base64,{imageData}">`

### Triggering Actions (POST /api/action)

```
livingui <project> run <op> --param value
```

Built-in actions: `reset`, `increment`, `decrement`.
App-specific verbs are real endpoints in `routes.py`, declared as ops in
`config/operations.json`.

---

## When to Use Each Layer

### Model Layer (Backend + Database)

**USE WHEN:**
- Data must persist across sessions
- Multiple data entities with relationships
- Complex queries (filtering, sorting, aggregation)
- External API calls (don't call external APIs from frontend)
- Agent needs to read/write data via API

**SKIP WHEN:**
- Pure visualization (charts from provided data)
- Static content display
- Calculator/converter tools (no persistence needed)

### View Layer (Frontend)

**ALWAYS NEEDED** - but complexity varies:
- **Simple:** Single component, minimal interactivity
- **Medium:** Multiple components, forms, lists
- **Complex:** Multi-view, navigation, rich interactions

### Controller Layer (useEntities / AppController)

The standard controller is PROVIDED: `useEntities<T>(plural, filters)` from
`services/data.ts` handles fetch/create/update/remove with auto-refresh —
most apps need nothing more. `AppController.ts` is OPTIONAL, for
app-specific orchestration beyond entity CRUD (multi-step flows, cross-
component coordination, custom-endpoint calls via ApiService).

### Agent Interface Layer (A)

**ALWAYS AVAILABLE** - the standard endpoints are built-in via
`system_routes.py`; the agent never has to build its own access:
- `/api/ui-snapshot` - Automatic UI state capture
- `/api/ui-screenshot` - On-demand screenshots
- `/api/state` - Application data
- `/api/action` - Trigger actions

Imported (external) apps get `/api/ui-snapshot` and `/api/ui-screenshot`
too — served by the platform's sidecar proxy, which injects the capture
script into the app's HTML without touching its source. Their `/api/state`
and `/api/action` equivalents are whatever ops the importer declared in
`config/operations.json`.

---

## Architecture Decision Matrix

| App Type | Database | Backend API | Frontend | Agent Interface |
|----------|----------|-------------|----------|-----------------|
| Todo/Task list | ✓ | ✓ | ✓ | ✓ (built-in) |
| Dashboard (live data) | ✓ | ✓ | ✓ | ✓ |
| Calculator | - | - | ✓ | ✓ |
| Data visualizer | - | ✓ (external API) | ✓ | ✓ |
| CRUD app | ✓ | ✓ | ✓ | ✓ |
| Game with saves | ✓ | ✓ | ✓ | ✓ |
| Agent-fed display | - | ✓ (receive data) | ✓ | ✓ |

---

## Agent Access: the livingui CLI (the ONLY way to operate a Living UI)

Agents operate every Living UI through the `livingui` CLI via run_shell
(it is on PATH — run `livingui ...` directly). There is no other supported
path — no direct curl, no direct sqlite, no HTTP actions.

```
livingui <project> --help                     discover: tables, operations, commands
livingui <project> snapshot                   what the user sees (DOM/text/inputs)
livingui <project> screenshot --out shot.png  visual check (then describe_image)
livingui <project> select <table> --where ... read rows (works when stopped)
livingui <project> insert <table> --file F    bulk write (one command for N rows)
livingui <project> update <table> --where ... --set k=v
livingui <project> sql "SELECT ..."           aggregates and joins
livingui <project> run <op> [--param v]       the app's declared verbs (real logic)
livingui <project> api GET /api/...           raw endpoint passthrough
livingui <project> migrate | restart          schema changes / lifecycle
```

### Choosing the right command

| Need | Command |
|------|---------|
| Discover everything (schema, ops, routes) | `livingui <project> --help` |
| See what the user sees | `snapshot` / `screenshot` |
| Read/write rows in bulk | `select` / `insert --file` / `update --where` |
| Complex queries | `sql "SELECT ..."` |
| Trigger app behavior | `run <op>` (prefer over raw writes — runs real logic) |
| Call a custom endpoint | `api <METHOD> <path>` |
| Drive the running UI | `ui --data '{"type": "refresh"}'` |
| Add a capability that doesn't exist | edit code → declare op → `restart` |

---

## External Data Fetching (Into Living UI)

### Option A: Backend Proxy (Recommended)

Backend fetches external data, frontend gets it from backend.

```python
@router.get("/weather")
def get_weather():
    response = requests.get("https://api.weather.com/...")
    return response.json()
```

**Best for:** External APIs, API keys, caching needed. Data from
CraftBot-connected services (GitHub, Google, Slack, ...) goes through
`services/integration_client.py` — see INTEGRATIONS.md.

### Option B: Agent-Fetched Data

Agent fetches data and pushes it into the Living UI:

```
# Agent fetches external data, then pushes it into the Living UI
livingui <project> api PUT /api/state --data '{"data": {"weather": {"temp": 72}}}'
```

**Best for:** Real-time data, agent-controlled refresh cycles

---

## Component Responsibilities

### Backend Files

| File | Responsibility |
|------|----------------|
| `config/schema.json` | THE data layer — entities are declared here |
| `engine.py` | schema.json → models + CRUD API (SYSTEM — never edit) |
| `models.py` | Re-exports engine + system models (SYSTEM — never edit) |
| `system_routes.py` | The A layer: /state /action /ui-* (SYSTEM — never edit) |
| `routes.py` | CUSTOM behavior endpoints ONLY — edit this |
| `database.py` | DB connection, .env DATABASE_URL (SYSTEM — never edit) |
| `main.py` | FastAPI app setup (SYSTEM — never edit) |

### Frontend Files

| File | Responsibility |
|------|----------------|
| `types.gen.ts` | GENERATED entity types — import, never edit |
| `types.ts` | App-specific NON-entity types only |
| `services/data.ts` | Generic CRUD client + useEntities (SYSTEM — use, never edit) |
| `services/ApiService.ts` | Client for CUSTOM endpoints only |
| `services/UICapture.ts` | UI snapshot/screenshot capture (SYSTEM) |
| `AppController.ts` | OPTIONAL app-specific orchestration |
| `components/` | React UI components — edit/add here |

### Data Flow

```
User Action
    ↓
React Component
    ↓
useEntities.create/update/remove   (entity CRUD — the standard path)
  or AppController → ApiService    (custom endpoints only)
    ↓
Backend Route (generated CRUD, or routes.py)
    ↓
Database
    ↓
Response flows back up

On meaningful events (state changes, user interactions):
UICapture → POST /api/ui-snapshot → agent reads via `livingui snapshot`
```

---

## The CLI (how agents actually operate the app)

Everything above is reachable through ONE tool: `livingui`. Agents never
curl, never open the DB, never start servers by hand.

Universal built-ins (work on EVERY Living UI, no declaration needed):

| Command | Purpose |
|---|---|
| `livingui <project> --help` | The app's tables, declared ops, commands |
| `select/count/insert/update/delete/sql` | Direct data plane (works even when the app is stopped) |
| `schema` | Tables + columns as they exist on disk |
| `api GET /api/...` | Call any backend endpoint |
| `run <op> --params-file p.json` | Execute a declared operation |
| `jobs` / `job <id>` | Long-running op status |
| `ui` / `snapshot` / `screenshot` | Observe the running UI |
| `status` / `logs --tail 50` / `restart` / `migrate` | Lifecycle + diagnostics |

App-specific verbs come from `config/operations.json` (see the executor
recipes in that file). The contract: **what is declared there IS the app's
control surface** — an undeclared capability does not exist for any future
agent. CRUD never needs an op; the data commands and generated REST cover
every schema entity automatically.

## Quick Reference: Operating an App

```bash
# Get UI state (what the user sees)
livingui <project> snapshot

# Get a screenshot (then view it with describe_image)
livingui <project> screenshot --out shot.png

# Get / update the generic app state
livingui <project> api GET /api/state
livingui <project> api PUT /api/state --data '{"data": {"key": "value"}}'

# Trigger a named action / declared op
livingui <project> run reset

# Entity CRUD (any schema entity, running or stopped)
livingui <project> select cards --where '{"status": "open"}'
livingui <project> insert cards --file rows.json
```
