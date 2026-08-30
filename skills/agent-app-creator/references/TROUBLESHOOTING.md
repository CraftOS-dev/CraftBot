# Troubleshooting Guide

Quick diagnostics and fixes for common Agent App issues.

---

## Log Files

When something goes wrong, check these log files in the project directory:

| Log File | Contains |
|----------|----------|
| `backend/logs/subprocess_output.log` | Uvicorn startup output, crashes, stack traces |
| `backend/logs/backend_*.log` | Backend app-level logs (requests, errors, SQL) |
| `backend/logs/frontend_console.log` | Frontend console errors, warnings, app logs, and network requests |
| `backend/logs/test_discovery.json` | Pre-launch test results (imports, routes, models) |
| `backend/logs/test_results.json` | External smoke test results |
| `logs/frontend_output.log` | Vite preview server output |

**Read these logs first** when debugging launch failures or runtime issues.

---

## Common Mistakes

- **Relative imports** — NEVER use `from . import models` or `from .models import ...` in backend code. Use absolute imports: `from models import ...`
- **Double /api prefix** — Routes in `routes.py` should NOT have `/api` prefix (e.g., use `@router.get("/items")` not `@router.get("/api/items")`). The prefix is added by `main.py`'s `include_router`.
- **Running servers manually** — NEVER start uvicorn, npm run dev, or npm run preview. The pipeline handles this.

---

## Quick Diagnostics

### 1. Backend Check

```bash
cd backend && python -c "from models import *; from routes import *; print('Backend OK')"
```

If this fails, you have Python/import errors.

### 2. Frontend Type Check

```bash
npx tsc --noEmit
```

If this fails, you have TypeScript errors.

### 3. Build Check

```bash
npm run build
echo $?  # Should print 0
```

If exit code is not 0, build failed.

---

## Common Errors & Fixes

### Missing db.commit() (Data Not Saved!)
```python
# WRONG - changes not saved
db.add(item)
return item.to_dict()

# RIGHT - commit to save
db.add(item)
db.commit()
return item.to_dict()
```

### SQLAlchemy Reserved Names
```python
# WRONG - will crash
metadata = Column(JSON)

# RIGHT
extra_data = Column(JSON)
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

### No Loading State
```typescript
// WRONG - jarring UX
const items = await fetch('/api/items')

// RIGHT - user sees loading
setState({ loading: true })
const items = await fetch('/api/items')
setState({ loading: false, items })
```

### Frontend-Only State (Data Loss!)
```typescript
// WRONG - lost on refresh
const [todos, setTodos] = useState([])

// RIGHT - fetched from backend
const todos = await fetch('/api/todos').then(r => r.json())
```

### Wrong Project ID
```python
# WRONG - using task session ID
agent_app_notify_ready(project_id="Create_Agent_App_MyApp_abc123", ...)

# RIGHT - using project ID from task instruction
agent_app_notify_ready(project_id="c8cda731", ...)
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

**Cause:** Backend returns different shape than types.ts

**Diagnosis:**
```bash
# Check actual API response
curl http://localhost:PORT/api/items | head
```

**Fix:**
1. Compare response to types.ts interface
2. Backend uses snake_case, TypeScript expects camelCase
3. Update `to_dict()` to use camelCase keys

```python
# In models.py
def to_dict(self):
    return {
        "id": self.id,
        "createdAt": self.created_at.isoformat(),  # camelCase!
        "userName": self.user_name,  # camelCase!
    }
```

---

### State lost after page refresh

**Cause:** Backend not saving or frontend not fetching

**Fix Checklist:**
- [ ] Route calls `db.commit()` after changes
- [ ] `AppController.initialize()` calls backend API
- [ ] Backend returns the saved object (not input data)

```python
# WRONG - missing commit
@router.post("/items")
def create_item(data: dict, db: Session = Depends(get_db)):
    item = Item(**data)
    db.add(item)
    return item.to_dict()  # NOT SAVED!


# RIGHT - with commit
@router.post("/items")
def create_item(data: dict, db: Session = Depends(get_db)):
    item = Item(**data)
    db.add(item)
    db.commit()  # SAVE TO DATABASE
    return item.to_dict()
```

---

### Build fails with import errors

**Cause:** Circular imports or missing exports

**Fix:**
- Check import paths are correct (relative vs absolute)
- Ensure all used items are exported from their modules
- Move shared types to `types.ts` to avoid circular deps

```typescript
// BAD - importing from component that imports this
import { Item } from './ItemList'

// GOOD - import from shared types
import { Item } from '../types'
```

---

### CORS errors in browser console

**Cause:** Frontend/backend URL mismatch

**Fix:**
1. Check `manifest.json` ports match actual running services
2. Verify backend CORS is configured (should be by default)
3. Frontend should use relative URLs or correct backend port

```typescript
// Check AppController or services for backend URL
const BACKEND_URL = `http://localhost:${backendPort}`
```

---

### "metadata" SQLAlchemy error

**Cause:** Using reserved column name

**Fix:** Rename the column

```python
# WRONG - 'metadata' is reserved
class Item(Base):
    metadata = Column(JSON)  # CRASHES


# RIGHT - use different name
class Item(Base):
    extra_data = Column(JSON)  # Works
```

---

### API returns empty array but database has data

**Cause:** Query filter issue or wrong table

**Diagnosis:**
```bash
# Check database directly
sqlite3 backend/agent_app.db "SELECT * FROM items;"
```

**Fix:** Check your query in routes.py
```python
# Make sure table name matches model
items = db.query(Item).all()  # Item must match __tablename__
```

---

### UI shows but buttons don't work

**Cause:** Event handlers not connected

**Fix Checklist:**
- [ ] onClick/onChange handlers are passed to components
- [ ] Handler functions exist in controller
- [ ] No TypeScript errors silently breaking the code

```typescript
// Check handlers are connected
<button onClick={() => controller.deleteItem(id)}>Delete</button>

// Make sure method exists in controller
class AppController {
  async deleteItem(id: string): Promise<void> {
    // Implementation here
  }
}
```

---

## Development Workflow

### Start Development Environment

```bash
# Terminal 1: Backend (PORT from config/manifest.json)
cd backend
uvicorn main:app --port PORT --reload

# Terminal 2: Frontend (dev server with hot reload)
npm run dev
```

### Test Backend Before Frontend

Before building UI, verify backend works (replace PORT with your backend port):

```bash
# Create
curl -X POST http://localhost:PORT/api/items \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Item"}'

# Read
curl http://localhost:PORT/api/items

# Update
curl -X PUT http://localhost:PORT/api/items/ITEM_ID \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated"}'

# Delete
curl -X DELETE http://localhost:PORT/api/items/ITEM_ID
```

### Build for Production

```bash
# Type check first
npx tsc --noEmit

# Build
npm run build

# Verify success
echo $?  # Must be 0
ls dist/  # Should have files
```

---

## Debugging Tips

### Check Browser Console

1. Open DevTools (F12)
2. Go to Console tab
3. Look for red errors
4. Check Network tab for failed requests

### Check Backend Logs

Backend prints errors to terminal. Look for:
- ImportError (missing module)
- SyntaxError (Python syntax issue)
- SQLAlchemyError (database issue)

### Verify State Flow

Add temporary logging:

```typescript
// In AppController
async fetchItems() {
  console.log('Fetching items...')
  const items = await ApiService.getItems()
  console.log('Got items:', items)
  await this.setState({ items })
  console.log('State updated')
}
```

### Test in Isolation

1. Backend works? → Test with curl
2. API returns correct data? → Check with curl
3. Types match? → Run tsc --noEmit
4. Component renders? → Check browser console
5. State updates? → Add console.log

---

## Quick Fixes Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| Build fails | TypeScript errors | Run `npx tsc --noEmit` |
| State lost on refresh | Missing db.commit() | Add `db.commit()` after changes |
| "undefined" errors | Null state access | Add optional chaining `?.` |
| CORS errors | Port mismatch | Check manifest.json ports |
| Empty responses | Wrong query | Check model __tablename__ |
| Buttons don't work | Missing handlers | Connect onClick to controller |
| Type mismatch | snake_case vs camelCase | Fix to_dict() output |
