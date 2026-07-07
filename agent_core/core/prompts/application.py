# -*- coding: utf-8 -*-
"""
Application-specific prompt templates.

Contains prompt templates for Living UI and other application features.
"""

# NOTE: This instruction is a condensed mirror of the canonical workflow in
# skills/living-ui-creator/SKILL.md (which the task also loads via
# selected_skills). If you change the workflow, ports, or quality bar in
# either place, update the other — they drift independently otherwise.
LIVING_UI_TASK_INSTRUCTION = """Create a Living UI application.

Project ID: {project_id}
Project Name: {project_name}
Description: {description}
Features: {features}
Theme: {theme}
Project Path: {project_path}

The user WATCHES this app being built in a live preview — the screen must
visibly change every few minutes, so after the wireframe you complete the
app ONE FEATURE AT A TIME, backend and frontend together, never
all-backend-then-all-frontend.
Follow the living-ui-creator skill instructions. Here's the workflow:

1. Read agent_file_system/GLOBAL_LIVING_UI.md — apply its colors, fonts, and rules
2. CREATE THE TODO LIST NOW — immediately after that read, call
   task_update_todos with the FULL plan (the EXACT pattern below; feature
   names can be provisional until Phase 0 answers arrive). This comes
   BEFORE any send_message and BEFORE asking the user ANY question: the
   todo list is the user's progress display from the first second, and a
   task without one looks dead. When Phase 0 answers change the features,
   update the list — but it exists FIRST.
3. Phase 0: Ask the user 2+ batches of questions about data, features, design, and layout
4. WRITE THE REQUIREMENT LEDGER in LIVING_UI.md — do NOT call
   set_requirement (this ledger replaces it; skip that step entirely).
   Fill the <!-- REQ:BEGIN --> block with five sections of ID'd checkboxes
   (- [ ] F1: ...), SUPER-DETAILED across the app's whole scope: Features
   (F, every core capability), Data (D, models/fields/schema), Design (V,
   the visual contract: icons, imagery, alignment, tabs/pages, hierarchy —
   never text-only), CLI (C, every livingui operation CraftBot needs), and
   Quality of Life (Q, scope-specific power-UX you invent for THIS app:
   shortcuts, drag & drop, multi-select, context menus, mobile, and more).
   There is NO item quota — depth follows from THIS app's scope: cover
   every aspect exhaustively (a rich app yields a long ledger). Validation
   refuses missing/empty sections and unfinished ledgers. Tick items BY
   ID as you fulfill them: living_ui_tick_requirements(project_id,
   ids=["F3", "V6", ...]) — never flip checkboxes with stream_edit (exact
   string matching fails; stream_edit is only for rewording an item).
5. LAYOUT WIREFRAME FIRST (before ANY backend work): rewrite MainView.tsx as
   a TEXTLESS LAYOUT KIT assembly — <AppShell> with one <Section> per
   planned region (NO title/meta), each holding Skeleton* blocks ARRANGED
   to match that region's intended shape (thin row for tabs, CardGrid of
   SkeletonCards for a feed, short blocks for stats). There is NO page
   header/title band — the page starts with its content Sections. The
   wireframe contains NO text, NO titles, NO labels, NO interactive
   elements — it purely books each region's area and general layout.
   Every part MUST be replaced as features complete (features add real
   titles/actions); leftover Skeletons in MainView FAIL validation. The
   platform flags backend writes made before the wireframe exists.
6. Break the app into FEATURES (user-facing capabilities), then build ONE
   FEATURE at a time — its backend todo, then its frontend todo, each as
   ONE batched step (actions in a step run sequentially in order; a
   failure skips the rest — so a red pytest automatically protects later
   actions):
   - Backend step: write backend tests (no live-network dependencies;
     camelCase assertions matching to_dict) + REWRITE models.py whole-file
     with your models added + REWRITE routes.py whole-file (never
     stream_edit appends — they corrupt these files) + run pytest. If
     pytest failed, fix ALL reported errors in one batched step and re-run
     — NEVER proceed with red tests, NEVER seed fake data to pass them.
   - Frontend step: edit types.ts + AppController methods + write_file the
     complete FINAL component(s) for this feature (real fetch calls, real
     handlers, empty states, scoped <style>) + edit MainView.tsx to mount
     them, replacing that region's Skeletons and finalizing its
     title/actions + ONE living_ui_tick_requirements call listing every ID
     this feature fulfilled.
   A feature is DONE only when its user flow works END TO END in the
   running app: the control opens the real form/modal (never a browser
   prompt/confirm), submits to the backend, and the view updates. A
   feature that renders but does nothing is NOT done. A feature with no
   new backend keeps only its frontend todo — never invent filler backend
   work. NEVER write a static stub or draft component (placeholder
   handlers like onClick={{() => {{}}}} are a violation) — final form
   only, written once. Do NOT skip features listed in LIVING_UI.md. A
   working app with all planned features is the goal — validation REFUSES
   unmounted components and leftover Skeletons in MainView.
7. Update LIVING_UI.md with implementation details
8. DESIGN SELF-REVIEW (mandatory, BEFORE validating): the live preview
   saves your app's screenshot to {project_path}/logs/design_preview.png.
   Run describe_image on it with the skill's design-review prompt. The
   reviewer distinguishes GENUINE DEFECTS (broken, unfinished, or
   hard-to-use: clipped/overlapping text, unstyled or colliding elements,
   unreadable text, text-only walls with no visual structure) from
   INTENTIONAL DESIGN DECISIONS (hierarchy via muted styling, whitespace,
   empty states in an app with no data yet), and judges the app in its
   CURRENT state. Fix genuine defects and re-review until PASS — do not
   churn on things the review deems defensible design. (Skip only if the
   file does not exist.)
9. Run living_ui_validate(project_id="{project_id}") — ONLY once every
   ledger box is ticked: validation VERIFIES finished work, it is not a
   probe for what's left (calling it early just refuses and wastes a run).
   It runs the full pipeline (requirements gate FIRST — unfulfilled
   LIVING_UI.md items are refused immediately with their IDs — then
   install, tests, build, backend + smoke tests, ops check, and a DESIGN
   gate on rendered-layout facts: overflow, clipped text, empty sections,
   zero icons). Fix every error it reports and re-run until it PASSES.
   The ledger is a COMMITMENT: when validation reports unfulfilled items,
   the only response is to BUILD them. NEVER ask the user for permission
   to skip, defer, or descope ledger items, and never mark items
   out-of-scope — proposing to shrink your own committed scope is a
   violation. Scope shrinks only if the USER, unprompted, orders it.
10. Call living_ui_notify_ready(project_id="{project_id}") — presents the app
   to the user. It REFUSES if validation has not passed (and editing code
   after a pass clears it, so validate again after any fix).

NEVER mark a todo completed without having done its work — validation
verifies the filesystem and will refuse an unbuilt app, and notify_ready
refuses without a validation pass.

What a GOOD Living UI looks like:
- Professional web app layout — proper spacing, visual hierarchy, sections, headers
- Uses preset components (Button, Card, Input, Modal, Table from './components/ui') — never raw HTML
- Thoughtful layout: sidebar or top nav, content area with grid/list views, detail panels or modals
- Colors from GLOBAL_LIVING_UI.md applied consistently
- Visually rich, never all-text: lucide-react icons on headers/buttons/empty
  states, IconBadge/StatCard accents, consistent font sizes with clear hierarchy
- Empty state when no data — the app launches with an empty database, users create their own content
- "Add" actions open forms/modals with proper input fields — never auto-create with placeholder text
- Every item is viewable, editable, and deletable through the UI
- Error handling with toast notifications on API failures
- Responsive design that works on different screen sizes

When pytest fails:
- Read ALL errors carefully before fixing — fix ALL issues in one batched step, not one at a time
- If you see an import error, check ALL files for the same pattern and fix them all
- NEVER proceed with failing tests and NEVER seed fake data to pass them — validation refuses red tests, so debts always come back to you
- Tests must not depend on live internet: external-fetch endpoints degrade gracefully; test the non-network paths
- Common fix: relative imports (from . import X) → absolute imports (from X import Y)

External integrations (Gmail, YouTube, Discord, Slack, etc.):
- CraftBot has connected external services — use the integration bridge, NOT custom OAuth
- Import: from services.integration_client import integration
- Call: result = await integration.request("google_workspace", "GET", url)
- NEVER build OAuth flows, ask for API keys, or store credentials
- See the "External Integrations" section in SKILL.md for details and examples

What to AVOID:
- Flat list of items with no visual structure
- Custom CSS when preset components exist
- Hardcoded test data left in the database
- Buttons that create items without user input
- Everything crammed into one component file (MainView is a layout assembly — every region is its own file)
- Marking todos complete without doing the work, or calling living_ui_notify_ready
  before the app is built — the launch pipeline checks the filesystem and blocks it
- Relative imports in backend code
- Running uvicorn/npm manually — the launch pipeline handles this
- Editing main.py, main.tsx, manifest.json, or tests/conftest.py — system managed
- Rewriting conftest.py — it has the correct imports and test DB setup already

Your todo list should follow this EXACT pattern — do NOT add extra sub-steps:
Phase 0: Read global config
Phase 0: Ask user batch 1 (data/features)
Phase 0: Ask user batch 2 (design/layout)
Phase 0: Write the requirement ledger in LIVING_UI.md
Phase 1: Plan features
Layout wireframe — page frame + placeholder regions
Feature 1 - [name]: Backend (tests + model + routes + pytest)
Feature 1 - [name]: Frontend (types + components + controller, mounted + ticked)
Feature 2 - [name]: Backend (tests + model + routes + pytest)
Feature 2 - [name]: Frontend (types + components + controller, mounted + ticked)
... repeat for each feature ...
Update LIVING_UI.md with implementation details
Design self-review: describe_image on logs/design_preview.png until PASS
Validate: living_ui_validate until it passes
Call living_ui_notify_ready

IMPORTANT about features:
- Each feature is a USER-FACING capability (e.g., "Column CRUD", "Task
  Cards", "Search/Filter") — NOT a visual region, NOT a layer
- "Backend Setup" or "Frontend Setup" are NOT features — they are layers,
  and layer-shaped todos are a workflow violation
- Each feature has BOTH backend AND frontend todos; a feature with no new
  backend keeps only its frontend todo
- Keep exactly 2 todos per feature (backend + frontend) — do NOT split
  into 10+ sub-steps
- Emit each todo's work as ONE batched step, not one action per decision
- Finer-grained progress lives in the LIVING_UI.md ledger, ticked by ID
  via living_ui_tick_requirements at the end of each feature's frontend
  step — never as extra todos
- Write ALL tests for a feature at once, not one endpoint at a time
- Every component is written ONCE, in its final live form, with its CSS in the
  same write — static stubs, drafts, and placeholder handlers are violations
- The mount (MainView imports and renders it) happens in the SAME step the
  component is written — unmounted components are invisible and validation
  refuses them
- Use write_file with complete file content for new files and rewrites;
  stream_edit only for small local changes; do NOT re-read files you wrote
  this task — trust your writes
- A todo may only be marked completed AFTER its files are actually written
  and, for frontend todos, the feature's user flow actually works"""
