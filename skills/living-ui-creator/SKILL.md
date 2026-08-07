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
| `pb/pb_hooks/ops.pb.js` + new `*.pb.js` / `*.js` modules | custom verbs + their helpers |
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

0. **If `reference/requirements.md` starts with `MARKETPLACE DECISION: install
   <app-id>`** — do NOT build. Call
   `living_ui_marketplace_install(app_id=..., name=..., description=...,
   will_adapt=<true if the decision line says adapt: yes>)`. It installs INTO
   this project (same tab and id — never a duplicate).
   - `adapt: no` — the install completes the build and the system announces
     it; do NOT send your own summary and do NOT call notify_ready or
     walk_verify. End the run.
   - `adapt: yes` — after the install, apply ONLY the adaptations listed
     under `## Adaptations` (modify flow: edit → `living_ui_notify_ready` →
     `living_ui_walk_verify`). If the list says "none specified", ask the
     user what to change (a FINAL `send_message`) instead of guessing.
   The user explicitly chose reuse over a fresh build — never rebuild what
   was just installed, even if a later trigger asks you to "continue" it.
1. Read `agent_file_system/GLOBAL_LIVING_UI.md` — colors, fonts, enforced rules.
2. Read `{project_path}/LIVING_UI.md` and `reference/requirements.md`. The
   creation wizard interviewed the user and synthesized `requirements.md` — it
   is the **binding spec**: implement it exactly and mirror its checklist into
   `LIVING_UI.md`. If it is absent, build from the project description; only ask
   the user (a FINAL `send_message`, `continue_work=false`) when something is
   genuinely blocking and you cannot reasonably decide it yourself.
3. **Any feature need data from outside the app? Check, then research.**
   FIRST check the `[INTEGRATIONS this app can use]` block already in your
   context — if a connected integration's action covers the feature (email =
   `send_gmail`), use `bridge.callAction`; nothing to research. Only for
   THIRD-PARTY public APIs: research like an engineer — endpoint, auth,
   response shape, limits. Spawn a research_agent; never write an
   integration hook from memory.
   - User named an API/service → research it. If it needs a key, tenant URL,
     or account detail you cannot find online, ask the user (final
     `send_message`) and build the rest of the app while waiting.
   - No API named → research candidates and pick a **keyless public API**
     yourself (e.g. Open-Meteo for weather). Choosing the source is your
     engineering call — no user round-trip.
   - Nothing usable exists → build the honest empty/offline state and REPORT
     the blocker in your final message. **Mock or generated data is forbidden**
     unless requirements explicitly ask for demo data.
4. A Living UI build is substantial work — the standard run protocol applies
   as-is (scope, plan, execute, verify, deliver); this skill adds nothing to
   it. `reference/requirements.md` is the binding spec verification checks
   against; mirror the feature checklist in `LIVING_UI.md`.

## Per feature: schema → verbs → UI

**Schema** — add a new file in `pb/pb_migrations/`. **Never edit AND never
rename or delete a migration that has been applied** (i.e. after any
successful launch): the filename is the identity in the live database.
Renaming one makes every boot re-run its "new" replacement into the existing
schema — PocketBase exits before serving anything and the app cannot start
until the original filename is restored. Fixing a migration's mistake =
writing a NEW migration that alters the collection.
The ONLY top-level call is `migrate(upFn, downFn)` — the down/rollback
function is the **second argument**. A top-level `rollback(...)` does not
exist and panics the whole PocketBase process at load. Follow the starter
migration's pattern exactly: field types, `autodate`
created/updated, and rules matching the project's `authMode` (`manifest.json`):
`''` open rules for `none`; `@request.auth.id != ""` (or owner-scoped
`owner = @request.auth.id` with a `relation` to `users`) for `multi-user`.

**Seeding records in a migration:** `new Record(...)` takes the **Collection
OBJECT — never an id string**. Passing `someCollection.id` nil-panics
PocketBase internally and can WEDGE the process (alive, silent, never
serving). The gate kills and reports it, but write it right:

```js
const locations = app.findCollectionByNameOrId('locations'); // the OBJECT
const record = new Record(locations);
record.set('city_name', 'Manchester');
app.save(record);
```

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

**External data (third-party APIs)** — Living UIs CAN call the internet, from
**hooks only** (never the frontend: browser CORS breaks and keys would be
visible). Use `$http.send`.

**THE #1 HOOK TRAP — handlers run in ISOLATED VMs.** Code inside a
`routerAdd`/`cronAdd`/`onRecord*` callback **cannot see file-level `const`s
or functions**: it throws `X is not defined` at REQUEST time, which the gate
(registration-time only) cannot catch. Share logic via a plain `.js` module
and `require()` it INSIDE each callback — module scope IS visible within the
module:

```js
// pb/pb_hooks/weather.js — a MODULE (plain .js, not .pb.js)
const OPEN_METEO = 'https://api.open-meteo.com/v1/forecast'; // literal → recorded as egress

function refreshAll(app) {
  const res = $http.send({
    url: OPEN_METEO + '?latitude=53.48&longitude=-2.24&current=temperature_2m,wind_speed_10m',
    method: 'GET',
    timeout: 20,                                  // ALWAYS set a timeout
  });
  if (res.statusCode !== 200) {
    throw new Error('weather source returned HTTP ' + res.statusCode);
  }
  const data = res.json;   // ONLY correct way to read the body — pre-parsed.
  // res.body is a Go BYTE SLICE: JSON.parse(String(res.body)) throws
  // "SyntaxError: Unexpected token at the end" on every response. If you
  // remember fetch-style res.body/JSON.parse, that is the WRONG API here.
  // …store readings via app.save(...) and return them
}
module.exports = { refreshAll: refreshAll };
```

```js
// pb/pb_hooks/ops.pb.js — the route + the scheduled job use the SAME code path
routerAdd('POST', '/api/ops/weather-refresh', (e) => {
  const weather = require(`${__hooks}/weather.js`);   // require INSIDE the handler
  try {
    return e.json(200, { updated: weather.refreshAll(e.app).length });
  } catch (err) {
    console.error('weather-refresh failed:', err);    // → logs/pocketbase.log — ALWAYS
    return e.json(502, { error: String(err) });       //   log the CAUSE before the 502;
  }                                                   //   the browser only sees the status
});

cronAdd('weatherSync', '*/15 * * * *', () => {
  const weather = require(`${__hooks}/weather.js`);
  try { weather.refreshAll($app); }
  catch (err) { console.error('weatherSync failed:', err); }
});
```

- **Current PB API only:** `app.findRecordsByFilter(...)`, `app.save(...)`,
  `app.delete(...)`. `$app.dao()` does **NOT exist** in this PocketBase — it
  throws `Object has no member 'dao'`. If you remember `.dao()` from
  tutorials, your memory is a major version out of date; copy the working
  `items.clear-done` example instead.
- **PB find helpers THROW on no rows — they never return null.**
  `findFirstRecordByFilter`/`findRecordById` on zero matches throws NotFound,
  which surfaces as a bare 404 response. `if (!rec)` after them is dead code.
  Wrap in try/catch (catch = "not found") or use
  `findRecordsByFilter(collection, filter, sort, LIMIT, OFFSET)` and check
  `.length`. Corollary when debugging: **a 404 from a route you declared
  means your HANDLER threw, not that the route is missing** — check
  logs/pocketbase.log for the `[handler-error]` line with the real cause.
- Keep base URLs as string **literals** in the module (the tooling records
  the app's external hosts in the manifest from them).
- Unreachable source / non-200 → `console.error` the cause, return a clean
  error; the UI shows its offline/empty state. **NEVER substitute generated
  or random data for real data** — a mock that renders is a lie that passes
  review. If the source cannot be reached, the app says so and so do you.
- CraftBot's own connected services (Gmail, Slack, Notion, …) are NOT called
  this way — see `references/INTEGRATIONS.md` (the `_craftbot_bridge.js`
  helper). Third-party public APIs: direct `$http.send` as above.

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

**App→agent triggers** — when a feature needs the AGENT to react to something
happening in the app (a button that asks the agent to act, backend logic that
crossed a threshold), declare it in `triggers.json` and fire it via the kit's
`fireAgentTrigger` (frontend) or `_triggers_lib.js`'s `fire()` (hooks) — see
`references/TRIGGERS.md` for the manifest format, the trust rules, and the
design rules (idempotent instructions, generous cooldowns). Declare a trigger
only where agent judgment adds value — plain code handles plain events.

## Finish: launch, then verify

1. `living_ui_notify_ready(project_id="<PROJECT_ID>")` — runs the gate
   (**types → build → migrations-on-fresh-db → ops → ownership**), starts the
   app and health-checks it. On errors: read ALL of them, fix ALL of them,
   call it again. Success = app RUNNING but NOT yet verified. Never start
   servers manually.
2. **REALITY CHECK — look at what actually exists, not at what you wrote.**
   Success messages lie by omission; stored state does not. While the app
   runs:
   - `GET /api/_a2app/describe` → does every collection show the FIELDS you
     migrated? A collection showing only `id` means your migration silently
     did nothing (wrong key, wrong API — the cause doesn't matter, the
     emptiness is the proof).
   - Trigger one real data flow (call your refresh/main op), then read a
     record back (`GET /api/collections/<name>/records?perPage=1`) and LOOK
     at the values. Missing fields, empty strings, all-zero numbers = the
     write silently failed, whatever the op's status code said.
   - Any path you CANNOT trigger for real (scheduled email, posts to the
     user's accounts): **dry-run it** — `callAction(name, sameParams,
     { confirmIrreversible: true, dryRun: true })` validates grant, params,
     placeholders and confirmation without executing. A path that was never
     run NOR dry-run is not done, whatever the code looks like.
   Reason about ANY mismatch between what you intended and what is stored —
   fix it before verifying. This catches the failure classes no error
   message reports.
3. `living_ui_walk_verify(project_id="<PROJECT_ID>")` — an independent
   sub-agent walks the running app in a real (headless) browser against
   `reference/requirements.md`. **Success announces the app to the user and
   completes the build.** Failing features come back as a report: fix them,
   then repeat step 1 and step 3.

Test data is fine during the build: at delivery the platform resets the
app's data to its pristine post-migration state, so records you or the
verifier created never reach the user. Data your migrations SEED survives
(they re-run on the clean DB) — put anything the user must see on first
open in a migration, never insert it by hand. Externally-fetched data is
reset too: an app that syncs from an API must self-populate on an empty
DB (fetch at boot or when the collection is empty — never rely on a sync
that happened during the build).

**HONESTY RULE:** the app is ready ONLY when `living_ui_walk_verify` returns
`status: success`. If you cannot make it pass, tell the user the build
**failed** and exactly what's blocking. Never claim a broken app is ready,
and never present generated data as live data — "live" in your message means
the app fetched it from the real source.

## Debugging

- Full platform reference (bridge, jobs, kit API):
  `living-ui-v2/docs/agent-guide.md` (repo-level, read on demand).
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
- Mock/random data standing in for external data (`Math.random()` weather,
  hardcoded "sample" rows) — unreachable source means an honest empty state
  plus a report, not a simulation
- Printing or copying `.superuser` credentials
- Starting `pocketbase`, `vite`, or `npm run` servers by hand
- Ending the run mid-build — pause ONLY for a user question (final
  send_message), finish ONLY via `living_ui_walk_verify`
