# Agent Guide — Building and Operating a Living UI (V2)

Audience: the agent building or operating a Living UI project. This is the
source document CraftBot's `living-ui-*` skills compile from (spec A5).

---

## 1. The one rule that matters: ownership

Every file in a project has exactly one owner. You edit **only** these paths:

| Path | What goes there |
|------|-----------------|
| `frontend/src/app/` | All UI code: pages, components, features |
| `pb/pb_migrations/` | Schema: one migration per change, never edit an applied one |
| `pb/pb_hooks/ops.pb.js` (+ new `*.pb.js`) | Custom verbs beyond CRUD |
| `operations.json` | Declarations for every custom verb (non-`system` entries) |
| `LIVING_UI.md` | Your plan/context/index — keep it current |
| `reference/` | Requirements and materials handed to you |

Everything else — `frontend/src/kit/`, `main.tsx`, `config.gen.ts`, configs,
`_system.pb.js`, `_craftbot_bridge.js`, `manifest.json` — is **system-managed**. The validation gate
hashes those files and **fails the build if you touched them** (ownership step).
Need different behavior from a kit component? Wrap it in `app/`:

```tsx
// app/components/DueBadge.tsx — compose, never edit kit files
import { cn } from '../../kit/index.ts';
export function DueBadge({ overdue }: { overdue: boolean }) { /* … */ }
```

## 2. The build loop

1. Read `reference/requirements.md` and `LIVING_UI.md`.
2. Schema first: add a migration in `pb/pb_migrations/` (see §3).
3. Custom verbs (if any): hook route + `operations.json` entry (see §4).
4. UI: build in `frontend/src/app/` from kit parts (see §5).
5. Run the gate: `lui validate <project>` — fix, repeat. The gate is:
   types → build → migrations-on-fresh-db → ops structure/routing → ownership.
6. Frontend runtime errors land in `logs/frontend_console.log` (console.error/
   warn + uncaught errors are relayed automatically). Read it when the UI
   "looks fine but doesn't work".

## 3. Schema (PocketBase migrations)

- One JS migration per change; never modify an already-applied file.
- Wire format: PB gives every record `id`, `created`, `updated` (autodate
  fields declared in the starter migration — follow that pattern).
- **Rules are the security boundary** (spec B6). The scaffold set them from the
  auth mode: open (`''`) for `none`, `@request.auth.id != ""` for `multi-user`.
  New collections MUST follow the project's mode — check `manifest.json`
  `authMode`. In multi-user apps, owner-scoped data uses a `relation` field to
  `users` and rules like `owner = @request.auth.id`.

## 4. Operations (your public verb surface)

Anything an outside agent should be able to *do* to this app must be declared
in `operations.json` (schema: `spec/operations.schema.json`; discovery:
`GET /api/_ops`). The gate enforces: every non-system `http`/`job` op must
match a `routerAdd` route in `pb_hooks`, and it *warns* about routes you
forgot to declare.

- `http` — normal case: a hook route (see `ops.pb.js` for a working example,
  `items.clear-done`).
- `crud` — parameterized collection access, no hook needed.
- `job` — POST route returning `{jobId}`, status at `GET /api/_jobs/{jobId}`.
- Mark data-deleting ops `"destructive": true` — hosts confirm before running.

### 4.1 The CraftBot bridge (LLM + integrations, zero keys)

Hook routes can reach the host's LLM and connected integrations through the
system module `pb/pb_hooks/_craftbot_bridge.js` — no API keys in the app:

```js
const bridge = require(`${__hooks}/_craftbot_bridge.js`);
const summary = bridge.callLLM('Summarize:\n' + text, 'Reply in one sentence.');
const res = bridge.callIntegration('slack', 'POST', '/chat.postMessage', { ... });
```

`callLLM` returns `''` and `callIntegration` returns `{status: 503, ...}` when
the app runs outside CraftBot — degrade gracefully (skip the feature, never
crash the route). Only integrations the user has connected in CraftBot work;
treat non-2xx `status` as "not available".

## 5. Frontend

- Import everything from `../kit/index.ts` (the public API). Internals move
  without notice.
- Data: `useCollection('items', { sort: '-created' })` — realtime by default;
  never poll, never reload. Writes: `getPbClient().call((pb) => …)` — errors
  toast automatically; add `{ silent: true }` only when you handle them.
- Auth: in `multi-user` projects the shell already wraps your app in
  `LoginGate`; use `useAuth()` for the current user and logout.
- Styling: Tailwind utilities + kit tokens (`var(--lui-*)`). Never hardcode
  colors — theming is host-owned and must keep working when the host switches
  style packs or dark mode.
- Required UX (from GLOBAL rules): empty states with a next action, loading
  states, confirmation dialogs for destructive actions, toasts on CRUD,
  responsive layout.

## 6. Commands you'll use

```
lui validate <project>   # the gate — run after every meaningful change
lui dev <project>        # PocketBase + Vite HMR (development)
lui kit-sync <project>   # re-vendor the kit (only when instructed)
lui pb path              # the pinned PocketBase binary
```

You never start production servers yourself — hosts use `manifest.json`'s
pipeline (`install` / `build` / `start` / `health`).

## 7. Operating an existing app (no code edits!)

Use the CLI — it resolves the port, authenticates, and validates params:

```
lui ops  <project>                       # what can this app do?
lui run  <project> <op> --param value    # execute a declared op
lui data <project> <collection> list --filter '...' --limit 20
lui data <project> <collection> create --json '{...}'
```

1. `lui ops` (or `GET /api/_ops`) → discover the verb surface.
2. Declared op exists → `lui run` it (DESTRUCTIVE ops: confirm first).
3. No op → `lui data` for plain CRUD; read freely, write only what the app's
   own UI offers.
4. Would require new code → that's a *modification*, not an operation. Say so.

The `.superuser` file (0600) holds the machine superuser for administrative
API access. Never print, copy, or ship it.
