# MVC-A Architecture Guide

The Agent App pattern for building agent-aware web applications.

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

```bash
curl -X POST http://localhost:PORT/api/action \
  -H "Content-Type: application/json" \
  -d '{"action": "refresh"}'
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

## Agent Data Access Methods

### Method 1: UI Observation (GET /api/ui-snapshot)

Agent reads what the user sees on the UI.

```bash
curl http://localhost:PORT/api/ui-snapshot
```

- **Captures:** DOM structure, visible text, form values, component state
- **Frequency:** Event-driven (on page load, state changes, user interactions)
- **Best for:** Monitoring user interactions, form data, navigation

### Method 2: Visual Observation (GET /api/ui-screenshot)

Agent gets a visual screenshot of the UI.

```bash
curl http://localhost:PORT/api/ui-screenshot
```

- **Format:** Base64 encoded PNG
- **Best for:** Visual verification, debugging, documentation

### Method 3: Data API (GET/PUT /api/state)

Agent reads/writes application state.

```bash
# Read state
curl http://localhost:PORT/api/state

# Update state
curl -X PUT http://localhost:PORT/api/state \
  -H "Content-Type: application/json" \
  -d '{"data": {"counter": 5}}'
```

- **Best for:** Reading/writing structured application data

### Method 4: Direct Database Access

Agent reads/writes SQLite database directly.

```python
import sqlite3

conn = sqlite3.connect("backend/agent_app.db")
cursor = conn.execute("SELECT * FROM items")
items = cursor.fetchall()
```

- **Best for:** Bulk operations, complex queries
- **Caution:** Bypasses API validation

### Method 5: Code Modification

Agent edits Agent App code to add new endpoints/features.

- **Best for:** Adding capabilities that don't exist
- **Requires:** Rebuild after changes

### Choosing the Right Method

| Need | Method | Endpoint |
|------|--------|----------|
| See what user sees | UI Snapshot | GET /api/ui-snapshot |
| Visual verification | Screenshot | GET /api/ui-screenshot |
| Read app data | Data API | GET /api/state |
| Write app data | Data API | PUT /api/state |
| Trigger action | Action API | POST /api/action |
| Bulk operations | Direct DB | SQLite file |

---

## External Data Fetching (Into Agent App)

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

Agent fetches data and posts to Agent App via API.

```bash
# Agent fetches external data, then posts to Agent App
curl -X PUT http://localhost:PORT/api/state \
  -H "Content-Type: application/json" \
  -d '{"data": {"weather": {"temp": 72, "condition": "sunny"}}}'
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
