# Troubleshooting Guide

Quick diagnostics and fixes for common Living UI issues.

---

## Log Files

When something goes wrong, check these log files in the project directory:

| Log File | Contains |
|----------|----------|
| `backend/logs/subprocess_output.log` | PocketBase startup output, crashes, stack traces |
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

- **npm imports / node APIs in hooks** — `pb_hooks/main.pb.js` runs in PocketBase's embedded JS VM (goja): NO `import`/`require`, NO node APIs. Use the ambient globals `$app`, `$os`, `$http`, `$security`.
- **Path prefix confusion** — `routerAdd` takes the FULL path including the prefix: `routerAdd("POST", "/api/custom/archive-done", ...)`. The frontend `ApiService.request` takes the path WITHOUT `/api`: `ApiService.request('POST', '/custom/archive-done', {...})`.
- **Running servers/builds manually** — NEVER start pocketbase, npm run dev/build/preview. The pipeline installs, builds, and serves; write-time feedback already runs `tsc` for you.
- **EntityForm/EntityTable take the SCHEMA name** (`entity="Card"`), while `useEntities` takes the route plural (`'cards'`). Mixing them up is a compile error (and the runtime error names the right value).

---

## Quick Diagnostics

### 1. Backend hook check

Hook errors surface at startup: after editing `pb_hooks/main.pb.js`, run
`livingui <project> restart`, then `livingui <project> logs --tail 50` —
a JS error names the file and line. Then PROVE each custom route with a
curl against the running api URL (`livingui <project> status`).

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

### Missing $app.save() in a CUSTOM route (Data Not Saved!)
```js
// WRONG - the change never persists
card.set("archived", true)

// RIGHT - save the record
card.set("archived", true)
$app.save(card)
```
(PocketBase CRUD persists automatically — this applies to pb_hooks/main.pb.js only.)

### PocketBase returns 403 on CRUD
Collection rules default to locked. Every collection in
`config/schema.json` must declare public rules — `"listRule": "",
"viewRule": "", "createRule": "", "updateRule": "", "deleteRule": ""`.
If they are set and you still get 403, the schema was not re-imported:
rewrite `config/schema.json` (writes trigger the import) or restart.

### PocketBase returns 400 on create
A required field is missing, or a `relation` field got an invalid value —
relations take the STRING record id of an EXISTING record in the related
collection. Also: never declare `id`/`created`/`updated` in schema.json;
they are automatic.

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
1. For schema entities this CANNOT drift — field names appear on the wire
   EXACTLY as declared in `config/schema.json`, and `frontend/types.gen.ts`
   is generated from the same schema. Import types from types.gen, never
   hand-write them.
2. For CUSTOM endpoints: return camelCase keys from pb_hooks/main.pb.js to match
   the response types you declared in `types.ts`.

```js
// In a pb_hooks/main.pb.js custom endpoint
return e.json(200, {
  id: card.id,
  createdAt: card.get("created"),   // camelCase keys!
  userName: card.get("userName"),
})
```

---

### State lost after page refresh

**Cause:** Backend not saving or frontend not fetching

**Fix Checklist:**
- [ ] Custom routes call `$app.save(record)` after mutating records
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
3. Frontend should use the provided clients (`api.gen` for entities,
   `ApiService.request` for `/api/custom/*` endpoints) — they already
   resolve the backend URL

---

### API returns empty array but database has data

**Cause:** Query filter issue or wrong table

**Diagnosis:**
```bash
livingui <project> select cards --limit 5
livingui <project> sql "SELECT COUNT(*) FROM cards"
```
(Tables are the collection names from `config/schema.json`; the CLI's
`schema` command lists them.)

**Fix:** Check the filters you pass to `useEntities`/the list endpoint, or
your custom route's query.

---

### UI shows but buttons don't work

**Cause:** Event handlers not connected

**Fix Checklist:**
- [ ] Every control has a real handler — `onClick={() => {}}` stubs are forbidden
- [ ] The handler actually calls `useEntities.create/update/remove`, the typed `api.<collection>.*` client from api.gen, or `ApiService.request` (`/api/custom/*` endpoints only)
- [ ] No TypeScript errors silently breaking the module (read the write-result feedback)

```tsx
// A wired control: real handler → API call → view refresh
<Button size="sm" variant="destructive"
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
livingui <project> api GET /api/collections/cards/records   # probe any endpoint
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
2. Endpoint returns them? → `livingui <project> api GET /api/collections/<name>/records`
3. Types match? → read the write-result tsc feedback
4. Component renders them? → `livingui <project> snapshot`
5. Still confused? → add a temporary `console.log` (it lands in
   frontend_console.log) and remove it after

---

## Quick Fixes Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| Validate fails at frontend.build | TypeScript errors | Fix every error in the returned list |
| State lost on refresh | Missing $app.save() / local-only state | Save records in custom routes; use useEntities |
| "undefined" errors | Null state access | Add optional chaining `?.` |
| CORS errors | Port mismatch | Check manifest.json ports |
| Empty responses | Wrong filters/table | `livingui select` / `sql` to inspect |
| Buttons don't work | Stub handlers | Wire real handlers to the data layer |
| Type mismatch | Hand-written entity types | types.gen for entities; camelCase from custom routes |
| unknown entity "xyz" at render | Route plural passed to EntityForm/Table | Use the SCHEMA name (`entity="Card"`) |
