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
Theme: {theme}
Project Path: {project_path}

REQUIREMENTS — the complete, binding specification for this app. It was
gathered from the user's configuration and interview BEFORE this task
started (also saved at {project_path}/reference/requirements.md); the user
will NOT answer further questions, so never ask — where the spec is
silent, decide and build:

{requirements}

Reference files the user provided (design sketches, screenshots,
documents) — study each BEFORE the wireframe; view images with
describe_image:
{reference_files}

The user WATCHES this app being built in a live preview — the screen must
visibly change every few minutes, so after the wireframe you build
incrementally, bringing one capability fully to life at a time (its data,
endpoints, and UI together, mounted as you go) rather than doing all
backend then all frontend, which freezes the preview for a long stretch.
Follow the living-ui-creator skill instructions. Here's the workflow:

1. Read agent_file_system/GLOBAL_LIVING_UI.md — apply its colors, fonts,
   and rules — and study the reference files listed above (describe_image
   for images). Do NOT call set_requirement (the REQUIREMENTS section
   above is the requirement record; skip that step entirely) and NEVER
   ask the user questions — requirement gathering already happened in the
   creation wizard.
2. CREATE THE TODO LIST NOW — immediately after that, call
   task_update_todos with the FULL plan, shaped to fit the app (the skill
   shows a sensible default; adapt it). The todo list is the user's
   progress display from the first second; nothing else happens before it
   exists.
3. LAYOUT WIREFRAME FIRST (before ANY backend work): rewrite MainView.tsx as
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
4. BUILD THE APP to fulfill the REQUIREMENTS — work the way you would in
   any codebase; there is NO forced backend-then-frontend order:
   - READ before you write: the existing files you're about to change
     (backend/models.py, backend/routes.py, frontend/AppController.ts, the
     component files) and LIVING_UI.md for project-specific notes — and
     follow their conventions.
   - Build INCREMENTALLY so the preview keeps changing: take one
     capability at a time all the way to working (its data, endpoints, and
     UI, mounting each component as you write it). You choose the order and
     grouping. Don't do all backend then all frontend — that leaves the
     screen frozen.
   - RUN tests / lint / the build when it helps you catch a problem early
     (find the project's commands first). You are NOT required to per
     step — living_ui_validate runs the full suite at the end, so don't
     re-run after every small change.
   - Every capability must WORK END TO END in the running app: the control
     opens a real form/modal (never a browser prompt/confirm), submits to
     the backend, and the view updates. Renders-but-does-nothing is NOT
     done.
   Rules that always hold: whole-file rewrites for models.py/routes.py
   (stream_edit appends corrupt them); NEVER seed fake data to pass a test;
   every component is written ONCE in final form with its CSS in the same
   write (no static stubs, no placeholder handlers like
   onClick={{() => {{}}}}); mount every component (unmounted = invisible,
   validation refuses it); replace every wireframe Skeleton (leftovers
   FAIL validation); build the FULL scope the REQUIREMENTS specify — skip
   nothing.
5. Update LIVING_UI.md with implementation details
6. DESIGN SELF-REVIEW (mandatory, BEFORE validating): the live preview
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
7. Run living_ui_validate(project_id="{project_id}") — ONLY once every
   feature is built and its flow works: validation VERIFIES finished
   work, it is not a probe for what's left. It runs the full pipeline
   (completeness/mounting checks, install, tests, build, backend + smoke
   tests, ops check, and a DESIGN gate on rendered-layout facts:
   overflow, clipped text, empty sections, zero icons). Fix every error
   it reports and re-run until it PASSES. The REQUIREMENTS are a
   COMMITMENT: build all of them. NEVER ask the user for permission to
   skip, defer, or descope anything, and never mark items out-of-scope —
   proposing to shrink your own committed scope is a violation. Scope
   shrinks only if the USER, unprompted, orders it.
8. Call living_ui_notify_ready(project_id="{project_id}") — presents the app
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

Backend tests:
- Write them alongside the models/routes they cover. Run pytest when it
  helps you catch something early — you're not required to per capability,
  and living_ui_validate runs the full suite at the end, so don't re-run
  after every small change.
- NEVER seed fake data to make a test pass — validation refuses red tests, so debts always come back to you
- Tests must not depend on live internet: external-fetch endpoints degrade gracefully; test the non-network paths
- When validate reports failures: read ALL errors before fixing; if it's an import error, check ALL files for the same pattern. Common fix: relative imports (from . import X) → absolute imports (from X import Y)

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

Shape your todo list to the app — this is a sensible DEFAULT, adapt it
(one line per capability; keep it coarse so updates stay cheap):
Read global config + reference files
Layout wireframe — page frame + placeholder regions
Build <capability A> (data + API + UI, mounted)
Build <capability B> (data + API + UI, mounted)
... one line per capability ...
Update LIVING_UI.md with implementation details
Design self-review: describe_image on logs/design_preview.png until PASS
Validate: living_ui_validate until it passes
Call living_ui_notify_ready

How to build:
- Plan around USER-FACING capabilities (e.g. "Column CRUD", "Task Cards",
  "Search/Filter"), NOT layers. "Backend Setup" / "Frontend Setup" as
  top-level phases are the anti-pattern — they leave the preview frozen
  for a long stretch. Keep each capability's data + endpoints + UI close
  together.
- You choose the granularity and order of the todos and how you sequence
  the work — keep todos coarse (a capability, not one endpoint) so updates
  stay cheap.
- READ the existing code and LIVING_UI.md before writing; follow the
  conventions already there.
- RUN tests / lint / the build when it helps you (find the commands
  first); not required per step — validate runs the full suite at the end.
- Every component is written ONCE, in its final live form, with its CSS in
  the same write — static stubs, drafts, and placeholder handlers are
  violations.
- Mount every component in the same step you write it — unmounted
  components are invisible and validation refuses them.
- Whole-file rewrites for models.py/routes.py; stream_edit only for small
  local changes; do NOT re-read files you wrote this task — trust your
  writes.
- A todo is complete only AFTER its files are written and, for anything
  user-facing, the flow actually works."""
