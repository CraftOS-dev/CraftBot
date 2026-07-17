# Living UI Quality Standards

Every Living UI must meet the standards of a **real application**, not a demo.

---

## 1. Data Persistence Standards

### When Database is Required

- User creates/modifies data → **MUST persist**
- User preferences/settings → **MUST persist**
- Progress/state that shouldn't reset → **MUST persist**

### Database Design Rules

- Collections are DECLARED in `config/schema.json` — PocketBase provides
  string `id`, `created`/`updated`, and the full CRUD API automatically.
  You never write a model class.
- Use meaningful collection/field names (camelCase, used EXACTLY as
  declared on the wire and in `types.gen.ts`)
- Model relationships with `relation` fields (`collectionName`,
  `maxSelect: 1`, `cascadeDelete: true` when children die with the parent)

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
/* Fill the container — the page frame owns gutters (mx-auto max-w on
   <main>); never add your own competing max-width cap */
.container {
  width: 100%;
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

### Error Handling (custom routes — generated CRUD handles this itself)

```js
// Good error handling in a pb_hooks/main.pb.js custom endpoint
routerAdd("GET", "/api/custom/card-summary", (e) => {
  const id = e.requestInfo().query["cardId"]
  if (!id) return e.json(400, { error: "cardId is required" })
  let card
  try {
    card = $app.findRecordById("cards", id)
  } catch (_) {
    return e.json(404, { error: "Card not found" })  // User-friendly message
  }
  return e.json(200, { id: card.id, summary: "..." })
})
```

**Rules:**
- Never expose stack traces to frontend
- Log errors server-side
- Return user-friendly error messages
- Handle edge cases (empty inputs, invalid IDs)
- **Every custom route gets a declared op** in `config/operations.json`
  with a one-line description stating what it does and when to use it —
  agents discover and choose capabilities by reading it. A route without
  an op is invisible.

### Performance

- Paginate large datasets (50+ items)
- Don't load unnecessary data
- Use database indexes for frequent queries

### Bulk Work

For seeding or importing many records, loop `api.<collection>.create`
from the frontend, or — for true one-request bulk work — write a
`/api/custom/...` endpoint in `pb_hooks/main.pb.js` that creates the
records server-side. There is no generated `/bulk` route.

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

### pb_hooks JavaScript

```js
// BAD - unvalidated input, failure becomes an opaque 500 or a silent {}
routerAdd("POST", "/api/custom/archive", (e) => {
  const body = e.requestInfo().body
  const cards = $app.findRecordsByFilter(
    "cards", `columnId = '${body.columnId}'`, "-created", 500, 0)
  cards.forEach((c) => { c.set("archived", true); $app.save(c) })
  return e.json(200, { archived: cards.length })
})

// GOOD - validate params by hand, catch, return a clean error
routerAdd("POST", "/api/custom/archive", (e) => {
  const body = e.requestInfo().body
  if (!body.columnId) return e.json(422, { error: "columnId is required" })
  try {
    const cards = $app.findRecordsByFilter(
      "cards", `columnId = '${body.columnId}'`, "-created", 500, 0)
    cards.forEach((c) => { c.set("archived", true); $app.save(c) })
    return e.json(200, { archived: cards.length })
  } catch (err) {
    return e.json(500, { error: "archive failed" })
  }
})
```

### General

- No commented-out code
- No `console.log` in production (use sparingly in dev)
- No hardcoded secrets/URLs
- Meaningful variable names
- No TODO comments left unaddressed

---

## 5. Agent Integration Standards

### Observation (how the agent sees the app)

There are NO in-app reporting hooks. The agent observes the app the way a
user does — a real browser (navigate / snapshot / click / console) — plus
the platform surfaces:

- `livingui <project> logs --tail 100` — server + build output
- PocketBase data via the CLI data commands or the REST API
- the system routes in `pb_hooks/_craftbot.pb.js` (state blob, UI
  snapshots, action log) — system-managed, never edit or extend them

**Rules:**
- Never invent a reporting/command channel; the browser is the interface
- Anything worth observing should be visible in the UI or stored in a
  collection — if the agent can't see it, neither can the user

### Agent Data Access (Agent ↔ Backend)

- Plain data needs nothing: PocketBase CRUD plus the CLI's built-in data
  commands (`select`/`count`/`sql`) already cover every collection
- Add `/api/custom/...` endpoints (`pb_hooks/main.pb.js`) for computed or
  aggregate data an agent might need — e.g. `/api/custom/stats`
- Declare an op for each, and document which ops are agent-accessible

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
- [ ] No console errors (`browser_console_messages` during normal use)
- [ ] `verify_build` is ok (root-cause-grouped compile truth)

### Agent
- [ ] Every side-effectful capability beyond CRUD has a declared op

---

## Quick Reference

### Must Have (Blocking)

1. Data persists across refreshes
2. UI works on mobile (320px)
3. Loading states for async operations
4. No console errors
5. `living_ui_validate` passes

### Should Have (Quality)

1. Empty states when no data
2. Confirmation for destructive actions
3. Keyboard navigation works
4. Consistent visual design
5. Agent integration
