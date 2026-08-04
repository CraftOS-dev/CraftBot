---
name: living-ui-importer
description: Install Living UI apps from the marketplace or import exported Living UI V2 ZIPs. Registers, launches, and verifies imported projects.
action-sets:
  - file_operations
  - living_ui
---

# Living UI Importer (V2)

Bring existing Living UI apps into this CraftBot: **marketplace installs**
(pre-built apps from the catalogue) and **V2 export ZIPs** (round-trip with
the export feature). That is the full scope — arbitrary foreign apps
(Go/Node/Docker repos, random GitHub projects) are NOT importable yet; tell
the user so honestly instead of improvising.

## Which path?

| The user has… | Do this |
|---|---|
| An app name / "what's in the marketplace?" | `living_ui_marketplace_list` → match by name → `living_ui_marketplace_install(app_id=...)` |
| A `.zip` exported from a Living UI | `living_ui_import_zip(zip_path=...)` → launch → verify |
| A GitHub repo / foreign codebase | Not supported yet — say so and stop |

## Marketplace install

1. `living_ui_marketplace_list` — resolve the exact `app_id` (never guess
   ids; match the user's words against names/descriptions).
2. `living_ui_marketplace_install(app_id="...", name="...")` — downloads,
   registers, and **launches** the app in one step.
3. On success, tell the user the app name and URL. Marketplace apps are
   pre-built and pre-verified upstream — no walk-verify needed.
   NOTE: apps still in the legacy V1 format are rejected with a clear
   error — the platform is V2-only. Tell the user that app hasn't been
   re-published for this version of CraftBot yet; do not improvise a
   workaround.
4. On a launch error, treat it like any build failure: read ALL errors,
   fix (the project is a normal V2 project under the ownership rules),
   `living_ui_notify_ready` again.

## ZIP import

1. `living_ui_import_zip(zip_path="/absolute/path.zip")` — registers a NEW
   project (fresh id + port, shipped credentials stripped, kit re-vendored).
   Only Living UI V2 exports are accepted; anything else errors.
2. `living_ui_notify_ready(project_id="<ID>")` — gate + launch. Fix any
   gate errors exactly as in the creator workflow (same ownership rules:
   edit only `frontend/src/app/`, `pb/pb_migrations/`, `pb/pb_hooks/`,
   `operations.json`, `LIVING_UI.md`).
3. `living_ui_walk_verify(project_id="<ID>")` — verifies the running app
   (against `reference/requirements.md` if the export shipped one, else its
   `LIVING_UI.md` checklist) and announces it. HONESTY RULE: the import is
   done ONLY when this returns success.

## Notes

- Imported/installed projects are ordinary V2 projects afterwards: operate
  them via the lui CLI (`ops` / `run` / `data`), modify them via the
  living-ui-modify workflow.
- Never edit `frontend/src/kit/`, `manifest.json`, or other system files —
  the validation gate hashes them.
- If an import fails with "no manifest.json" or "Only Living UI V2", the
  ZIP is not a V2 export — tell the user what it actually needs to be.
