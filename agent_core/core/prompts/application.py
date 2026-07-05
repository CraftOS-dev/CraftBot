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

Follow the living-ui-creator skill instructions. Here's the workflow:

1. Read agent_file_system/GLOBAL_LIVING_UI.md — apply its colors, fonts, and rules
2. Phase 0: Ask the user 2+ batches of questions about data, features, design, and layout
3. Document requirements in LIVING_UI.md
4. Break the app into features, then for each feature:
   - Re-read LIVING_UI.md (check what's left) and GLOBAL_LIVING_UI.md (refresh design rules)
   - Write backend tests first (backend/tests/)
   - Create model + routes to pass tests
   - Run pytest to verify
   - Create frontend types + components
   - Update LIVING_UI.md — mark this feature as done, add models/routes/components you created
   Do NOT skip features listed in LIVING_UI.md. A working app with all planned features is the goal.
5. Update LIVING_UI.md with implementation details
6. Call living_ui_notify_ready(project_id="{project_id}")

What a GOOD Living UI looks like:
- Professional web app layout — proper spacing, visual hierarchy, sections, headers
- Uses preset components (Button, Card, Input, Modal, Table from './components/ui') — never raw HTML
- Thoughtful layout: sidebar or top nav, content area with grid/list views, detail panels or modals
- Colors from GLOBAL_LIVING_UI.md applied consistently
- Empty state when no data — the app launches with an empty database, users create their own content
- "Add" actions open forms/modals with proper input fields — never auto-create with placeholder text
- Every item is viewable, editable, and deletable through the UI
- Error handling with toast notifications on API failures
- Responsive design that works on different screen sizes

When pytest fails:
- Read ALL errors carefully before fixing — fix ALL issues in one go, not one at a time
- If you see an import error, check ALL files for the same pattern and fix them all
- Maximum 3 pytest attempts per feature. If still failing after 3, review your approach
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
- Everything crammed into one component file
- Relative imports in backend code
- Running uvicorn/npm manually — the launch pipeline handles this
- Editing main.py, main.tsx, manifest.json, or tests/conftest.py — system managed
- Rewriting conftest.py — it has the correct imports and test DB setup already

Your todo list should follow this EXACT pattern — do NOT add extra sub-steps:
Phase 0: Read global config
Phase 0: Ask user batch 1 (data/features)
Phase 0: Ask user batch 2 (design/layout)
Phase 0: Document requirements in LIVING_UI.md
Phase 1: Plan features
Feature 1 - [name]: Backend (tests + model + routes + pytest)
Feature 1 - [name]: Frontend (types + components + controller)
Feature 2 - [name]: Backend (tests + model + routes + pytest)
Feature 2 - [name]: Frontend (types + components + controller)
Feature 3 - [name]: Backend (tests + model + routes + pytest)
Feature 3 - [name]: Frontend (types + components + controller)
... repeat for each feature ...
Update LIVING_UI.md with implementation details
Call living_ui_notify_ready

IMPORTANT about features:
- Each feature is a USER-FACING capability (e.g., "Board Items", "Media Attachments", "Search/Filter")
- "Backend Setup" or "Frontend Setup" are NOT features — they are layers
- Each feature MUST have BOTH backend AND frontend todos — never just one
- Keep exactly 2 todos per feature (backend + frontend) — do NOT split into 10+ sub-steps
- Write ALL tests for a feature at once, not one endpoint at a time"""
