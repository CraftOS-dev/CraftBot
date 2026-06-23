---
name: living-ui-creator
description: Create custom Living UI applications with backend-first architecture. Scaffolds, develops, tests, and launches dynamic web apps with persistent state.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Creator

Create interactive web applications that persist state and survive page reloads.

## Architecture Overview

Living UI uses a **backend-first, stateless frontend** pattern:

```
┌─────────────────────────────────────────────────────────────────┐
│   BACKEND (FastAPI + SQLite)                                    │
│   Location: backend/                                            │
│   - THE source of truth for ALL application state               │
│   - Persists data to SQLite database                            │
│   - Exposes REST API at http://localhost:<backend_port>         │
│   - State survives page reloads and tab switches                │
├─────────────────────────────────────────────────────────────────┤
│   FRONTEND (React + TypeScript)                                 │
│   Location: frontend/                                           │
│   - Stateless view layer - fetches state FROM backend           │
│   - Sends user actions TO backend                               │
│   - Uses localStorage as cache only (fallback)                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Principle**: Frontend is a dumb view. Backend owns all state.

## Architecture Decision

Before coding, determine what your app needs:

| Need | Solution |
|------|----------|
| Persist user data | Database models (SQLite) |
| Fetch external data | Backend proxy endpoint |
| Agent provides data | `PUT /api/state` to push data |
| Agent reads app data | `GET /api/state` endpoint |
| Agent observes UI | `GET /api/ui-snapshot` (auto-captured) |
| Agent sees visually | `GET /api/ui-screenshot` |
| Agent triggers actions | `POST /api/action` |
| Complex UI state | Multiple frontend components |
| Multiple users with own data | Add auth module from `app/data/living_ui_modules/auth/` |
| User roles (admin/member) | Auth module + role checks in routes |

**Default:** Most apps need all layers (DB + Backend + Frontend).
**Agent APIs are built-in** - no extra work needed.

See [MVC-A.md](references/MVC-A.md) for detailed architecture guidance.

## Multi-User / Auth Support

If the app needs multiple users, login, teams, or shared data:
1. Read `app/data/living_ui_modules/auth/README.md` for the full integration guide
2. Copy the module files into your project and wire them up as documented

**When to add auth:** user mentioned "multiple users", "team", "sharing", "login", or the app manages per-user data (task tracker, CRM, project manager). If unsure, ask during Phase 0.

## Directory Structure

```
project_root/
├── backend/                    # Python FastAPI backend
│   ├── main.py                 # FastAPI app entry point (rarely edit)
│   ├── models.py               # SQLAlchemy models - EDIT THIS for data
│   ├── routes.py               # API endpoints - EDIT THIS for actions
│   ├── database.py             # DB connection (rarely edit)
│   └── living_ui.db            # SQLite database (auto-created)
│
├── frontend/                   # React TypeScript frontend
│   ├── main.tsx                # Entry point (rarely edit)
│   ├── App.tsx                 # Main app component
│   ├── AppController.ts        # State management & backend communication
│   ├── types.ts                # TypeScript interfaces - EDIT THIS
│   ├── components/             # React components - EDIT/ADD HERE
│   │   ├── ui/                 # Pre-built UI components (USE THESE)
│   │   │   └── index.tsx       # Button, Card, Input, Modal, etc.
│   │   └── MainView.tsx        # Main UI component
│   ├── services/               # API & UI capture (rarely edit)
│   │   ├── ApiService.ts       # Backend API client
│   │   └── UICapture.ts        # UI snapshot/screenshot for agent
│   └── styles/global.css       # CraftBot design tokens
│
├── config/manifest.json        # Project metadata (port info here)
├── index.html
├── package.json
├── vite.config.ts
└── LIVING_UI.md                # Project documentation - UPDATE THIS
```

## UI Components (MANDATORY)

Use preset components for ALL standard UI elements — `Button`, `Card`, `Input`, `Modal`, `Alert`, `Table`, etc.
Do NOT create custom buttons, inputs, cards, or write custom CSS for standard elements.

```typescript
import { Button, Card, Input, Alert, Table, Modal } from './components/ui'
```

See [COMPONENTS.md](references/COMPONENTS.md) for full reference, icons (lucide-react), and toasts (react-toastify).

## Agent API (Built-in)

Living UI provides standard HTTP endpoints for agent observation:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/ui-snapshot` | GET | UI state (DOM, text, form values) |
| `/api/ui-screenshot` | GET | Visual screenshot (PNG base64) |
| `/api/state` | GET/PUT | Application data |
| `/api/action` | POST | Trigger actions |

Frontend auto-captures UI state on meaningful events (page load, state changes, user interactions). See [MVC-A.md](references/MVC-A.md) for details.

## Development Workflow

Follow these phases in order. Use TodoWrite to track progress.

### Step 0: Create the Project Scaffold (MANDATORY FIRST STEP)

Before writing any code, you MUST have a registered project with a real `project_id`
and an absolute `project_path`. There are two cases:

1. **Your task instruction already contains a `Project ID` and `Project Path`** —
   the project was scaffolded for you (Create Living UI modal flow). **Skip scaffolding.**
   Use that `project_id` and `project_path` directly.

2. **No Project ID / Project Path in your task instruction** (you're building from a
   chat request) — call `living_ui_scaffold` FIRST to create and register the project:

   ```
   living_ui_scaffold(name="<short app name>", description="<what the app does>")
   ```

   It copies the template (`backend/`, `frontend/`, `config/`), allocates ports, and
   registers the project so it appears in the user's Living UI list. It returns
   `project_id` and an absolute `project_path`.

**CRITICAL — file path rule (applies to ALL phases):**
- Treat `project_path` as the base for **every** file operation. The relative paths in
  this skill (`backend/models.py`, `frontend/components/`, `LIVING_UI.md`, etc.) are
  relative to `project_path`.
- When creating files (via `run_shell`), calling `read_file`, or running tests, use the **absolute path**:
  `{project_path}/backend/models.py`, `{project_path}/frontend/components/MainView.tsx`,
  `cd {project_path}/backend && python -m pytest tests/`.
- **NEVER write to bare relative paths** like `backend/models.py` — they land in the
  CraftBot process directory, scattering files at the wrong root and breaking launch.

### Before You Start: Read and Apply Global Config

Read `agent_file_system/GLOBAL_LIVING_UI.md` for global design preferences and rules.

**You MUST apply these settings in your code:**

- **Primary/Secondary/Accent Colors**: Use these hex values in your CSS and component styles. Set them as CSS custom properties in `frontend/styles/global.css` or use them directly in components. Example: if Primary Color is `#6366f1`, use it for primary buttons, active states, links, and accent elements.
- **Font Family**: Apply as the `font-family` in `global.css` body styles.
- **Enabled rules `[x]`**: Treat as hard requirements — your code must implement them.
- **Disabled rules `[ ]`**: Skip these features.
- **Always Enforced rules**: These are non-negotiable — always follow them.
- Per-project requirements from Phase 0 Q&A override global settings when they conflict.

### Phase 0: Requirement Gathering (MANDATORY — minimum 2 batches)

Before coding, gather requirements from the user through a conversational interview.
Use `send_message` with `wait_for_user_reply=True` to ask questions and wait for answers.

**Reference:** Read [QUESTIONNAIRE.md](references/QUESTIONNAIRE.md) for question categories and examples.

**CRITICAL RULES:**
- You MUST ask at least 2 batches of questions. Never skip to coding after just 1 batch.
- Batch 1 MUST cover data/features. Batch 2 MUST cover design/visual preferences.
- If the user gives short or vague answers, DO NOT skip Batch 2. Instead, offer specific choices (e.g., "Would you prefer a card grid or a kanban column layout?").
- If the user explicitly says "just build it" or "skip the questions" — then and ONLY then can you stop early. A short answer to one question is NOT "skip."
- **EXPAND VAGUE ANSWERS**: When a user gives a brief or vague reply (e.g., "basic user stuff", "normal layout", "simple dashboard"), you MUST expand it into specific features, then confirm with the user before proceeding. See "Expanding Vague Answers" in [QUESTIONNAIRE.md](references/QUESTIONNAIRE.md) for common mappings.

**Process:**

1. **Analyze the project description** — identify what's clear and what's ambiguous
2. **Batch 1: Data & Features (REQUIRED)** — ask 2-4 questions:
   - Open with a warm acknowledgment of the project idea
   - Focus on: what entities/items exist, how they relate, what operations are needed
   - Use `send_message` with `wait_for_user_reply=True`
3. **Batch 2: Design & Layout (REQUIRED)** — always ask this, even if Batch 1 answers were short:
   - Acknowledge Batch 1 answers briefly
   - Focus on: layout style (grid/kanban/list/freeform), visual style, color preferences, detail views vs modals
   - Offer concrete choices rather than open-ended questions (e.g., "Card grid like Pinterest, or columns like Trello?")
   - Use `send_message` with `wait_for_user_reply=True`
4. **Batch 3 (optional)** — only if significant gaps remain after Batch 2
5. **Expand vague answers** — after each batch, review the user's responses:
   - If any answer is vague ("basic", "normal", "simple", "standard", "the usual"), expand it into concrete features using the mappings in QUESTIONNAIRE.md
   - Confirm your expansion: "By 'basic user stuff' I'll include: login/signup, user profiles, member list, and role-based access (admin/member). Does that sound right?"
   - Wait for user to confirm or correct before proceeding
   - Document the **expanded** version in LIVING_UI.md, not the vague original
6. **Fill gaps with assumptions** — after gathering answers:
   - State your assumptions explicitly to the user
   - See "Safe Assumptions" in QUESTIONNAIRE.md for defaults
6. **Document in LIVING_UI.md (MANDATORY)** — you MUST fill in the Requirements section NOW, before moving to Phase 1:
   - Fill in ALL subsections: Entities & Data Model, Layout & Design, Features, Assumptions
   - Replace ALL HTML comments (`<!-- ... -->`) with actual content
   - Replace ALL example/placeholder data with real data
   - This becomes the source of truth for all subsequent phases
   - **DO NOT proceed to Phase 1 until LIVING_UI.md has real content**

**When to stop asking:**
- After Batch 2, unless there are major gaps (then do Batch 3)
- If user explicitly says "just build it" or "skip" — stop and assume the rest
- Never ask more than 3 batches total

**Tone:** Warm and conversational. Offer concrete choices, not just open-ended questions. Acknowledge answers before asking more.

**Example Batch 1 (Data & Features):**
> "Love the idea! Before I start building, a few quick questions about what goes on the board:
> 1. What kinds of items will you add? (notes, images, videos, links, docs — all of these?)
> 2. What info should each item have? (just the content, or also title, description, tags, status?)
> 3. Do you need to organize items into categories or groups?"

**Example Batch 2 (Design & Layout):**
> "Thanks! Now a couple questions about how it should look:
> 1. Layout preference — card grid (like Pinterest), columns (like Trello), or a list view?
> 2. When you click an item, should it open in a detail panel on the side, a full modal, or expand in place?
> 3. Any color/visual preference? (dark theme, light, colorful, minimal — or I'll use a clean modern default)"

### Phase 1: Plan Features

Read the requirements from LIVING_UI.md (Phase 0) and break the app into **features**.
A feature is a complete user-facing capability (e.g., "Board Items", "Media Attachments", "Search/Filter").

Create a feature list in your todo list. Order by dependency (core data first, then enhancements).

Example feature breakdown for a research board:
1. Board Items (create, view, edit, delete items with title/description)
2. Categories/Sections (organize items into groups)
3. Media Attachments (images, videos, links on items)
4. Search & Filter (find items by text, category, tags)
5. Drag & Drop (reorder items)

If Phase 0 was skipped (requirements are very detailed in the description),
document them in LIVING_UI.md now before proceeding.

### Phase 2-7: Build Features (repeat for each feature)

Build one feature at a time, fully completing each before moving to the next.
For each feature, follow this cycle:

#### Step A: Write Tests First

**Edit: `backend/tests/test_{feature}.py`**

Write tests that describe the expected API behavior BEFORE writing routes.
The template provides `conftest.py` with a test client and temporary in-memory database.
These tests will FAIL initially — that's expected.

```python
# Example: tests/test_items.py
def test_create_item(client):
    """Should create a new item."""
    response = client.post("/api/items", json={
        "title": "Test Item",
        "description": "A test item",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Item"
    assert "id" in data

def test_get_items(client):
    """Should return all items."""
    client.post("/api/items", json={"title": "Item 1"})
    client.post("/api/items", json={"title": "Item 2"})
    response = client.get("/api/items")
    assert response.status_code == 200
    assert len(response.json()) == 2

def test_delete_item(client):
    """Should delete an item and return 404 on re-fetch."""
    item = client.post("/api/items", json={"title": "To Delete"}).json()
    response = client.delete(f"/api/items/{item['id']}")
    assert response.status_code == 200
    assert client.get(f"/api/items/{item['id']}").status_code == 404
```

**What to test:**
- CRUD operations (create, read, update, delete)
- Business logic (e.g., deleting a section deletes its cards)
- Edge cases (e.g., non-existent item returns 404)
- Relationships (e.g., item belongs to section)

**The `client` and `db` fixtures** are provided by `conftest.py`.
**Delete `tests/test_example.py`** after creating your first test file.

#### Step B: Create Backend (model + routes)

**Edit: `backend/models.py`** — add the model for this feature:
- NEVER use `metadata` as column name (reserved by SQLAlchemy)
- Always include `to_dict()` method for JSON serialization
- If model name conflicts with Python built-ins, use alias: `from models import List as ListModel`

**Edit: `backend/routes.py`** — add routes to make your tests pass:
- Write routes that satisfy each test assertion
- Use absolute imports only

#### Step C: Verify Backend

Run tests to verify your backend works:
```bash
cd backend && python -m pytest tests/ -v --tb=short
```

**Fix any failures before proceeding.** Do NOT move to frontend until all tests pass.

#### Step D: Create Frontend for This Feature

**Edit: `frontend/types.ts`** — add TypeScript interfaces for this feature's models
**Edit: `frontend/AppController.ts`** — add methods to call this feature's API endpoints
  - For the backend URL, use: `const BACKEND_URL = (window as any).__CRAFTBOT_BACKEND_URL__ || 'http://localhost:3101'`
  - NEVER hardcode a specific port — the port may change between launches
**Edit: `frontend/components/`** — create React components for this feature
**Edit: `frontend/components/MainView.tsx`** — wire the new components into the main view

Use preset UI components (Button, Card, Input, Modal, etc.) — see the UI Component Presets section.
Apply colors from GLOBAL_LIVING_UI.md.

#### Step E: Move to Next Feature

Update your todo list — mark this feature complete, start the next one.
Repeat Steps A-D for each feature.

### Phase 8: Final Review

After all features are built, review your code:
- Backend routes use **absolute imports** (`from models import ...` NOT `from . import ...`)
- Backend `routes.py` does NOT add `/api` prefix to route paths
- All `to_dict()` methods return all fields
- TypeScript types match backend model output
- Components import correctly from relative paths
- All tests pass: `cd backend && python -m pytest tests/ -v`

**DO NOT run:** `npm run dev`, `npm run build`, `npm run preview`, or `uvicorn` manually.
The launch pipeline handles all building, testing, and serving automatically.

### Phase 9: Update Documentation (MANDATORY)

**Edit: `LIVING_UI.md`** — you MUST update ALL sections with real implementation details:

- **Overview**: What the app does, who it's for
- **Data Model table**: List every SQLAlchemy model with purpose and key fields (replace example rows)
- **API Endpoints table**: List every custom route with method, path, description (replace example rows)
- **Frontend Components table**: List every component with purpose
- **Key Files table**: Update if you added new files
- Remove ALL HTML comments (`<!-- ... -->`) and placeholder/example data
- **DO NOT proceed to Phase 10 if LIVING_UI.md still has placeholder content**

### Phase 10: Launch (MANDATORY)

**YOU MUST call `living_ui_notify_ready` to complete the task.**

This action runs the full launch pipeline automatically:
- Installs backend dependencies (`pip install -r requirements.txt`)
- Runs import validation, unit tests, and frontend-backend compatibility checks
- Starts the backend server and verifies health
- Runs external smoke tests against the running backend
- Installs frontend dependencies and builds (`npm install && npm run build`)
- Starts the frontend server

If any step fails, the action returns the specific errors. Fix them and call again.

**CRITICAL - project_id Parameter:**
- The `project_id` is in your **task instruction** (e.g., "Project ID: abc12345"), or
  it was returned by `living_ui_scaffold` in Step 0 if you scaffolded from chat
- **DO NOT use task session ID** - that's different
- The project_id is a short hex string like `c8cda731`

```
living_ui_notify_ready(project_id="<PROJECT_ID from task instruction>")
```

## Debugging

When something goes wrong, read the log files and check [TROUBLESHOOTING.md](references/TROUBLESHOOTING.md).

## Files Summary

| File | Purpose | When to Edit |
|------|---------|--------------|
| `backend/models.py` | Database models | Define data entities |
| `backend/routes.py` | API endpoints | Add CRUD operations |
| `frontend/types.ts` | TypeScript types | Match backend models |
| `frontend/components/` | UI components | Build the interface |
| `frontend/AppController.ts` | State management | Connect UI to backend |
| `LIVING_UI.md` | Documentation | Document your app |

## Quality & Completion

See [STANDARDS.md](references/STANDARDS.md) for quality requirements and [VERIFY.md](references/VERIFY.md) for the pre-launch checklist.

## External Integrations

CraftBot has connected services (Google, Discord, Slack, etc.). Living UIs access them via a built-in bridge — never build OAuth or store credentials yourself. See [INTEGRATIONS.md](references/INTEGRATIONS.md).

## FORBIDDEN Actions

- NEVER write to bare relative paths (`backend/models.py`) — always use the absolute `{project_path}/...` so files land in the project, not the CraftBot root
- NEVER skip Step 0 — you must have a registered `project_id`/`project_path` (from the task instruction or `living_ui_scaffold`) before writing any code
- NEVER use `metadata` as a column name in SQLAlchemy
- NEVER use relative imports in backend code (`from . import` or `from .models import`)
- NEVER add `/api` prefix to route paths in `routes.py` (the router prefix handles this)
- NEVER run `npm run dev`, `npm run build`, `npm run preview`, or `uvicorn` manually
- NEVER store important state only in React (use backend)
- NEVER use raw HTML elements (`<button>`, `<input>`, `<select>`) — use preset components (`<Button>`, `<Input>`, `<Select>`)
- NEVER write custom CSS for buttons, cards, inputs, modals, or alerts — use the preset component props
- NEVER pick arbitrary colors — use design tokens from `global.css` (e.g., `var(--color-primary)`)
- NEVER skip Phase 0 Batch 2 (design questions) — minimum 2 batches required
- ONLY use `send_message` during Phase 0 (Requirement Gathering) with `wait_for_user_reply=True`. NEVER use it during development phases (Phase 1-10).
- NEVER edit `config/manifest.json` (managed by the system, contains pipeline config)
- NEVER edit `backend/main.py` (managed by the system, contains server setup)
- NEVER edit `frontend/main.tsx` (managed by the system, contains service initialization)
- NEVER leave LIVING_UI.md with placeholder content, HTML comments, or example data
- NEVER skip calling `living_ui_notify_ready`
- NEVER use the task session ID as the project_id parameter

## References

- [UI Components](references/COMPONENTS.md) - Preset components, icons, toasts
- [External Integrations](references/INTEGRATIONS.md) - Integration bridge (Google, Discord, etc.)
- [Auth Module](../../data/living_ui_modules/auth/README.md) - Multi-user auth, membership, invites
- [Requirement Questionnaire](references/QUESTIONNAIRE.md) - Reference questions for Phase 0
- [MVC-A Architecture](references/MVC-A.md) - When to use each layer, agent data access methods
- [Quality Standards](references/STANDARDS.md) - Professional standards for Living UIs
- [Code Examples](references/EXAMPLES.md) - Complete code examples for each phase
- [Verification Checklist](references/VERIFY.md) - QA checklist before launch (REQUIRED)
- [Troubleshooting](references/TROUBLESHOOTING.md) - Debug common issues, log files
