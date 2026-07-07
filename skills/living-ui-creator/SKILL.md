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

**When to add auth:** the REQUIREMENTS mention multiple users, teams, sharing, login, or per-user data (task tracker, CRM, project manager).

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

The page itself is built from the **Layout Kit** (same import): `AppShell`,
`Section`, `CardGrid`, `EmptyState`, `SkeletonCard`, `SkeletonRow`,
`Toolbar`, `IconBadge`, `StatCard`, `SplitView`. Never hand-roll page scaffolding (gutters, max-width,
headers, section spacing) — the kit owns it.

```typescript
import { Button, Card, Input, Alert, Table, Modal } from './components/ui'
import { AppShell, Section, CardGrid, EmptyState, SkeletonCard } from './components/ui'
```

**EXACT prop names (do NOT guess — wrong props fail the TS build at validation):**

| Component | Props |
|---|---|
| `Button` | `variant`('primary'\|'secondary'\|'danger'\|'ghost'), `size`, `loading`, `fullWidth`, `icon`, `disabled`, `onClick` |
| `Input` | `label?`, `error?`, `hint?` + native input props (`value`, `onChange`, `placeholder`, ...) |
| `Select` | `label?`, `error?`, `hint?`, `options: {value,label}[]`, `placeholder?` |
| `Toggle` | `checked`, `onChange:(checked)=>void`, `label?`, `disabled?` |
| `Card` | `children`, `padding?`('none'\|'sm'\|'md'\|'lg') — NO `title` prop; put headings in children |
| `Alert` | `variant`, `title?`, `children`, `onClose?` |
| `Badge` | `children`, `variant?`, `size?`, `dot?` |
| `Modal` | `open` (NOT `isOpen`), `onClose`, `title?`, `children`, `footer?`, `size?` |
| `Table` | `columns: TableColumn[]`, `data`, `emptyMessage?`, `onRowClick?`, `rowKey?` |
| `EmptyState` | `icon?`, `title?`, `message` (NOT `description`), `action?` (one ReactNode) |
| `Tabs` | `children`, `defaultTab?`, `onChange?` |
| `AppShell` | `sidebar?`, `children`, `maxWidth?` — NO header prop |
| `Section` | `title?`, `meta?`, `actions?`, `children` |
| `CardGrid` | `children`, `minWidth?` |
| `SkeletonCard` | `count?`, `height?` — `SkeletonRow`: `count?` |
| `Toolbar` | `children`, `end?` (right-aligned group) — one row of controls |
| `IconBadge` | `icon` (lucide element), `color?`, `size?` — colored icon holder |
| `StatCard` | `icon?`, `value`, `label`, `color?` — icon + big number + label |
| `SplitView` | `children` (main), `aside`, `asideWidth?` — main + side column |

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
- When calling `write_file`, `read_file`, or running tests, use the **absolute path**:
  `{project_path}/backend/models.py`, `{project_path}/frontend/components/MainView.tsx`,
  `cd {project_path}/backend && python -m pytest tests/`.
- **NEVER write to bare relative paths** like `backend/models.py` — they land in the
  CraftBot process directory, scattering files at the wrong root and breaking launch.

### Before You Start: Read and Apply Global Config

Read `agent_file_system/GLOBAL_LIVING_UI.md` for global design preferences and rules.

**You MUST apply these settings in your code:**

- **Primary/Secondary/Accent Colors**: Use these hex values in your CSS and component styles. Set them as CSS custom properties in `frontend/styles/global.css` or use them directly in components. Example: if Primary Color is `#FF4F18` (the default `--color-primary` token — see references/COMPONENTS.md), use it for primary buttons, active states, links, and accent elements.
- **Font Family**: Apply as the `font-family` in `global.css` body styles.
- **Enabled rules `[x]`**: Treat as hard requirements — your code must implement them.
- **Disabled rules `[ ]`**: Skip these features.
- **Always Enforced rules**: These are non-negotiable — always follow them.
- Per-project REQUIREMENTS (from the task instruction) override global settings when they conflict.

### Requirements Arrive Complete (NEVER interview the user)

Your task instruction contains the REQUIREMENTS section: the complete,
binding specification for this app, synthesized from the user's creation
wizard (configuration, reference files, and interview) BEFORE this task
started. A copy lives at `{project_path}/reference/requirements.md`.

- Do NOT call `set_requirement` — the REQUIREMENTS section is the
  requirement record.
- NEVER ask the user questions (`send_message` is not part of this
  workflow) — requirement gathering already happened. Where the spec is
  silent, decide and build.
- The REQUIREMENTS are a COMMITMENT: build all of them. Never ask
  permission to skip, defer, or descope anything; scope shrinks only if
  the USER, unprompted, orders it.
- Study the reference files listed in the task instruction BEFORE the
  wireframe — view images with `describe_image`; they carry the user's
  design intent.

### Create the Todo List FIRST

Immediately after reading the global config and reference files, call
`task_update_todos` with the full plan (the EXACT pattern in Phase 1),
with feature names derived from the REQUIREMENTS. The todo list is the
user's progress display from the first second; nothing else happens
before it exists.

### Phase 1: Plan the Build

Think in **USER-FACING capabilities** (e.g. "Column CRUD", "Task Cards",
"Search/Filter"), NOT layers and NOT visual regions. A capability is DONE
only when its user flow works END TO END in the running app: the control
opens a real form/modal (never a browser prompt/confirm), submits to the
backend, and the view updates. Renders-but-does-nothing is NOT done.

Read the REQUIREMENTS from the task instruction, break the app into
capabilities, and create your todo list. **Shape it to the app** — this is
a sensible DEFAULT, adapt it (one coarse line per capability so updates
stay cheap; you choose granularity and order):

```
1. Layout wireframe — page frame + placeholder regions (Phase 1.5)
2. Build <capability A> (data + API + UI, mounted)
3. Build <capability B> (data + API + UI, mounted)
   ... one line per capability ...
4. Docs + operations (Phase 9)
5. Design self-review: describe_image on logs/design_preview.png until PASS
6. Validate: living_ui_validate until it passes
7. Launch: living_ui_notify_ready (refuses without a validation pass)
```

There is NO forced backend-then-frontend split and no fixed number of
todos per capability — work the way you would in any codebase (read the
existing code first, follow its conventions). The ONE constraint: build
INCREMENTALLY so the preview keeps changing — keep each capability's data,
endpoints, and UI close together, mounting components as you go.

FORBIDDEN: whole-app layers — "Backend (all features)" then "Frontend (all
features)". Layer-shaped work leaves the preview dead for 20+ minutes and
ships apps whose frontend was never wired to its backend.

### Phase 1.5: Layout Wireframe (MANDATORY FIRST BUILD STEP — before ANY backend work)

The first thing you build is the **full-page layout frame, purely for
display**, so the app looks like a real app from minute one. The platform
enforces the order: backend writes made before this exists come back with a
warning note.

**You do NOT hand-write page-level CSS. The LAYOUT KIT owns the page**
(gutters, max-width, viewport height, section spacing, overflow, skeletons):
`AppShell`, `Section`, `CardGrid`, `EmptyState`, `SkeletonCard`,
`SkeletonRow` — all in `./components/ui` (see COMPONENTS.md → Layout Kit).
There is NO page header: the page starts directly with its content
Sections — no title band.

1. **Rewrite `frontend/components/MainView.tsx` as a TEXTLESS kit assembly**:
   `<AppShell>` with one `<Section>` per planned
   region (NO `title`/`meta`), each holding `Skeleton*` blocks ARRANGED TO
   MATCH that component's intended shape — a tabs row books a thin
   `<SkeletonRow count={1} />`, a card grid books `<CardGrid><SkeletonCard
   count={6} /></CardGrid>`, a stats strip books a row of short skeleton
   blocks. The wireframe contains **NO text, NO titles, NO labels, NO
   interactive elements** — it purely covers each component's area and
   general layout. Sidebar layouts use AppShell's `sidebar` prop with
   skeleton blocks.
2. **The wireframe only BOOKS space — every part of it MUST be replaced.**
   Each Section's skeletons are replaced by the feature that owns that
   region, which also adds the real Section `title`/`meta`/`actions`
   (actions arrive WIRED in the feature that owns them). Nothing
   wireframe-authored may survive to the final app: leftover Skeletons in
   MainView FAIL validation. Do NOT create static stub components — every
   region component is written exactly once, in its final form, in its
   feature's frontend step. MainView stays a kit assembly — a region's UI
   never lives inline in MainView.
3. **CSS COMES WITH THE COMPONENT — always.** The kit covers page structure;
   whatever layout is INTERNAL to a component (its rows, alignment, card
   innards) ships as a scoped `<style>` block in the same write. A component
   that renders unstyled, even for one minute, is a violation. The platform
   flags raw HTML controls and CSS-less components in the write result.
4. **ONE ACTION, ONE PLACE.** Every action (e.g. Refresh) appears exactly
   once, in the `actions` slot of the ONE Section that owns it — never
   duplicated across sections and empty states. An EmptyState may carry the
   action ONLY if it is not already in its Section's actions slot.
5. **Static JSX only** — no data fetching, no `AppController` changes, no
   state. Hardcode nothing that looks like real data; empty states are the
   content.

### Phase 2-7: Build the Capabilities

Build the app to fulfill the REQUIREMENTS, one capability at a time, the
way you would in any codebase. There is **NO forced backend-then-frontend
order** and no fixed action list — you decide how to sequence the work.
What matters:

- **READ before you write.** Read the files you're about to change
  (`backend/models.py`, `backend/routes.py`, `frontend/AppController.ts`,
  the component files) and `LIVING_UI.md` for project-specific notes;
  follow the conventions already there.
- **Build INCREMENTALLY so the preview keeps changing.** Take one
  capability all the way to working — its data, endpoints, and UI —
  mounting each component as you write it, before moving to the next.
  Don't do all backend then all frontend.
- **RUN tests / lint / the build when it helps you** catch a problem early
  (find the project's commands first). You're not required to per
  capability — `living_ui_validate` runs the full suite at the end, so
  don't re-run after every small change.
- **Every capability WORKS END TO END** in the running app: real control →
  real `Modal`/form (never `prompt()`/`confirm()`) → API call → view
  updates. Renders-but-does-nothing is not done.

The pieces a capability typically needs (adapt — a capability reusing
existing models touches only the frontend ones):

- **`backend/tests/test_*.py`** — tests for the endpoints. Routes declare
  paths WITHOUT `/api`; tests call WITH `/api`. Assert camelCase (matching
  `to_dict()`). Tests MUST NOT depend on live internet — external-fetch
  endpoints degrade gracefully (return `{"fetched": 0}`-style, never 500);
  test the graceful path. NEVER seed fake/sample data to pass a test.
- **`backend/models.py`** — read it first, then `write_file` the COMPLETE
  updated file with your model added. NEVER append with `stream_edit`
  anchors — end-of-file edits corrupt this file. No `metadata` column;
  always a `to_dict()` returning ALL fields (camelCase).
- **`backend/routes.py`** — same whole-file approach; absolute imports,
  one-line docstrings, no `/api` prefix.
- **`frontend/types.ts`** — interfaces matching `to_dict()` exactly.
- **`frontend/AppController.ts`** — methods for the endpoints. Backend URL:
  `const BACKEND_URL = (window as any).__CRAFTBOT_BACKEND_URL__ || 'http://localhost:3101'`
- **`frontend/components/<Component>.tsx`** — FINAL form: real fetch calls
  through the controller, real handlers on every control, empty states,
  preset controls (real `Modal`/form — never `prompt()`/`confirm()`),
  scoped `<style>` block. The full flow ships WIRED; a capability spanning
  several components wires them together here.
- **`frontend/components/MainView.tsx`** — import and mount the
  component(s), replacing that region's `Skeleton*` placeholders and
  finalizing the Section's title/meta/actions.

**Every file is written ONCE, in its final form — no drafts, no static
stubs, no "wire it later".** A control with an empty handler
(`onClick={() => {}}`) must never exist at any point. When `living_ui_validate`
reports failures, fix them all — validation refuses red tests, skeleton
sections, and unmounted components, so debts always come back with interest.

The mount is the moment the user's wireframe section fills in with the
real, working UI. **An unmounted component does not exist** — the platform
warns on every write while a component is unmounted, and validation refuses
apps with unmounted components or leftover Skeletons in MainView.

### Phase 8: Final Review

After all features are live, review your code (by reading, NOT by running
pytest — validation runs the suite):
- Backend routes use **absolute imports** (`from models import ...` NOT `from . import ...`)
- Backend `routes.py` does NOT add `/api` prefix to route paths
- All `to_dict()` methods return all fields
- TypeScript types match backend model output
- Components import correctly from relative paths

**DO NOT run:** `npm run dev`, `npm run build`, `npm run preview`, or `uvicorn` manually.
The launch pipeline handles all building, testing, and serving automatically.

### Phase 9: Update Documentation & Declare Operations (MANDATORY)

**Edit: `LIVING_UI.md`** — you MUST update ALL sections with real implementation details:

- **Overview**: What the app does, who it's for
- **Data Model table**: List every SQLAlchemy model with purpose and key fields (replace example rows)
- **API Endpoints table**: List every custom route with method, path, description (replace example rows)
- **Frontend Components table**: List every component with purpose
- **Key Files table**: Update if you added new files
- Remove ALL HTML comments (`<!-- ... -->`) and placeholder/example data
- **DO NOT proceed to Phase 10 if LIVING_UI.md still has placeholder content**

**Make the app CLI-OPERABLE (MANDATORY — mechanical procedure, do not improvise).**

Every Living UI is operated later through the `livingui` CLI: agents run
`livingui <project> --help` and see the app's tables plus its declared
operations (`config/operations.json`). **What is declared there IS the app's
control surface — an undeclared capability does not exist for any future
agent.** You do NOT hand-author this file from memory; it is generated from
your code and you curate it:

1. **During development** (Phases 2-7): give EVERY route a one-line
   docstring saying what it does — docstrings become the generated op
   descriptions. This is where quality is decided.
2. **Phase 9**: nothing to author here beyond LIVING_UI.md. Do not
   hand-write operations.json paths/params — the generator gets them exactly
   right from your Pydantic schemas; you will get them wrong.
3. **After `living_ui_validate` passes** (the backend is left running):
   ```
   livingui <project_id> ops-sync --write   # generates ops for every non-CRUD route
   ```
   Then EDIT each generated op's description so it says *when* to use it
   (agents choose ops by reading descriptions), and finish with:
   ```
   livingui <project_id> ops-check          # repeat until 0 errors, 0 warnings
   ```
   Routes that genuinely should not be ops go in `"ignore_routes"` — an
   explicit decision, never a silent omission.

The launch pipeline enforces this: manifest errors (dead routes, undeclared
path params, broken templates) BLOCK the launch with exact fixes; uncovered
routes surface as warnings. Plain CRUD needs no ops — the CLI's built-in
data commands cover every table automatically. Also give every list
resource a bulk-create endpoint (`POST /api/{resource}/bulk` accepting a
JSON array, inserting all rows in one transaction).

### Phase 10: Review, Validate, then Launch (MANDATORY — three steps, in order)

**Step 1 — Visual design self-review (look at your own app BEFORE validating).**

While you build, the live preview continuously saves a screenshot of your
app to `{project_path}/logs/design_preview.png`. LOOK at it before you
spend a validation run:

```
describe_image(
  image_path="{project_path}/logs/design_preview.png",
  prompt="You are an experienced UI design reviewer looking at a screenshot
of a web app that was JUST BUILT and has NO USER DATA YET. Your job is to
find GENUINE DEFECTS — things a reasonable user would object to because
they look broken, unfinished, or make the app hard to use — while
respecting INTENTIONAL DESIGN DECISIONS. Before flagging anything, ask:
'is this a bug, or is this a choice a competent designer plausibly made
on purpose?' Conventional design patterns (visual hierarchy through
muted/secondary styling, whitespace as breathing room, empty states in an
app that has no data yet, restrained color palettes, de-emphasized
metadata) are NOT defects. A region that is empty because the app is
waiting for user content is fine IF it communicates that state; it is a
defect only if it renders as broken or unexplained dead space. DO report:
text clipped, cut off, or overlapping; elements colliding or misaligned;
sections that render as raw/unstyled/broken; text genuinely unreadable
against its background; controls that look unfinished or misplaced;
inconsistency between elements that should look alike; a UI that reads as
an unstyled wall of text with no visual structure, icons, or accents for
its scope. For each defect: say WHERE it is, WHY it is a defect rather
than a plausible design choice, and what a user would complain about.
Verdict: PASS unless there are genuine defects — do not fail the app for
defensible design decisions or for the absence of data it doesn't have
yet."
)
```

If the review lists a genuine defect: fix the layout/CSS/visual design,
wait a moment for the preview screenshot to refresh, and re-review. Repeat
until PASS. Trust the reviewer's decision/defect distinction — do not
"fix" things it explicitly identified as plausible design choices. If
`design_preview.png` does not exist (preview never open), skip this step —
the platform's design gate still applies.

**Step 2 — `living_ui_validate(project_id=...)` until it PASSES.**

Call it only when the work is DONE — every feature's flow working, every
component mounted. Validation verifies finished work; it is not a probe
for what's left, and calling it early just refuses on the first gate.
Whatever it reports, the only response is to fix and build — never to
negotiate scope away.

Validation runs the full launch pipeline:
- Completeness check (an unbuilt app is refused outright)
- Installs backend dependencies (`pip install -r requirements.txt`)
- Runs import validation, unit tests, and frontend-backend compatibility checks
- Starts the backend server and verifies health
- Runs external smoke tests against the running backend
- Checks the operations manifest (`config/operations.json`)
- Installs frontend dependencies and builds (`npm install && npm run build`)
- Starts the frontend server

If any step fails, the action returns the specific errors. Fix them and run
`living_ui_validate` again. Repeat until it PASSES. While the backend is up
after a pass, finish Phase 9's `ops-sync --write` / description curation /
`ops-check` — note that editing project code or operations.json CLEARS the
validation pass, so run `living_ui_validate` once more after curation.

Validation also measures the real rendered layout (step `design.review`):
pages that overflow horizontally, clip text, render empty Sections, or
contain ZERO icons/images are REFUSED with specifics. (These are
absence/presence facts about the page — visual judgment is YOUR job in
this review step.)

**Step 3 — `living_ui_notify_ready(project_id=...)` to present the app.**

This is a HARD GATE: notify_ready REFUSES to run unless the latest
`living_ui_validate` passed. Ignoring a validation failure and calling
notify_ready anyway does not work — it returns `validation_not_passed`.

**CRITICAL - project_id Parameter:**
- The `project_id` is in your **task instruction** (e.g., "Project ID: abc12345"), or
  it was returned by `living_ui_scaffold` in Step 0 if you scaffolded from chat
- **DO NOT use task session ID** - that's different
- The project_id is a short hex string like `c8cda731`

```
living_ui_validate(project_id="<PROJECT_ID>")     # repeat until it passes
living_ui_notify_ready(project_id="<PROJECT_ID>") # only works after a pass
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
- NEVER create whole-app layer todos ("Backend: all features" then "Frontend: all features") — build one capability at a time (data + API + UI together) so the preview keeps changing; you choose the order, but never freeze the screen behind an all-backend phase
- NEVER put interactive controls in the wireframe, and NEVER ship an empty stub handler (`onClick={() => {}}`) — controls arrive wired, in the feature that owns them
- NEVER use browser dialogs (`prompt()`, `confirm()`, `alert()`) for user input or confirmation — use the preset `Modal` and form components; a native dialog is an unfinished feature
- NEVER seed fake/sample/demo data to make tests pass or to showcase UI — empty states are the no-data content
- NEVER make tests depend on live internet — external fetches degrade gracefully and tests cover the non-network paths
- NEVER append to models.py/routes.py with stream_edit — read the file, then write_file the complete updated file
- NEVER ignore a test you ran that came back red, and NEVER seed fake data to make one pass — validation runs the full suite and refuses red tests, sending you back
- NEVER write a static stub or draft version of a component — every component is written ONCE, in its final live form (real fetch calls, real handlers). Placeholder handlers like `onClick={() => {}}` are a violation
- NEVER use `stream_edit` for new files or large rewrites — `write_file` with the complete final content; `stream_edit` is only for small local changes (a few lines)
- NEVER write backend code before the Phase 1.5 UI skeleton exists — the platform flags such writes with a warning note
- NEVER put a region's UI inline in `MainView.tsx` — MainView is a layout assembly; every visual region is its own file under `frontend/components/`
- NEVER write a component without its CSS in the same write — markup and its scoped `<style>` block arrive together; an unstyled component on screen is a violation
- NEVER hand-roll page scaffolding — MainView is an `AppShell`/`Section` assembly from the Layout Kit; hand-written page frames produce clipped titles, missing gutters, and overflow. NO page header/title band — the page starts with its content Sections
- NEVER leave a component unmounted — a component file that MainView (directly or via a parent component) doesn't render is INVISIBLE and does not count as built; mount it in the same step you create it. Validation refuses apps with unmounted components or skeleton-only MainViews
- NEVER place the same action (e.g. Refresh) in more than one spot — one action, one `actions` slot
- NEVER edit `frontend/components/ui/index.tsx` (preset component library — import from it, never modify it)
- NEVER pick arbitrary colors — use design tokens from `global.css` (e.g., `var(--color-primary)`)
- NEVER use `send_message` in a Living UI creation task — requirement gathering happened in the creation wizard before the task started; never ask the user questions
- NEVER edit `config/manifest.json` (managed by the system, contains pipeline config)
- NEVER edit `backend/main.py` (managed by the system, contains server setup)
- NEVER edit `frontend/main.tsx` (managed by the system, contains service initialization)
- NEVER leave LIVING_UI.md with placeholder content, HTML comments, or example data
- NEVER call `set_requirement` in a Living UI task — the REQUIREMENTS section of the task instruction is the requirement record
- NEVER track per-component progress in the todo list — todos stay at the feature level (the EXACT pattern in Phase 1)
- NEVER skip calling `living_ui_notify_ready`
- NEVER call `living_ui_notify_ready` before `living_ui_validate` has PASSED — it refuses with `validation_not_passed`; fix the reported errors and validate again
- NEVER use the task session ID as the project_id parameter
- NEVER hand-author operations.json paths/params — use `livingui <id> ops-sync --write` after launch, then curate descriptions and run `ops-check` until clean

## References

- [UI Components](references/COMPONENTS.md) - Preset components, icons, toasts
- [External Integrations](references/INTEGRATIONS.md) - Integration bridge (Google, Discord, etc.)
- [Auth Module](../../data/living_ui_modules/auth/README.md) - Multi-user auth, membership, invites
- [MVC-A Architecture](references/MVC-A.md) - When to use each layer, agent data access methods
- [Operations Manifest](references/OPERATIONS.md) - Declaring the app's verbs (config/operations.json)
- [Quality Standards](references/STANDARDS.md) - Professional standards for Living UIs
- [Code Examples](references/EXAMPLES.md) - Complete code examples for each phase
- [Verification Checklist](references/VERIFY.md) - QA checklist before launch (REQUIRED)
- [Troubleshooting](references/TROUBLESHOOTING.md) - Debug common issues, log files
