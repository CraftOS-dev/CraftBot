# Troubleshooting Guide

Quick diagnostics and fixes for common Living UI issues.

---

## Log Files

When something goes wrong, check these log files in the project directory:

| Log File | Contains |
|----------|----------|
| `backend/logs/subprocess_output.log` | Uvicorn startup output, crashes, stack traces |
| `backend/logs/backend_*.log` | Backend app-level logs (requests, unhandled 500s, SQL) |
| `backend/logs/frontend_console.log` | Frontend console errors, warnings, app logs, and network requests |
| `backend/logs/test_discovery.json` | Pre-launch test results (imports, routes, models) |
| `backend/logs/test_results.json` | External smoke test results |
| `logs/schedule.log` / `logs/schedule_state.json` | Scheduled-op results and last-run state |
| `logs/dev_preview.log` | Live-preview npm install / Vite dev server output |

**Read these logs first** when debugging launch failures or runtime issues.
Validation's `runtime.logs` step reads the first three too — an ERROR
recorded there during validation refuses the launch.

---

## Common Mistakes

- **Relative imports** — NEVER use `from . import models` or `from .models import ...` in backend code. Use absolute imports: `from models import ...`
- **Double /api prefix** — Routes in `routes.py` should NOT have `/api` prefix (e.g., use `@router.get("/cards/archive")` not `@router.get("/api/cards/archive")`). The prefix is added by `main.py`'s `include_router`.
- **Running servers/builds manually** — NEVER start uvicorn, npm run dev/build/preview. The pipeline installs, builds, and serves; write-time feedback already runs `tsc` for you.
- **EntityForm/EntityTable take the SCHEMA name** (`entity="Card"`), while `useEntities` takes the route plural (`'cards'`). Mixing them up is a compile error (and the runtime error names the right value).

---

## Quick Diagnostics

### 1. Backend import check (read-only, safe)

```bash
cd backend && python -c "from models import *; from routes import *; print('Backend OK')"
```

If this fails, you have Python/import errors — the traceback names the file.

### 2. TypeScript errors

You do NOT run tsc manually in a loop — every frontend write already
returns the COMPLETE current error list in the write result. Fix all of
them in your next step. (A one-off `npx tsc --noEmit` is fine while
debugging a confusing type issue.)

### 3. Everything else

`living_ui_validate` runs the full pipeline (install, tests, build, smoke,
runtime logs, design) and returns the complete error list. Don't rebuild
its steps by hand.

---

## Common Errors & Fixes

### Missing db.commit() in a CUSTOM route (Data Not Saved!)
```python
# WRONG - changes not saved
db.add(item)
return item.to_dict()

# RIGHT - commit to save
db.add(item)
db.commit()
return item.to_dict()
```
(Generated CRUD commits automatically — this applies to routes.py only.)

### Reserved field names in schema.json
```json
// WRONG — 'metadata' collides with SQLAlchemy internals; id/createdAt/
// updatedAt are automatic and must never be declared
{"fields": {"metadata": {"type": "json"}, "id": {"type": "integer"}}}

// RIGHT
{"fields": {"extraData": {"type": "json"}}}
```

### Non-responsive Frontend
```css
/* WRONG - fixed width breaks mobile */
.container { width: 800px; }

/* RIGHT - responsive */
.container {
  width: 100%;
  max-width: 800px;
  padding: 0 16px;
}
```
(Preset components and skeletons are already adaptive — this applies to
your own scoped styles.)

### No Loading State

`useEntities` gives you `loading` for free:

```tsx
const cards = useEntities<Card>('cards')
if (cards.loading) return <SkeletonRow count={3} />
```

### Frontend-Only State (Data Loss!)
```typescript
// WRONG - lost on refresh
const [todos, setTodos] = useState([])

// RIGHT - backed by the database via the generated API
const todos = useEntities<Todo>('todos')
```

### Wrong Project ID
```python
# WRONG - using task session ID
living_ui_notify_ready(project_id="Create_Living_UI_MyApp_abc123", ...)

# RIGHT - using project ID from task instruction
living_ui_notify_ready(project_id="c8cda731", ...)
```

### "Cannot read property 'X' of undefined"

**Cause:** Accessing state before it's loaded

**Fix:** Add optional chaining or default values

```typescript
// BAD - crashes if items is undefined
items.map(item => ...)

// GOOD - safe access
(items || []).map(item => ...)

// BETTER - optional chaining with fallback
items?.map(item => ...) ?? []
```

---

### TypeScript type errors on API response

**Cause:** Backend returns different shape than your types

**Fix:**
1. For schema entities this CANNOT drift — the wire format is camelCase by
   the engine and `frontend/types.gen.ts` is generated from the same
   schema. Import types from types.gen, never hand-write them.
2. For CUSTOM endpoints: return camelCase keys from routes.py to match
   the response types you declared in `types.ts`.

```python
# In a routes.py custom endpoint
return {
    "id": row.id,
    "createdAt": row.created_at.isoformat(),  # camelCase!
    "userName": row.user_name,  # camelCase!
}
```

---

### State lost after page refresh

**Cause:** Backend not saving or frontend not fetching

**Fix Checklist:**
- [ ] Custom routes call `db.commit()` after changes
- [ ] The component reads via `useEntities` (or `data.list`) — not a local useState
- [ ] Custom routes return the SAVED object (not the input data)

---

### Build fails with import errors

**Cause:** Circular imports or missing exports

**Fix:**
- Check import paths are correct (relative vs absolute)
- Ensure all used items are exported from their modules
- Entity types come from `../types.gen`; only app-specific NON-entity
  types live in `types.ts`

```typescript
// BAD - importing an entity type from a component
import { Card } from './CardList'

// GOOD - entity types are generated
import type { Card } from '../types.gen'
```

---

### CORS errors in browser console

**Cause:** Frontend/backend URL mismatch

**Fix:**
1. Check `manifest.json` ports match actual running services
2. Verify backend CORS is configured (should be by default)
3. Frontend should use the provided clients (`services/data.ts`,
   `ApiService`) — they already resolve the backend URL

---

### API returns empty array but database has data

**Cause:** Query filter issue or wrong table

**Diagnosis:**
```bash
livingui <project> select cards --limit 5
livingui <project> sql "SELECT COUNT(*) FROM card"
```
(Table names are snake_case singular on disk; the CLI's `schema` command
lists them.)

**Fix:** Check the filters you pass to `useEntities`/the list endpoint, or
your custom route's query.

---

### UI shows but buttons don't work

**Cause:** Event handlers not connected

**Fix Checklist:**
- [ ] Every control has a real handler — `onClick={() => {}}` stubs are forbidden
- [ ] The handler actually calls `useEntities.create/update/remove`, `data.*`, or ApiService (custom endpoints)
- [ ] No TypeScript errors silently breaking the module (read the write-result feedback)

```tsx
// A wired control: real handler → API call → view refresh
<Button size="sm" variant="danger"
  onClick={async () => { if (await confirm('Delete?')) await cards.remove(card.id) }}>
  Delete
</Button>
```

---

## Operating & Debugging a Running App

The platform runs all servers. To poke a live app, use the CLI:

```bash
livingui <project> status                 # ports, health, uptime
livingui <project> logs --tail 50         # recent backend log
livingui <project> snapshot               # what the user sees (DOM/text)
livingui <project> screenshot --out s.png # visual check (describe_image)
livingui <project> api GET /api/cards     # probe any endpoint
livingui <project> run <op>               # exercise declared behavior
livingui <project> restart                # relaunch after code changes
```

---

## Debugging Tips

### Check the captured console first

`backend/logs/frontend_console.log` already contains the browser's
errors, warnings, and failed network requests — you rarely need DevTools.

### Verify data flow in isolation

1. Rows exist? → `livingui <project> select <table> --limit 5`
2. Endpoint returns them? → `livingui <project> api GET /api/<plural>`
3. Types match? → read the write-result tsc feedback
4. Component renders them? → `livingui <project> snapshot`
5. Still confused? → add a temporary `console.log` (it lands in
   frontend_console.log) and remove it after

---

## Quick Fixes Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| Validate fails at frontend.build | TypeScript errors | Fix every error in the returned list |
| State lost on refresh | Missing db.commit() / local-only state | Commit in custom routes; use useEntities |
| "undefined" errors | Null state access | Add optional chaining `?.` |
| CORS errors | Port mismatch | Check manifest.json ports |
| Empty responses | Wrong filters/table | `livingui select` / `sql` to inspect |
| Buttons don't work | Stub handlers | Wire real handlers to the data layer |
| Type mismatch | snake_case vs camelCase | types.gen for entities; camelCase from custom routes |
| unknown entity "xyz" at render | Route plural passed to EntityForm/Table | Use the SCHEMA name (`entity="Card"`) |
