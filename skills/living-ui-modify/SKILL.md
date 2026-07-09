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

(Full log-file table: the creator skill's `references/TROUBLESHOOTING.md`.)

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

`livingui ls` (via run_shell) lists every project with id, status, and type —
or read the registry file:

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

| What to change | Read/edit |
|----------------|-----------|
| Entities / DB schema | `config/schema.json` (THE data layer — declared, not coded) |
| Custom endpoints / backend behavior | `backend/routes.py` |
| App-specific NON-entity types | `frontend/types.ts` (entity types are GENERATED in `types.gen.ts` — import, never edit) |
| UI components | `frontend/components/MainView.tsx` and relevant component files |
| Custom-endpoint calls / orchestration | `frontend/services/ApiService.ts` usage, optional `AppController.ts` |
| Declared operations | `config/operations.json` |
| Port / project config | `config/manifest.json` |

Understand the existing patterns, naming conventions, and code style before editing.

### Phase 3: Plan Changes

Identify all files that need modification. Changes cascade much less than
they used to — the schema is declarative and entity types are generated:

```
New entity/field  → config/schema.json (types.gen.ts + CRUD API regenerate
                    automatically) → component edits only
New behavior      → routes.py (+ test) → declare op → component/ApiService
UI-only change    → Component file(s) only
Bug fix           → Whichever file has the bug (logs first!)
```

If the change adds or removes a side-effectful capability (an endpoint that
DOES something beyond CRUD), also update `config/operations.json` so the
capability stays discoverable in `livingui <project> --help` — after the
restart, `livingui <project> ops-sync --write` generates it from the route,
then curate the description and run `ops-check`. Format:
`references/OPERATIONS.md` in the creator skill.

Schema changes: new fields/entities are migrated automatically when the
project restarts (`livingui <project_id> restart`). Restart BEFORE seeding
data into new columns — never seed first.

### Phase 4: Make Changes

#### Backend Changes

**Edit: `config/schema.json`** — entities are DECLARED here; the engine
materializes models and full REST CRUD (list/filter/search/stats/bulk) at
startup. You never write a model class or CRUD route.

```json
{
  "entities": {
    "Todo": {
      "fields": {
        "title":    {"type": "string", "required": true},
        "priority": {"type": "enum", "values": ["low", "medium", "high"], "default": "medium"},
        "done":     {"type": "boolean", "default": false}
      }
    }
  }
}
```

- `id`, `createdAt`, `updatedAt` are automatic — never declare them
- NEVER use `metadata` as a field name (SQLAlchemy reserved)
- Full field-type reference: creator skill `references/BACKEND.md`
- Writing schema.json auto-regenerates `frontend/types.gen.ts`

**Edit: `backend/routes.py`** — CUSTOM behavior only (the one backend file
you hand-write):

- One-line docstring on every route (it becomes the op description)
- Always call `db.commit()` after write operations (generated CRUD commits
  automatically; this applies to routes.py only)
- Return camelCase keys and proper HTTP status codes

```python
@router.post("/todos/{todo_id}/archive")
def archive_todo(todo_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Archive one todo so it leaves the active list."""
    from models import Todo
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    todo.archived = True
    db.commit()
    return todo.to_dict()
```

#### Update/Add Backend Tests

**Edit: `backend/tests/`**

- Update existing tests if you changed the schema or routes
- Add new tests for any new endpoints or business logic
- Tests use a temp DB (`conftest.py` handles this)
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

**Entity types are GENERATED** — import from `types.gen.ts`, never
hand-write or edit them. Only app-specific NON-entity types live in
`types.ts`.

```typescript
import type { Todo } from '../types.gen'
```

**Data plumbing is PROVIDED** — `useEntities<T>(plural)` from
`services/data.ts` handles fetch/create/update/remove with auto-refresh.
Custom endpoints go through `ApiService`. Never hand-roll fetch + backend
URL plumbing.

```typescript
const todos = useEntities<Todo>('todos')          // route plural
// <EntityForm entity="Todo" />                    // SCHEMA name — not the plural!
await ApiService.post(`/todos/${id}/archive`, {}) // custom endpoint
```

**Edit: `frontend/components/`**

- Modify existing or create new React components
- **Use preset UI components** — ~65 presets in `./components/ui` (forms,
  tables, overlays, charts, skeletons, EntityForm/EntityTable, upload,
  toast...). Full API: creator skill `references/COMPONENTS.md`.

```tsx
import { Button, Card, Badge, Modal, toast } from './components/ui'

// Use toast for user feedback on actions (do NOT install react-toastify)
toast.success('Item updated')
toast.error('Failed to delete')
```

- **Every frontend write returns the COMPLETE current TypeScript/lint error
  list in the write result.** Fix all of them in your next step — do not
  run tsc in a loop.

**Edit: `frontend/components/MainView.tsx`**

- Wire new components into the main view
- Connect every control to a real handler (no stubs)

### Phase 5: Review Code

Review your changes for correctness before restarting:
- Backend routes use **absolute imports** (`from models import ...` NOT `from . import ...`)
- Backend `routes.py` does NOT add `/api` prefix to route paths
- Entity types imported from `types.gen.ts`, not hand-written
- Write-result feedback is clean (no outstanding tsc/lint errors)

A read-only import check is fine while debugging
(`cd backend && python -c "from models import *; from routes import *"`),
but **DO NOT** run `npm run build` or start servers manually — the restart
pipeline builds and verifies.

### Phase 6: Restart

Apply the changes with the CLI:

```
livingui <project_id> restart
```

(or the `living_ui_restart` action — same pipeline). This stops both
servers, runs the launch pipeline (migrate, install, tests, build, health
checks, smoke tests), and relaunches on the same ports. If there are
errors, it reports them — read ALL of them before fixing.

**DO NOT** use `living_ui_notify_ready` — it's for initial launch only.
**DO NOT** start uvicorn or npm preview manually.

### Phase 7: Update Documentation (MANDATORY)

**Edit: `{project.path}/LIVING_UI.md`** — you MUST update all affected sections:

- **Data Model** table if the schema changed (add/remove/modify rows)
- **API Endpoints** table if routes changed (add/remove/modify rows)
- **Frontend Components** table if components added/removed
- **Key Files** table if new files created
- Remove any remaining HTML comments (`<!-- ... -->`) or placeholder data
- **DO NOT restart until LIVING_UI.md is updated**

## Directory Structure

```
{project.path}/
├── backend/
│   ├── main.py            # FastAPI setup (SYSTEM — never edit)
│   ├── engine.py          # schema.json → models + CRUD API (SYSTEM — never edit)
│   ├── models.py          # Re-exports engine + system models (SYSTEM — never edit)
│   ├── system_routes.py   # A-layer: /state /action /ui-* (SYSTEM — never edit)
│   ├── files_routes.py    # File storage API (SYSTEM — never edit)
│   ├── routes.py          # CUSTOM endpoints — edit this
│   ├── database.py        # DB connection, .env DATABASE_URL (SYSTEM — never edit)
│   ├── services/          # integration_client.py, secrets.py
│   ├── tests/             # pytest suite — add tests here
│   ├── .env               # secrets (DATABASE_URL, API keys) — never print
│   └── living_ui.db       # SQLite database
├── frontend/
│   ├── App.tsx            # Root component (rarely edit)
│   ├── AppController.ts   # OPTIONAL app-specific orchestration
│   ├── types.gen.ts       # GENERATED entity types — import, never edit
│   ├── schema.gen.ts      # GENERATED entity metadata — never edit
│   ├── types.ts           # App-specific NON-entity types only
│   ├── components/
│   │   ├── ui/            # Preset components (SYSTEM — never edit)
│   │   └── MainView.tsx   # Main UI component
│   ├── services/
│   │   ├── data.ts        # useEntities + CRUD client (SYSTEM — never edit)
│   │   ├── ApiService.ts  # Client for CUSTOM endpoints
│   │   └── UICapture.ts   # UI capture for agent (SYSTEM — never edit)
│   └── styles/            # global.css tokens + themes.css style packs (rarely edit)
├── config/
│   ├── schema.json        # THE data layer — entities declared here
│   ├── operations.json    # Declared ops = the app's CLI verbs
│   └── manifest.json      # Ports and project metadata
└── LIVING_UI.md           # Documentation index
```

## Imported (external) apps

`livingui ls` shows TYPE `external` for imported third-party apps. Modifying
them is allowed HERE (import itself never touches app source), but:

- Keep changes minimal and local to the app's own patterns — you are editing
  someone else's codebase, not a template you know.
- The structure above does NOT apply — read the app's own layout first;
  `LIVING_UI.md` (written at import) is the map.
- After adding any capability, declare it in `config/operations.json`
  (`ops-sync --write` if the app serves an OpenAPI spec) — an undeclared
  capability is invisible to every future agent.
- Their manifest data block is READ-ONLY by default — write through the
  app's own API/ops unless `"writable": true` was verified and set.
- `livingui <project> restart` relaunches through the app's manifest
  pipeline (install/start/health) just like native restarts.

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

# In-app AI (CraftBot's LLM interface — no API key)
text = await integration.llm("Summarize this: ...")
caption = await integration.describe_image(image_b64)
```

**Available:** google_workspace, slack, discord, notion, telegram, github, jira, linkedin, twitter, outlook, whatsapp

If `integration_client.py` doesn't exist in the project (older projects), copy it from the template's `backend/services/integration_client.py`. Recipes: creator skill `references/INTEGRATIONS.md`.

## FORBIDDEN Actions

- NEVER implement OAuth or credential management — use the integration bridge
- NEVER ask users for API keys — CraftBot already has their connected accounts
- NEVER edit SYSTEM files: `engine.py`, `models.py`, `main.py`, `database.py`,
  `system_routes.py`, `files_routes.py`, `types.gen.ts`, `schema.gen.ts`,
  `services/data.ts`, `components/ui/`
- NEVER hand-write entity types or declare `id`/`createdAt`/`updatedAt`/`metadata` fields
- NEVER install or import `react-toastify` — `toast` comes from `./components/ui`
- NEVER use relative imports in backend code (`from . import` or `from .models import`)
- NEVER add `/api` prefix to route paths in `routes.py` (the router prefix handles this)
- NEVER run `npm run dev`, `npm run build`, `npm run preview`, or `uvicorn` manually
- NEVER store important state only in React (use the backend)
- NEVER use `send_message` - this is a background task

## Debugging & Logs

When something goes wrong, check these log files in the project directory:

| Log File | Contains |
|----------|----------|
| `backend/logs/subprocess_output.log` | Uvicorn startup output, crashes, stack traces |
| `backend/logs/backend_*.log` | Backend app-level logs (requests, errors, SQL) |
| `backend/logs/frontend_console.log` | Frontend console errors, warnings, app logs, and network requests (fetch method, URL, status) |
| `backend/logs/health_status.json` | Health checker status (last check, failures) |
| `logs/schedule.log` | Scheduled-op results |

**Read these logs first** when debugging issues after modifications. Full
table + diagnostics: creator skill `references/TROUBLESHOOTING.md`.

## Quality Checklist

Before restarting:

- [ ] Schema changes declared in `config/schema.json` (not models.py)
- [ ] Backend uses absolute imports (`from models import ...`)
- [ ] Route paths don't have `/api` prefix (e.g., `@router.get("/todos/archive")`)
- [ ] New endpoints handle errors (404 for not found, etc.) and have docstrings
- [ ] Entity types imported from `types.gen.ts`
- [ ] Write-result tsc/lint feedback is clean
- [ ] New/changed capabilities declared in `config/operations.json` (ops-sync after restart)
- [ ] LIVING_UI.md updated with changes
- [ ] (Pipeline handles build/test verification automatically)

## References

These reference files from the creator skill also apply to modifications:

- [Backend Deep-Dive](../living-ui-creator/references/BACKEND.md) - schema.json field types, engine API, external DB, file storage
- [Quality Standards](../living-ui-creator/references/STANDARDS.md) - UI, backend, and code quality standards
- [Code Examples](../living-ui-creator/references/EXAMPLES.md) - Complete code examples for each layer
- [Component Reference](../living-ui-creator/references/COMPONENTS.md) - Full preset component API reference
- [Operations Manifest](../living-ui-creator/references/OPERATIONS.md) - declared ops format, safe flag, schedules
- [MVC-A Architecture](../living-ui-creator/references/MVC-A.md) - layers, CLI, agent interface
- [Troubleshooting](../living-ui-creator/references/TROUBLESHOOTING.md) - Common errors and fixes
- [Verification Checklist](../living-ui-creator/references/VERIFY.md) - Detailed QA checklist
