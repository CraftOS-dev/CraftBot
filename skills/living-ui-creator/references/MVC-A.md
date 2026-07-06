# MVC-A Architecture Guide

The Living UI pattern for building agent-aware web applications.

## The Pattern

```
┌─────────────────────────────────────────────────────────────┐
│  M - MODEL (Backend + SQLite)                               │
│  Source of truth. Persists data. Exposes REST API.          │
├─────────────────────────────────────────────────────────────┤
│  V - VIEW (React Frontend)                                  │
│  Stateless UI. Renders data. Captures user input.           │
├─────────────────────────────────────────────────────────────┤
│  C - CONTROLLER (AppController)                             │
│  Orchestrates. Calls APIs. Manages local state cache.       │
├─────────────────────────────────────────────────────────────┤
│  A - AGENT (HTTP API Layer)                                 │
│  GET /api/ui-snapshot - Observe UI state                    │
│  GET /api/ui-screenshot - Visual observation                │
│  POST /api/action - Trigger actions                         │
└─────────────────────────────────────────────────────────────┘
```

## Agent Communication Protocol

**All agent communication uses HTTP** - no WebSocket required.

### Standard Agent Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/state` | GET | Get application data state |
| `/api/state` | PUT | Update application state |
| `/api/ui-snapshot` | GET | Get UI state (DOM, text, inputs) |
| `/api/ui-screenshot` | GET | Get UI screenshot (PNG base64) |
| `/api/action` | POST | Trigger named action |
| `/api/items` | GET/POST | CRUD operations |

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

Built-in actions: `reset`, `increment`, `decrement`
Custom actions can be added in `routes.py`.

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

### Controller Layer (AppController)

**ALWAYS NEEDED** - manages state flow between View and Model:
- Fetches data from backend
- Handles user actions
- Updates local state cache

### Agent Layer (HTTP APIs)

**ALWAYS AVAILABLE** - The standard endpoints are built-in:
- `/api/ui-snapshot` - Automatic UI state capture
- `/api/ui-screenshot` - On-demand screenshots
- `/api/state` - Application data
- `/api/action` - Trigger actions

---

## Architecture Decision Matrix

| App Type | Database | Backend API | Frontend | Agent APIs |
|----------|----------|-------------|----------|------------|
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

**Best for:** External APIs, API keys, caching needed

### Option B: Agent-Fetched Data

Agent fetches data and posts to Living UI via API.

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
| `models.py` | SQLAlchemy models, data schema |
| `routes.py` | REST API endpoints (including agent APIs) |
| `database.py` | DB connection (rarely edit) |
| `main.py` | FastAPI app setup (rarely edit) |

### Frontend Files

| File | Responsibility |
|------|----------------|
| `AppController.ts` | State management, API calls |
| `types.ts` | TypeScript interfaces |
| `components/` | React UI components |
| `services/UICapture.ts` | UI snapshot/screenshot capture |
| `services/ApiService.ts` | Backend API client |

### Data Flow

```
User Action
    ↓
React Component
    ↓
AppController.method()
    ↓
ApiService.call()
    ↓
Backend Route
    ↓
SQLite Database
    ↓
Response flows back up

On meaningful events (state changes, user interactions):
UICapture → POST /api/ui-snapshot → Agent can GET
```

---

## Quick Reference: Agent API Usage

Replace `PORT` with the backend port from `config/manifest.json`.

```bash
# Get UI state
curl http://localhost:PORT/api/ui-snapshot

# Get screenshot
curl http://localhost:PORT/api/ui-screenshot

# Get app data
curl http://localhost:PORT/api/state

# Update app data
curl -X PUT http://localhost:PORT/api/state \
  -H "Content-Type: application/json" \
  -d '{"data": {"key": "value"}}'

# Trigger action
curl -X POST http://localhost:PORT/api/action \
  -H "Content-Type: application/json" \
  -d '{"action": "reset"}'

# CRUD items
curl http://localhost:PORT/api/items
curl -X POST http://localhost:PORT/api/items \
  -H "Content-Type: application/json" \
  -d '{"title": "New Item"}'
```
