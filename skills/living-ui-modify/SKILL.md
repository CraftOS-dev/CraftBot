---
name: living-ui-modify
description: Modify existing Living UI applications - add features, fix bugs, update UI, change backend logic. Reads existing code, makes targeted changes, verifies, and restarts.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Modifier

Make changes to existing Living UI applications: add features, fix bugs, update UI components, modify backend logic, or restructure data models.

## FIRST: Read Logs Before Any Code Changes

If the user is reporting a bug or issue, you MUST read the logs BEFORE attempting any fix.
Do NOT guess at what's wrong — the logs tell you exactly what failed.

1. Read `{project.path}/backend/logs/subprocess_output.log` — backend crashes and stack traces
2. Read `{project.path}/backend/logs/frontend_console.log` — frontend errors and failed API calls
3. Read the most recent `{project.path}/backend/logs/backend_*.log` — request-level errors

Only after reading the logs should you identify the root cause and make targeted fixes.

## Workflow

Follow these phases in order. Use TodoWrite to track progress.

### Before You Start: Read and Apply Global Config

Read `agent_file_system/GLOBAL_LIVING_UI.md` for global design preferences and rules. You MUST follow:
- **Colors**: Use the defined Primary/Secondary/Accent hex values for new UI elements.
- **Enabled rules `[x]`**: Treat as hard requirements.
- **Always Enforced rules**: Non-negotiable.
- Per-project requirements from the project's `LIVING_UI.md` override global settings.

### Phase 1: Identify the Living UI

Read the project registry:

```
File: agent_file_system/workspace/living_ui_projects.json
```

Each entry has: `id`, `name`, `path`, `status`, `port` (frontend), `backendPort` (backend API).

**Match by name** - fuzzy-match user's request against project names. If ambiguous, list projects and ask.

### Phase 2: Understand Current Implementation

Start with the `livingui` CLI (via run_shell):
`livingui <project_id> --help` — the capability card
shows the database schema (ground truth), declared operations, and commands
in one shot, far cheaper and more accurate than reading files. Dig deeper
with `livingui <project_id> schema <table>`. Then read only the files you
actually intend to change:

1. **`{project.path}/LIVING_UI.md`** - overview, data models, API endpoints, components
2. **Source files relevant to the change:**

| What to change | Read first |
|----------------|------------|
| Data models / DB schema | `backend/models.py` |
| API endpoints / backend logic | `backend/routes.py` |
| TypeScript types | `frontend/types.ts` |
| UI components | `frontend/components/MainView.tsx` and relevant component files |
| State management / API calls | `frontend/AppController.ts` |
| Port / project config | `config/manifest.json` |

Understand the existing patterns, naming conventions, and code style before editing.

### Phase 3: Plan Changes

Identify all files that need modification. Changes often cascade:

```
New data field  → models.py → routes.py → types.ts → AppController.ts → Component
New feature     → models.py → routes.py → types.ts → AppController.ts → New component → MainView.tsx
UI-only change  → Component file(s) only
Bug fix         → Whichever file has the bug
```

If the change adds or removes a side-effectful capability (an endpoint that
DOES something beyond CRUD), also update `config/operations.json` so the
capability stays discoverable in `livingui <project> --help` — see the
living-ui-creator skill's `references/OPERATIONS.md` for the format.

Schema changes: new model columns/tables are migrated automatically when the
project restarts (`livingui <project_id> restart`, or the `living_ui_restart`
action). Restart BEFORE seeding data into new columns — never seed first.

### Phase 4: Make Changes

#### Backend Changes

**Edit: `backend/models.py`**

- Add/modify SQLAlchemy models
- NEVER use `metadata` as column name (SQLAlchemy reserved)
- Always include `to_dict()` method for JSON serialization
- If adding a new model, new table is auto-created on restart

```python
# Adding a field to existing model
class Todo(Base):
    __tablename__ = "todos"
    # ... existing fields ...
    priority = Column(String(20), default="medium")  # NEW FIELD

    def to_dict(self):
        return {
            # ... existing fields ...
            "priority": self.priority,  # ADD TO DICT
        }
```

**Edit: `backend/routes.py`**

- Add/modify API endpoints
- If model name conflicts with Python built-ins, use alias: `from models import List as ListModel`
- Always call `db.commit()` after write operations
- Return proper HTTP status codes (404 for not found, etc.)

```python
# Adding a new endpoint
@router.post("/todos/{todo_id}/archive")
def archive_todo(todo_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    todo.archived = True
    db.commit()
    return todo.to_dict()
```

#### Update/Add Backend Tests

**Edit: `backend/tests/`**

- Update existing tests if you changed models or routes
- Add new tests for any new endpoints or business logic
- Tests use a temp in-memory DB (`conftest.py` handles this)
- The launch pipeline runs `pytest tests/` and blocks if tests fail

```python
def test_archive_todo(client):
    """Archive endpoint should set archived=True."""
    todo = client.post("/api/todos", json={"title": "My Todo"}).json()
    response = client.post(f"/api/todos/{todo['id']}/archive")
    assert response.status_code == 200
    assert response.json()["archived"] == True
```

#### Frontend Changes

**Edit: `frontend/types.ts`**

- Keep TypeScript interfaces in sync with backend models
- Use camelCase in types (backend `to_dict()` should output camelCase)

```typescript
export interface Todo {
  id: number
  title: string
  priority: string  // NEW FIELD
}
```

**Edit: `frontend/AppController.ts`**

- Add methods for new backend endpoints
- Follow existing patterns for API calls and state updates
- For the backend URL, use: `const BACKEND_URL = (window as any).__CRAFTBOT_BACKEND_URL__ || 'http://localhost:3101'`
- NEVER hardcode a specific port — the port may change between launches

```typescript
async archiveTodo(id: number): Promise<void> {
  await fetch(`${this.backendUrl}/todos/${id}/archive`, { method: 'POST' })
  await this.fetchTodos()  // Refresh list
}
```

**Edit: `frontend/components/`**

- Modify existing or create new React components
- **Use preset UI components** - import from `./components/ui`:

| Category | Components |
|----------|------------|
| **Forms** | `Input`, `Textarea`, `Select`, `Checkbox`, `Toggle` |
| **Buttons** | `Button` (variants: primary, secondary, danger, ghost) |
| **Layout** | `Card`, `Container`, `Divider` |
| **Feedback** | `Alert`, `Badge`, `EmptyState`, `toast` (react-toastify) |
| **Data** | `Table`, `List`, `ListItem` |
| **Overlays** | `Modal`, `Tabs`, `TabList`, `Tab`, `TabPanel` |

```tsx
import { Button, Card, Badge, Modal } from './components/ui'
import { toast } from 'react-toastify'

// Use toast for user feedback on actions
toast.success('Item updated')
toast.error('Failed to delete')
```

**Edit: `frontend/components/MainView.tsx`**

- Wire new components into the main view
- Connect event handlers to controller methods

### Phase 5: Review Code

Review your changes for correctness before restarting:
- Backend routes use **absolute imports** (`from models import ...` NOT `from . import ...`)
- Backend `routes.py` does NOT add `/api` prefix to route paths
- All `to_dict()` methods return all fields

**DO NOT** run `npm run build`, `python -c "from models import *"`, or start servers manually.

### Phase 6: Restart

Use the `living_ui_restart` action to apply changes:

```
living_ui_restart(project_id="{project.id}")
```

This stops both backend and frontend, runs the launch pipeline (install dependencies, run tests, build frontend, health checks), and relaunches on the same ports. If there are errors, it reports them.

**DO NOT** use `living_ui_notify_ready` — it's for initial launch only.
**DO NOT** start uvicorn or npm preview manually.

### Phase 7: Update Documentation (MANDATORY)

**Edit: `{project.path}/LIVING_UI.md`** — you MUST update all affected sections:

- **Data Model** table if models changed (add/remove/modify rows)
- **API Endpoints** table if routes changed (add/remove/modify rows)
- **Frontend Components** table if components added/removed
- **Key Files** table if new files created
- Remove any remaining HTML comments (`<!-- ... -->`) or placeholder data
- **DO NOT call `living_ui_restart` until LIVING_UI.md is updated**

## Directory Structure

```
{project.path}/
├── backend/
│   ├── main.py          # FastAPI entry point (rarely edit)
│   ├── models.py        # SQLAlchemy models
│   ├── routes.py        # API endpoints
│   ├── database.py      # DB connection (rarely edit)
│   └── living_ui.db     # SQLite database
├── frontend/
│   ├── App.tsx           # Root component (rarely edit)
│   ├── AppController.ts  # State management & API calls
│   ├── types.ts          # TypeScript interfaces
│   ├── components/
│   │   ├── ui/index.tsx  # Preset components (DO NOT edit)
│   │   └── MainView.tsx  # Main UI component
│   ├── services/
│   │   ├── ApiService.ts # Backend HTTP client
│   │   └── UICapture.ts  # UI capture for agent (rarely edit)
│   └── styles/global.css # Design tokens (rarely edit)
├── config/manifest.json  # Ports and project metadata
└── LIVING_UI.md          # Documentation index
```

## External Integrations (Google, Discord, Slack, etc.)

If the user asks to connect to an external service (Gmail, YouTube, Discord, Slack, etc.),
use the built-in integration bridge — **do NOT build OAuth flows or ask for API keys.**

CraftBot already has connected accounts. Use `backend/services/integration_client.py`:

```python
from services.integration_client import integration

# Check what's connected
integrations = await integration.get_integrations()

# Make an authenticated API call (CraftBot injects credentials)
result = await integration.request(
    integration="google_workspace",
    method="GET",
    url="https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=10",
)
```

**Available:** google_workspace, slack, discord, notion, telegram, github, jira, linkedin, twitter, outlook, whatsapp

If `integration_client.py` doesn't exist in the project, create it from the template at `backend/services/integration_client.py`.

## FORBIDDEN Actions

- NEVER implement OAuth or credential management — use the integration bridge
- NEVER ask users for API keys — CraftBot already has their connected accounts
- NEVER use `metadata` as a SQLAlchemy column name
- NEVER use relative imports in backend code (`from . import` or `from .models import`)
- NEVER add `/api` prefix to route paths in `routes.py` (the router prefix handles this)
- NEVER run `npm run dev`, `npm run build`, `npm run preview`, or `uvicorn` manually
- NEVER store important state only in React (use backend)
- NEVER edit `frontend/components/ui/index.tsx` (preset components)
- NEVER use `send_message` - this is a background task

## Debugging & Logs

When something goes wrong, check these log files in the project directory:

| Log File | Contains |
|----------|----------|
| `backend/logs/subprocess_output.log` | Uvicorn startup output, crashes, stack traces |
| `backend/logs/backend_*.log` | Backend app-level logs (requests, errors, SQL) |
| `backend/logs/frontend_console.log` | Frontend console errors, warnings, app logs, and network requests (fetch method, URL, status, request/response bodies) |
| `backend/logs/health_status.json` | Health checker status (last check, failures) |
| `logs/frontend_output.log` | Vite preview server output |

**Read these logs first** when debugging issues after modifications.

## Quality Checklist

Before calling `living_ui_restart`:

- [ ] Backend uses absolute imports (`from models import ...`)
- [ ] Route paths don't have `/api` prefix (e.g., `@router.get("/items")`)
- [ ] New endpoints handle errors (404 for not found, etc.)
- [ ] `to_dict()` updated if model fields changed
- [ ] Types in `types.ts` match backend output
- [ ] LIVING_UI.md updated with changes
- [ ] (Pipeline handles build/test verification automatically)

## References

These reference files from the creator skill also apply to modifications:

- [Quality Standards](../living-ui-creator/references/STANDARDS.md) - UI, backend, and code quality standards
- [Code Examples](../living-ui-creator/references/EXAMPLES.md) - Complete code examples for each layer
- [Component Reference](../living-ui-creator/references/COMPONENTS.md) - Full preset component API reference
- [Troubleshooting](../living-ui-creator/references/TROUBLESHOOTING.md) - Common errors and fixes
- [Verification Checklist](../living-ui-creator/references/VERIFY.md) - Detailed QA checklist
