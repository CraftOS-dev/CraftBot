# Living UI Quality Standards

Every Living UI must meet the standards of a **real application**, not a demo.

---

## 1. Data Persistence Standards

### When Database is Required

- User creates/modifies data → **MUST persist**
- User preferences/settings → **MUST persist**
- Progress/state that shouldn't reset → **MUST persist**

### Database Design Rules

- Every model needs: `id` (primary key), `created_at`
- Use meaningful table/column names
- Add indexes for frequently queried columns
- Never use `metadata` as column name (SQLAlchemy reserved)
- Always include `to_dict()` method for JSON serialization

### Persistence Verification

Before completion, verify:
1. Add an item → Refresh page → Item still exists
2. Modify an item → Close browser → Reopen → Change persists
3. Delete an item → It's gone permanently

---

## 2. Frontend Standards

### Responsive Design (REQUIRED)

Every Living UI **MUST** work on:
- **Desktop:** 1200px+
- **Tablet:** 768px - 1199px
- **Mobile:** 320px - 767px

**Implementation:**
```css
/* Use flexible layouts */
.container {
  width: 100%;
  max-width: 1200px;
  padding: 0 16px;
  margin: 0 auto;
}

/* Use CSS Grid or Flexbox */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

/* Media queries for breakpoints */
@media (max-width: 768px) {
  .sidebar { display: none; }
}
```

**Rules:**
- Use relative units (%, rem, vh/vw)
- Test at 320px, 768px, and 1200px widths
- No horizontal scrolling on mobile
- Touch targets minimum 44x44px on mobile

### Visual Standards

- **Spacing:** Use 4px/8px/16px/24px/32px scale
- **Typography:** Minimum 14px for body text, 16px preferred
- **Contrast:** 4.5:1 ratio for text (WCAG AA)
- **Hierarchy:** Clear visual distinction between headings, body, captions
- **Colors:** Consistent palette, max 3-4 primary colors

### UX Standards

| State | Required | Example |
|-------|----------|---------|
| Loading | ✓ | Spinner or skeleton while fetching |
| Empty | ✓ | "No items yet. Add one!" message |
| Error | ✓ | Red text with clear message |
| Hover | ✓ | Visual feedback on interactive elements |
| Focus | ✓ | Visible outline for keyboard navigation |
| Disabled | ✓ | Grayed out, no pointer events |
| Success | Recommended | Green checkmark or toast |

### Form Standards

- Labels for all inputs (not just placeholders)
- Validation feedback inline, not alerts
- Submit button disabled during submission
- Clear error messages next to invalid fields
- Tab navigation works correctly
- Enter key submits forms

---

## 3. Backend Standards

### API Design

| Convention | Rule |
|------------|------|
| GET | Read data (no side effects) |
| POST | Create new resource |
| PUT | Update existing resource |
| DELETE | Remove resource |
| Response | Always JSON |
| Errors | Include message in body |

### HTTP Status Codes

| Code | When to Use |
|------|-------------|
| 200 | Success (GET, PUT, DELETE) |
| 201 | Created (POST) |
| 400 | Bad request (validation failed) |
| 404 | Resource not found |
| 500 | Server error (should never happen) |

### Error Handling

```python
# Good error handling
@router.get("/items/{item_id}")
def get_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Item not found"  # User-friendly message
        )
    return item.to_dict()
```

**Rules:**
- Never expose stack traces to frontend
- Log errors server-side
- Return user-friendly error messages
- Handle edge cases (empty inputs, invalid IDs)
- **Every route gets a one-line docstring** stating what it does — it becomes
  the OpenAPI summary AND the generated CLI operation description
  (`ops-sync` reads it). A route without a docstring produces an unusable op.

### Performance

- Paginate large datasets (50+ items)
- Don't load unnecessary data
- Use database indexes for frequent queries

### Bulk Endpoints (REQUIRED)

Every list resource MUST have a bulk-create endpoint so callers (and agents)
can write N records in one request:

```python
@router.post("/tasks/bulk")
def create_tasks_bulk(tasks: List[TaskCreate], db: Session = Depends(get_db)):
    created = [Task(**t.dict()) for t in tasks]
    db.add_all(created)
    db.commit()
    return {"created": len(created)}
```

Give every list resource `POST /api/{resource}/bulk` (accepts a JSON array, one transaction). One request for 100 records,
never 100 requests.

### Declared Operations (REQUIRED)

Every side-effectful capability (beyond plain CRUD) MUST be registered in
`config/operations.json` so agents can discover and fire it via the
livingui CLI (`livingui <project> run <op>`). Do NOT hand-author it: after
the first launch run `livingui <id> ops-sync --write` (generates exact
paths/params from your schemas), curate the descriptions, then
`livingui <id> ops-check` until clean. An undeclared capability is
invisible to future agent sessions; the launch pipeline blocks manifest
errors and warns on uncovered routes.

---

## 4. Code Quality Standards

### TypeScript

```typescript
// BAD - no types
const handleClick = (item) => { ... }

// GOOD - fully typed
const handleClick = (item: Item): void => { ... }
```

**Rules:**
- No `any` types (unless absolutely necessary)
- Interfaces for all data structures
- Props typed for all components
- Return types on functions

### Python

```python
# BAD - no types, bare except
def get_items(db):
    try:
        return db.query(Item).all()
    except:
        return []

# GOOD - typed, specific exception
def get_items(db: Session) -> List[Dict]:
    try:
        return [i.to_dict() for i in db.query(Item).all()]
    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Database error")
```

### General

- No commented-out code
- No `console.log` in production (use sparingly in dev)
- No hardcoded secrets/URLs
- Meaningful variable names
- No TODO comments left unaddressed

---

## 5. Agent Integration Standards

### State Reporting (UI → Agent)

```typescript
// Register component state for agent visibility
useAgentAware('TodoList', {
  itemCount: items.length,
  completedCount: items.filter(i => i.done).length
})
```

**Rules:**
- Register key components with `useAgentAware()`
- Include meaningful state (not just raw data dumps)
- Keep payloads reasonable (<10KB)

### Command Handling (Agent → UI)

```typescript
// Handle agent commands
useAgentCommand((command) => {
  switch (command.type) {
    case 'refresh':
      controller.refresh()
      break
    case 'action':
      controller.executeAction(command.payload)
      break
  }
})
```

**Rules:**
- Handle refresh, update, action commands
- Graceful degradation if agent disconnected
- Don't block UI waiting for agent

### Agent Data Access (Agent ↔ Backend)

- Provide `/api/state` endpoint for full state access
- Create endpoints for any data agent might need
- Consider `/api/stats` for summary data
- Document which endpoints are agent-accessible

---

## 6. Testing Checklist

Before marking complete, verify ALL:

### Functional
- [ ] All CRUD operations work
- [ ] State persists after page refresh
- [ ] State persists after browser close/reopen

### Responsive
- [ ] Works at 320px width (mobile)
- [ ] Works at 768px width (tablet)
- [ ] Works at 1200px width (desktop)
- [ ] No horizontal scrolling

### UX States
- [ ] Loading state shows during fetch
- [ ] Empty state displays when no data
- [ ] Error messages display on failures

### Quality
- [ ] No console errors
- [ ] No TypeScript errors
- [ ] Build succeeds (exit code 0)

### Agent
- [ ] Key components registered with useAgentAware()
- [ ] Agent commands handled appropriately

---

## Quick Reference

### Must Have (Blocking)

1. Data persists across refreshes
2. UI works on mobile (320px)
3. Loading states for async operations
4. No console errors
5. Build succeeds

### Should Have (Quality)

1. Empty states when no data
2. Confirmation for destructive actions
3. Keyboard navigation works
4. Consistent visual design
5. Agent integration
