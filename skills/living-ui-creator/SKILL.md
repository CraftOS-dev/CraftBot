---
name: living-ui-creator
description: Create Living UI applications (V2 — PocketBase backend, React kit frontend). Scaffolds, develops, validates, and launches local web apps with persistent state and realtime UI.
action-sets:
  - file_operations
  - code_execution
  - living_ui
---

# Living UI Creator (V2)

A Living UI is a self-contained local web app: **one PocketBase process** (data,
auth, realtime, custom verbs) serving a **React frontend built from a preset
kit**. You declare schema, compose UI, wire verbs — the platform owns the rest.

## Step 0: Have a registered project (MANDATORY FIRST)

1. **Task instruction contains `Project ID` + `Project Path`** → the project is
   already scaffolded. Use those values. **Skip scaffolding.**
2. **No Project ID in your instruction** (user asked in a regular chat) → call
   `living_ui_scaffold(name, description, auth_mode)` — it scaffolds AND
   dispatches the build to the project's dedicated session. Tell the user the
   build started, then end your turn. Do NOT build in the chat session.

Pick `auth_mode` from requirements: `none` (personal local tool — default) or
`multi-user` (accounts; the kit's LoginGate wraps the app automatically).

## The ownership rule (the gate enforces this)

Edit ONLY:

| Path | Purpose |
|------|---------|
| `frontend/src/app/` | all UI code |
| `pb/pb_migrations/` | schema — one NEW migration per change |
| `pb/pb_hooks/ops.pb.js` + new `*.pb.js` | custom verbs |
| `operations.json` | declarations for those verbs (non-`system` entries) |
| `LIVING_UI.md` | your plan/context/index — keep current |

NEVER edit `frontend/src/kit/`, `frontend/src/main.tsx`, `frontend/src/config.gen.ts`,
`pb/pb_hooks/_system.pb.js`, `manifest.json`, or build configs — the validation
gate hashes them and **fails the build** if they changed. Need a variant of a
kit component? Wrap it in `app/`:

```tsx
// frontend/src/app/components/DueBadge.tsx
import { cn } from '../../kit/index.ts';
export function DueBadge({ overdue }: { overdue: boolean }) { /* compose */ }
```

## Before coding

1. Read `agent_file_system/GLOBAL_LIVING_UI.md` — colors, fonts, enforced rules.
2. Read `{project_path}/LIVING_UI.md` and `reference/requirements.md`. The
   creation wizard interviewed the user and synthesized `requirements.md` — it
   is the **binding spec**: implement it exactly and mirror its checklist into
   `LIVING_UI.md`. If it is absent, build from the project description; only ask
   the user (a FINAL `send_message`, `continue_work=false`) when something is
   genuinely blocking and you cannot reasonably decide it yourself.
3. A Living UI build is substantial work — the standard run protocol applies
   as-is (scope, plan, execute, verify, deliver); this skill adds nothing to
   it. `reference/requirements.md` is the binding spec verification checks
   against; mirror the feature checklist in `LIVING_UI.md`.

## Per feature: schema → verbs → UI

**Schema** — add a new file in `pb/pb_migrations/` (never edit an applied one).
Follow the starter migration's pattern exactly: field types, `autodate`
created/updated, and rules matching the project's `authMode` (`manifest.json`):
`''` open rules for `none`; `@request.auth.id != ""` (or owner-scoped
`owner = @request.auth.id` with a `relation` to `users`) for `multi-user`.

**Relation fields — the #1 migration mistake:** `collectionId` must be the
target collection's **ID, never its name**. Save the target collection first,
then reference it:

```js
const words = new Collection({ name: 'words', /* … */ });
app.save(words);
const reviews = new Collection({
  name: 'reviews',
  fields: [
    { name: 'word', type: 'relation', required: true,
      collectionId: app.findCollectionByNameOrId('words').id, cascadeDelete: true },
    /* … */
  ],
});
app.save(reviews);
```

**Custom verbs** — anything beyond CRUD is a `routerAdd` route in
`pb/pb_hooks/ops.pb.js` PLUS a matching entry in `operations.json` (see the
working `items.clear-done` example). The gate fails ops without routes and
warns about routes without ops. Mark data-deleting ops `"destructive": true`.
Plain CRUD needs no verb — the PB API and the kit hooks already cover it.

**Request bodies in hooks: `e.requestInfo().body` ONLY** (a pre-parsed
object). `toString(e.request.body)` reads a Go stream as EMPTY — your handler
will 400 on every request and the error will falsely blame the client.

**Naming: kebab-case everywhere, all three places must agree** — the op `name`
in operations.json, the `routerAdd` path in pb_hooks, and every frontend call:
`"plan.generate"` ↔ `/api/ops/plan-generate` ↔ `fetch('/api/ops/plan-generate')`.
Pick the names once, before writing any of the three.

**Load-time calls must survive an EMPTY database.** A fresh app has no records:
never call ops or filtered queries at page load that 400 without data — gate
them behind existence checks (e.g. only call plan ops after a profile exists).
The launch verifier fails the app on any first-paint console error.

**UI** — build in `frontend/src/app/`, importing ONLY from `../kit/index.ts`:

- Read data with `useCollection('name', { sort: '-created' })` — it is
  **realtime**; never poll, never reload.
- Write with `await getPbClient().call((pb) => pb.collection('name').create(...))`
  — failures toast automatically.
- Components: `Button, Input, Card/CardHeader/CardBody, Dialog, Table, LoginGate`,
  plus `toast` for feedback and `useAuth()` in multi-user apps.
- Style with Tailwind utilities + kit tokens (`var(--lui-*)`). Never hardcode
  colors — theming is host-owned (style packs + dark mode must keep working).
- Required UX: empty states with an action, loading states, confirmation
  dialogs for destructive actions, toasts on CRUD, responsive layout.

Update `LIVING_UI.md` after each feature (entities table, ops list, checklist).

## Finish: launch, then verify

1. `living_ui_notify_ready(project_id="<PROJECT_ID>")` — runs the gate
   (**types → build → migrations-on-fresh-db → ops → ownership**), starts the
   app and health-checks it. On errors: read ALL of them, fix ALL of them,
   call it again. Success = app RUNNING but NOT yet verified. Never start
   servers manually.
2. `living_ui_walk_verify(project_id="<PROJECT_ID>")` — an independent
   sub-agent walks the running app in a real (headless) browser against
   `reference/requirements.md`. **Success announces the app to the user and
   completes the build.** Failing features come back as a report: fix them,
   then repeat step 1 and step 2.

**HONESTY RULE:** the app is ready ONLY when `living_ui_walk_verify` returns
`status: success`. If you cannot make it pass, tell the user the build
**failed** and exactly what's blocking. Never claim a broken app is ready.

## Debugging

- Frontend runtime errors: `{project_path}/logs/frontend_console.log`
  (console.error/warn + uncaught errors are auto-relayed).
- Server: `{project_path}/logs/pocketbase.log`.
- Data inspection: the PB REST API on the project's port
  (`GET /api/collections/<name>/records`).

## FORBIDDEN

- Editing system-managed files (see ownership rule) — the gate will fail
- Editing an already-applied migration — add a new one
- Custom fetch layers, polling, or page reloads — use the kit's realtime hooks
- Hardcoded colors or raw `<button>`/`<input>` — kit components + tokens only
- Declaring ops without routes (or routes without ops)
- Printing or copying `.superuser` credentials
- Starting `pocketbase`, `vite`, or `npm run` servers by hand
- Ending the run mid-build — pause ONLY for a user question (final
  send_message), finish ONLY via `living_ui_walk_verify`
