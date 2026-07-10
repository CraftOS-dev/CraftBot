---
name: living-ui-creator
description: Create custom Living UI applications with a declared (schema-driven) backend. Scaffolds, develops, tests, and launches dynamic web apps with persistent state.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Creator

Create interactive web applications that persist state and survive page reloads.

## Architecture Overview

Living UI uses a **declared backend, stateless frontend** pattern —
the backend is CONFIGURATION, not code: entities go in config/schema.json
and a pre-tested engine materializes the models and REST CRUD API. You
hand-write only custom behavior endpoints and the frontend.

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

## Reference Index (read the right file BEFORE acting)

SKILL.md is the workflow; the details live in references/. When a step
touches a topic below, READ that file first — do not improvise from
memory:

| When you are about to... | Read |
|---|---|
| Declare entities / query the generated API / use files, schedules, secrets, AI, Supabase | [BACKEND.md](references/BACKEND.md) |
| Write ANY frontend component (exact preset props, layout kit, styling, theming) | [COMPONENTS.md](references/COMPONENTS.md) |
| Write schema/route/test/component code (copy-paste patterns) | [EXAMPLES.md](references/EXAMPLES.md) |
| Call external services (Google, Slack, Discord...) or in-app AI | [INTEGRATIONS.md](references/INTEGRATIONS.md) |
| Declare/curate the app's operations or schedules | [OPERATIONS.md](references/OPERATIONS.md) |
| Add login / multiple users | [Auth module README](../../data/living_ui_modules/auth/README.md) |
| Decide which layer owns a behavior | [MVC-A.md](references/MVC-A.md) |
| Run the Phase 10 design self-review | [DESIGN_REVIEW.md](references/DESIGN_REVIEW.md) |
| Judge whether the app is "done" | [STANDARDS.md](references/STANDARDS.md), [VERIFY.md](references/VERIFY.md) |
| Debug a failure (logs, common errors) | [TROUBLESHOOTING.md](references/TROUBLESHOOTING.md) |

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

## The Backend Is Declared, Not Coded (MANDATORY)

Declare every entity in `config/schema.json`; the engine materializes the
models AND the full REST API per entity — list (filters, `?q=` search,
range filters, orderBy/limit/offset), create/bulk, get/update/delete,
`/_stats` aggregations, `/api/_meta/schema`. You NEVER write models.py or
CRUD routes. Automatic per entity: `id`, `createdAt`, `updatedAt` (never
declare them); camelCase wire format.

```json
{
  "entities": {
    "Card": {
      "fields": {
        "title": {"type": "string", "required": true},
        "status": {"type": "enum", "values": ["todo", "done"], "default": "todo"},
        "dueDate": {"type": "datetime"},
        "columnId": {"type": "ref", "entity": "BoardColumn", "required": true}
      }
    }
  }
}
```

Field types: string, text, integer, float, boolean, datetime, json, ref,
enum (+ `"unique": true`). Full field spec, the complete generated API
surface, and the query params: **references/BACKEND.md**.

**`routes.py` is for BEHAVIOR only** (multi-entity transactions, computed
aggregations, external fetches) — Pydantic bodies always, one-line
docstrings, paths WITHOUT `/api`. See references/EXAMPLES.md.

Hard rules (details + recipes in references/BACKEND.md):
- **Every entity needs a WORKING INGRESS** — user forms, bridge pull
  from a connected service (+ a scheduled sync op), file import, or
  computed. Inbound webhooks are NOT an ingress (the app runs on
  localhost; external services can never reach it). External-data apps
  MUST build the bridge pull — an app that can never contain data is a
  failed build.
- **Dependencies are the PLATFORM's job** — NEVER run `npm install`/`pip
  install`; early "Cannot find module" notes on template deps mean the
  platform install is still running (a second npm CORRUPTS node_modules).
  New packages: add to package.json/requirements.txt.
- **Schema renames/removals are SAFE** — the platform reconciles the DB;
  never hand-edit or delete living_ui.db.
- **File storage is built in** — system `/api/files` routes +
  `<FileUpload>`/`<ImageInput>` presets; never hand-roll uploads.
- **Ops can run on a schedule** — `"schedule": "every 15m" | "hourly" |
  "daily 09:00"` in operations.json (references/OPERATIONS.md).
- **Secrets live ONLY in backend/.env** — `services/secrets.get_secret`;
  never hardcoded, never echoed. Stripe/payments recipe: BACKEND.md.
- **In-app AI is one call** — `await integration.llm(prompt)` /
  `.describe_image(url)` (references/INTEGRATIONS.md).
- **External database (Supabase/Postgres)** — one line in backend/.env:
  `DATABASE_URL=postgresql://...`; full recipe + safety rules: BACKEND.md.

See [MVC-A.md](references/MVC-A.md) for detailed architecture guidance.

## Multi-User / Auth Support

If the app needs multiple users, login, teams, or shared data:
1. Read `app/data/living_ui_modules/auth/README.md` for the full integration guide
2. Copy the module files into your project and wire them up as documented

**When to add auth:** the REQUIREMENTS mention multiple users, teams, sharing, login, or per-user data (task tracker, CRM, project manager).

## Directory Structure

The full annotated tree lives in **references/BACKEND.md**. The files YOU
edit: `config/schema.json` (entities), `backend/routes.py` (custom
behavior), `backend/tests/`, `frontend/components/` + `MainView.tsx`,
`config/operations.json` (via ops-sync), `LIVING_UI.md`. Everything marked
SYSTEM is never edited.

## UI Components (MANDATORY)

Use preset components for ALL standard UI elements; the page itself is
built from the Layout Kit (`AppShell`, `Section`, `CardGrid`, and the
Skeleton shape set: Box/Circle/Text/Chip/Card/Row/Stack — all adaptive,
never px-sized).
Never hand-roll buttons/inputs/cards/page scaffolding.

```typescript
import { Button, Input, Modal, EntityForm, EntityTable, toast,
         AppShell, Section, CardGrid, EmptyState, SkeletonCard } from './components/ui'
```

- **Read references/COMPONENTS.md → "Exact Props Cheat-Sheet" BEFORE
  writing any component** — wrong/guessed props fail the TS build at
  validation. It lists every preset (forms, tables, overlays, charts,
  uploads, hooks) with exact prop names.
- **Schema-aware presets FIRST**: `<EntityForm entity="Card"/>` IS the
  create/edit form; `<EntityTable entity="Card" searchable pageSize={25}/>`
  IS the data table; `useConfirm()` (never browser confirm), `toast` on
  every mutation.
- **Accent discipline**: the orange accent = ONE primary action per view +
  active states only; vary dashboards with semantic colors
  (COMPONENTS.md → Accent Discipline).
- **The HOST owns theming**: never render a theme picker/style switcher/
  dark-mode toggle in the app; `setDefaultStyle('glass')` at the top of
  App.tsx is the only theming call allowed (COMPONENTS.md → Style Packs).
- **Style with token-mapped Tailwind utilities** (`bg-surface`, `text-ink`,
  `border-line`, `rounded-token`, ...) — never hardcode colors/radius/
  shadow/spacing; class map in COMPONENTS.md → Styling with Tailwind.

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
  this skill (`config/schema.json`, `frontend/components/`, `LIVING_UI.md`, etc.) are
  relative to `project_path`.
- When calling `write_file`, `read_file`, or running tests, use the **absolute path**:
  `{project_path}/config/schema.json`, `{project_path}/frontend/components/MainView.tsx`,
  `cd {project_path}/backend && python -m pytest tests/`.
- **NEVER write to bare relative paths** like `config/schema.json` — they land in the
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

0. **Shell mode — the default is almost always right.** Plain `<AppShell>`
   FILLS the Living UI container with comfortable gutters (no max-width) —
   correct for dashboards, lists, forms, CRUD, nearly everything. Two
   opt-ins for the exceptions, applied when the first REAL region lands
   (the wireframe itself always uses plain `<AppShell>`):
   - `<AppShell fullBleed>` — ZERO gutters, for board/canvas/kanban/map
     apps and any app that paints its own full background (a background on
     an inner wrapper inside the default frame stops at the content edge
     and looks broken — if the app paints one, it must be fullBleed).
   - `<AppShell readingWidth>` — caps lines at the `--measure-reading`
     token, ONLY for long-form text (articles, notes readers). Never
     invent your own width numbers.
1. **Rewrite `frontend/components/MainView.tsx` as a TEXTLESS kit assembly**:
   plain `<AppShell>` with one `<Section>` per planned region (NO
   `title`/`meta`), each holding Skeleton presets ARRANGED TO MATCH that
   component's intended shape. **Use ONLY these presets — the complete wireframe
   vocabulary:**
   - `SkeletonBox` (`ratio?`) — any rectangle: toolbar strip (`ratio={8}`),
     chart area (`ratio={2}`), square tile (`ratio={1}`)
   - `SkeletonCircle` (`size?`) — avatars, icon spots
   - `SkeletonText` (`lines?`) — paragraph placeholder
   - `SkeletonChip` (`count?`) — filter/tag pill row
   - `SkeletonCard` (`count?`, `lines?`, `media?`) — content cards (in
     `<CardGrid>`)
   - `SkeletonRow` (`count?`) — list/table rows
   - `SkeletonStack` — groups mixed shapes with consistent spacing
   Examples: tabs row → `<SkeletonChip count={4} />`; card grid →
   `<CardGrid><SkeletonCard count={6} /></CardGrid>`; stats strip →
   `<CardGrid minWidth={160}><SkeletonBox count={4} ratio={2.5} /></CardGrid>`;
   sidebar → AppShell's `sidebar` prop with `<SkeletonStack>` of rows.
   **NEVER hand-make wireframe markup** — no custom divs with inline
   styles, no `<style>` blocks, no px widths/heights, no DIY shimmer.
   The presets are adaptive (they size from their container and cannot
   overflow) and space themselves; custom markup is flagged at write time
   and causes the overflow/stuck-together layouts that fail validation.
   The wireframe contains **NO text, NO titles, NO labels, NO interactive
   elements** — it purely covers each component's area and general layout.
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

- **READ before you write.** Read `config/schema.json`, the files you're
  about to change (`backend/routes.py`, `frontend/AppController.ts`, the
  component files) and `LIVING_UI.md` for project-specific notes; follow
  the conventions already there.
- **Build INCREMENTALLY so the preview keeps changing.** Take one
  capability all the way to working — its data, endpoints, and UI —
  mounting each component as you write it, before moving to the next.
  Don't do all backend then all frontend.
- **FIX WRITE-RESULT FEEDBACK IMMEDIATELY.** After every frontend code
  write the platform runs the project's own `tsc --noEmit` and appends the
  COMPLETE type-error list to your write result. Fix all of them in your
  next step — type errors compound and every one will fail validation.
- **RUN tests / lint / the build when it helps you** catch a problem early
  (find the project's commands first). You're not required to per
  capability — `living_ui_validate` runs the full suite at the end, so
  don't re-run after every small change.
- **Every capability WORKS END TO END** in the running app: real control →
  real `Modal`/form (never `prompt()`/`confirm()`) → API call → view
  updates. Renders-but-does-nothing is not done.

The pieces a capability typically needs (adapt — a capability reusing
existing entities touches only the frontend ones):

- **`config/schema.json`** — declare the capability's entities (see "The
  Backend Is Declared"). This alone creates the models and the whole CRUD
  API. Never declare `id`/`createdAt`/`updatedAt`.
- **`backend/routes.py`** — ONLY if the capability needs behavior beyond
  CRUD. Absolute imports, one-line docstrings, paths WITHOUT `/api`,
  request bodies as Pydantic models (never a bare Dict — the smoke tests
  probe endpoints from their OpenAPI schema). Declare the op in
  `config/operations.json`.
- **`backend/tests/test_*.py`** — tests for YOUR custom endpoints only
  (generated CRUD is pre-tested). Tests call paths WITH `/api`; assert
  camelCase. Tests MUST NOT depend on live internet — external-fetch
  endpoints degrade gracefully (return `{"fetched": 0}`-style, never 500);
  test the graceful path. NEVER seed fake/sample data to pass a test.
- **Entity types are GENERATED** — `frontend/types.gen.ts` is regenerated
  from schema.json on every schema write. Import from it
  (`import type { Card } from '../types.gen'`); NEVER hand-write entity
  interfaces. App-specific non-entity types go in types.ts.
- **Data plumbing is PROVIDED** — `useEntities<Card>('cards', {filters})`
  from `../services/data` gives items/loading/error + create/update/remove
  with auto-refresh; `data.list/create/bulkCreate/update/remove` for
  one-off calls. NEVER hand-write per-entity fetch methods in
  ApiService/AppController; ApiService is only for CUSTOM endpoints.
- **`frontend/components/<Component>.tsx`** — FINAL form: reach for the
  schema-aware presets FIRST — `<EntityForm entity="Card" …/>` for every
  create/edit form, `<EntityTable entity="Card" …/>` for data tables,
  `useConfirm()` for confirmations, `SortableList` for drag-reorder —
  then `useEntities`/`data` for custom layouts. Real handlers on every
  control, empty states, preset controls (never `prompt()`/`confirm()`),
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
- Custom routes use **absolute imports** (`from models import ...` NOT `from . import ...`)
- Custom `routes.py` paths do NOT add the `/api` prefix
- Every custom route has a one-line docstring and an op in operations.json
- TypeScript types match the schema's camelCase fields
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
data commands cover every schema entity automatically, and every entity
already has a generated bulk endpoint (`POST /api/<plural>/bulk`).
### Phase 10: Review, Validate, then Launch (MANDATORY — three steps, in order)

**Step 1 — Visual design self-review (look at your own app BEFORE validating).**

While you build, the live preview saves a screenshot of your app to
`{project_path}/logs/design_preview.png`. Run `describe_image` on it with
the EXACT reviewer prompt from **references/DESIGN_REVIEW.md** (it encodes
the defect-vs-design-decision distinction — do not ad-lib the prompt).
Fix genuine defects, wait for the screenshot to refresh, re-review until
PASS. If design_preview.png does not exist, skip this step.

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
absence/presence facts about the page.)

And it LOOKS at the page (step `design.judgment`): the platform VLM
reviews the resting-page screenshot like a human design reviewer —
unfinished-looking layouts (content welded into a corner over an empty
void, stray fragments with no page composition) are REFUSED with the
reviewer's specific reasons. Deliberate minimalism and full-bleed layouts
pass. Your Step 1 self-review catches this BEFORE it costs a validation
run.

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

## Quality & Completion

See [STANDARDS.md](references/STANDARDS.md) for quality requirements and [VERIFY.md](references/VERIFY.md) for the pre-launch checklist.

## External Integrations

CraftBot has connected services (Google, Discord, Slack, etc.). Living UIs access them via a built-in bridge — never build OAuth or store credentials yourself. See [INTEGRATIONS.md](references/INTEGRATIONS.md).

## External Data & Device APIs (weather, news, location, ...)

The app runs in a cross-origin iframe on localhost. Two patterns fail there
and must never be load-bearing:

1. **Frontend `fetch()` to third-party APIs** — CORS blocks most of them.
   ALL external data is fetched by the BACKEND: a `routes.py` endpoint using
   `httpx` (already in requirements), returning cached/normalized JSON to the
   frontend. No CORS, no keys exposed, degrades gracefully offline (return
   the last cached value or an empty payload — never a 500).
2. **Browser permission APIs** (`navigator.geolocation`, notifications,
   camera) — permission prompts inside the embedded tab are unreliable.
   A denied permission must NEVER be a dead-end error state.
   - **Location: default to backend IP-based lookup** (keyless, no prompt):
     `GET https://ipapi.co/json/` or `http://ip-api.com/json/` from a
     routes.py endpoint → `{lat, lon, city}`.
   - Browser geolocation is at most an optional refinement that silently
     falls back to the IP result.
   - Let the user override (a location field persisted in the schema) —
     settings beat detection.

Solved recipe — weather without any API key: backend endpoint does IP lookup
→ `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current_weather=true`
→ cache the JSON in memory with a timestamp and re-fetch only when stale
(e.g. 10+ min) → frontend reads YOUR endpoint via ApiService. News, quotes,
prices: same shape — pick a keyless/public API, fetch in the backend, cache,
degrade gracefully.

## FORBIDDEN Actions

- NEVER write to bare relative paths (`backend/models.py`) — always use the absolute `{project_path}/...` so files land in the project, not the CraftBot root
- NEVER skip Step 0 — you must have a registered `project_id`/`project_path` (from the task instruction or `living_ui_scaffold`) before writing any code
- NEVER edit system-managed backend files: `models.py`, `engine.py`, `system_models.py`, `system_routes.py`, `database.py`, `main.py` — data lives in `config/schema.json`
- NEVER hand-write CRUD models or routes — declare entities in `config/schema.json`; the engine generates both, pre-tested
- NEVER declare `id`, `createdAt`, or `updatedAt` in schema.json — the engine provides them
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
- NEVER fetch third-party APIs from the frontend (CORS) and NEVER make a browser permission (`navigator.geolocation`, notifications) load-bearing — external data comes from a backend endpoint; location defaults to backend IP lookup (see External Data & Device APIs)
- NEVER edit `tailwind.config.js` / `postcss.config.js` (system-managed; the token-mapped classes are already wired)
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

- [Declared Backend](references/BACKEND.md) - Schema spec, generated API, files/schedules/secrets/AI/Supabase, project layout
- [UI Components](references/COMPONENTS.md) - EXACT preset props, layout kit, styling, theming, icons, toasts
- [Code Examples](references/EXAMPLES.md) - Complete code examples for each phase
- [External Integrations](references/INTEGRATIONS.md) - Integration bridge, in-app AI, notification recipes
- [Operations Manifest](references/OPERATIONS.md) - Declaring the app's verbs + schedules (config/operations.json)
- [Auth Module](../../data/living_ui_modules/auth/README.md) - Multi-user auth, membership, invites
- [MVC-A Architecture](references/MVC-A.md) - When to use each layer, agent data access methods
- [Design Self-Review](references/DESIGN_REVIEW.md) - The exact Phase 10 reviewer prompt
- [Quality Standards](references/STANDARDS.md) - Professional standards for Living UIs
- [Verification Checklist](references/VERIFY.md) - QA checklist before launch (REQUIRED)
- [Troubleshooting](references/TROUBLESHOOTING.md) - Debug common issues, log files
