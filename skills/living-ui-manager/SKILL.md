---
name: living-ui-manager
description: Get, set, update data and manipulate state of running Living UI applications. Reads project registry and LIVING_UI.md for context, uses HTTP APIs or creates new endpoints as needed.
action-sets:
  - core
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Manager

Interact with existing Living UI applications: read data, write data, update state, and add new capabilities.

## Workflow

Follow these steps **in order** for every Living UI interaction.

### Before You Start: Read and Apply Global Config

Read `agent_file_system/GLOBAL_LIVING_UI.md` for global design preferences and rules. You MUST follow:
- **Colors**: Use the defined Primary/Secondary/Accent hex values for any new UI elements or endpoints.
- **Enabled rules `[x]`**: Treat as hard requirements.
- **Always Enforced rules**: Non-negotiable.
- Per-project requirements from the project's `LIVING_UI.md` override global settings.

### Step 1: Identify the Living UI

Read the project registry:

```
File: agent_file_system/workspace/living_ui_projects.json
```

This JSON contains all projects. Each entry has:

| Field | Purpose |
|-------|---------|
| `id` | Unique project identifier |
| `name` | Display name (use this to match user's request) |
| `path` | Absolute path to project directory |
| `status` | running, stopped, creating, error |
| `port` | Frontend port (DO NOT use for API calls) |
| `backendPort` | Backend API port (USE THIS for all API calls) |

**Match by name** - if the user says "todo" or "expense", fuzzy-match against project names. If ambiguous, list available projects and ask the user.

### Step 2: Read LIVING_UI.md

```
File: {project.path}/LIVING_UI.md
```

This is the **context index** for the Living UI. It documents:
- **Data Model** - database tables and fields
- **API Endpoints** - all available routes (method, path, description)
- **Frontend Components** - UI structure
- **Ports** - backend and frontend URLs

**Read this file before making any API calls.** It tells you exactly what endpoints exist and what data structures to use.

If LIVING_UI.md is empty or has only template placeholders (e.g., `<!-- Agent: ... -->`), skip to Step 4 to read the source code directly.

### Step 3: Execute the Operation

**Base URL**: `http://localhost:{backendPort}/api`

The project backend must be running (status = "running"). If it's stopped, inform the user that the Living UI needs to be launched first from the browser.

#### Reading Data

Use `http_request` with the appropriate endpoint from LIVING_UI.md:

```
# Custom resource endpoints (check LIVING_UI.md for exact paths)
GET http://localhost:{backendPort}/api/todos
GET http://localhost:{backendPort}/api/todos/{id}

# Generic state endpoint (always available)
GET http://localhost:{backendPort}/api/state

# Generic items endpoint (always available)
GET http://localhost:{backendPort}/api/items
GET http://localhost:{backendPort}/api/items/{id}
```

#### Writing / Updating Data

```
# Create - POST with JSON body
POST http://localhost:{backendPort}/api/todos
Body: {"title": "New item", "priority": "high"}

# Update - PUT with JSON body
PUT http://localhost:{backendPort}/api/todos/{id}
Body: {"completed": true}

# Delete
DELETE http://localhost:{backendPort}/api/todos/{id}

# Bulk state update (merges with existing)
PUT http://localhost:{backendPort}/api/state
Body: {"data": {"key": "value"}}

# Execute named action
POST http://localhost:{backendPort}/api/action
Body: {"action": "complete-all", "payload": {}}
```

#### Observing the UI

```
GET http://localhost:{backendPort}/api/ui-snapshot    # DOM, text, form values
GET http://localhost:{backendPort}/api/ui-screenshot  # Base64 PNG image
```

**After any operation**, format the results clearly for the user.

### Step 4: If No Suitable API Exists

When LIVING_UI.md does not list an endpoint for the requested operation, or the endpoint returns 404/405:

#### 4a. Read the Backend Source Code

```
{project.path}/backend/routes.py   - existing API endpoints
{project.path}/backend/models.py   - database models
```

Check if the data or functionality already exists but isn't documented in LIVING_UI.md. If you find a usable endpoint, use it and update LIVING_UI.md.

#### 4b. Create the Missing Endpoint

If no suitable endpoint exists:

1. **Edit `backend/routes.py`** - add the new route following existing patterns:

```python
# Follow the existing import style and router pattern
@router.get("/your-endpoint")
def get_your_data(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Description of what this does."""
    items = db.query(YourModel).all()
    return [item.to_dict() for item in items]
```

2. **Edit `backend/models.py`** if a new data model is needed:

```python
class YourModel(Base):
    __tablename__ = 'your_table'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    # ... fields ...

    def to_dict(self):
        return {"id": self.id, "name": self.name}
```

3. **Update `LIVING_UI.md` (MANDATORY)** — add the new endpoints to the API Endpoints table and update Data Model table if models changed. Remove any HTML comments or placeholder data. Future interactions depend on this being accurate.

#### 4c. Restart the Backend

After modifying backend code, use the `living_ui_restart` action:

```
living_ui_restart(project_id="{project.id}")
```

This action stops the entire project (backend + frontend), runs the launch pipeline (install, tests, build, health checks), and relaunches both on the same ports. If there are import errors or test failures, it will report them.

**DO NOT** run `python -c "from models import *"` or `npm run build` manually — the pipeline handles verification.
**DO NOT** use `living_ui_notify_ready` for restart — it's for initial launch only.

#### 4d. Call the New Endpoint

Now use `http_request` to call your newly created endpoint.

## Directory Structure Reference

When reading project files (Step 4), this is the layout:

```
{project.path}/
├── backend/
│   ├── main.py          # FastAPI entry point (rarely edit)
│   ├── models.py        # SQLAlchemy models - edit for new data
│   ├── routes.py        # API endpoints - edit for new routes
│   ├── database.py      # DB connection (rarely edit)
│   └── living_ui.db     # SQLite database (auto-created)
├── frontend/            # DO NOT edit for data operations
├── config/manifest.json # Port info (also in projects.json)
└── LIVING_UI.md         # Context index - ALWAYS update
```

## Backend Coding Rules

When creating new endpoints (Step 4b):

- **NEVER use `metadata` as a SQLAlchemy column name** (it's reserved)
- Always include `to_dict()` method on new models for JSON serialization
- If model name conflicts with Python built-ins, use alias: `from models import List as ListModel`
- Follow existing import style and router patterns in the file
- New SQLite tables are auto-created on next backend startup

## Rules

- **Always read LIVING_UI.md first** before making API calls
- **Use `backendPort`** from projects.json, never the frontend `port`
- **Backend must be running** for HTTP requests to work
- **Never modify frontend code** for data operations - always use backend APIs
- **Update LIVING_UI.md** after adding new endpoints
- **Format results** clearly for the user - tables, lists, summaries
- **Use `living_ui_restart` action** after code changes - never start servers manually or run verification commands yourself; the restart pipeline runs install, tests, and health checks and reports any import errors (see 4c)
- **Don't create a Living UI** - this skill is for interacting with existing ones. Use `living-ui-creator` skill to create new Living UIs.
