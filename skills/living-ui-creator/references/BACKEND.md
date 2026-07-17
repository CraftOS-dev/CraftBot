# Backend Reference — PocketBase

The backend is **PocketBase** (single binary, SQLite): the platform runs
it, imports your declared collections, and PB itself serves full CRUD —
you never write models, CRUD routes, or migrations.

## 1. Declare collections — `config/schema.json`

PocketBase's native import format. Field names are used EXACTLY as
declared (camelCase recommended — the same names appear on the wire and
in `types.gen.ts`). String `id` and `created`/`updated` are automatic.

```json
{
  "collections": [
    {
      "name": "cards", "type": "base",
      "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": "",
      "fields": [
        {"name": "title", "type": "text", "required": true},
        {"name": "dueDate", "type": "date"},
        {"name": "labels", "type": "json"},
        {"name": "columnId", "type": "relation", "collectionName": "boardColumns",
         "cascadeDelete": true, "maxSelect": 1}
      ]
    }
  ]
}
```

Field types: `text`, `number`, `bool`, `date`, `select` (+`values`),
`relation` (+`collectionName`, `maxSelect: 1`, `cascadeDelete`), `json`,
`file`, `email`, `url`. Rules `""` = public (right for these local
single-user apps). Writing this file re-imports collections into the
RUNNING PocketBase and regenerates `types.gen.ts`/`api.gen.ts`.

**`required: true` means NON-EMPTY, not "must be present"** — PocketBase
rejects `false` on a required `bool`, `0` on a required `number`, and
`""` on a required `date`/`text`, all with `"cannot be blank"`. NEVER
mark a field required if it legitimately starts false/zero/empty
(`completed`, `completedAt`, counters, optional dates). If a create is
failing with "cannot be blank" on a value you ARE sending, the fix is in
the schema (drop `required`), never in the value.

What PB then serves per collection (never write these):
`GET/POST /api/collections/<name>/records` (`?filter=`, `?sort=-field`,
`?page/perPage`, `?expand=rel`), `GET/PATCH/DELETE .../records/<id>`,
realtime subscriptions, file storage.

## 2. Custom logic — `pb_hooks/main.pb.js`

ONLY for multi-record transactions, computed aggregations, external
calls, and domain verbs — never CRUD.

```js
routerAdd("POST", "/api/custom/archive-done", (e) => {
  const body = e.requestInfo().body
  const cards = $app.findRecordsByFilter(
    "cards", `columnId = '${body.columnId}' && done = true`, "-created", 500, 0)
  cards.forEach((c) => { c.set("archived", true); $app.save(c) })
  return e.json(200, { archived: cards.length })
})
```

Rules:
- **Embedded JS VM (goja)**: plain JavaScript, NO npm imports, NO node
  APIs. Globals: `$app` (findRecordsByFilter/findRecordById/save/delete),
  `$os`, `$http`, `$security` — full ambient API in `pb_data/types.d.ts`.
- Paths under `/api/custom/...`; reply with `return e.json(status, obj)`.
- Hook file changes need a backend restart (`livingui <id> restart`).
- AI calls: the `callLLM(prompt, systemMessage?)` helper in main.pb.js
  (bridges to the CraftBot host; returns `""` on failure — degrade
  gracefully).
- PROVE every route with a live curl against the running backend
  (`livingui <id> status` shows the api URL) — create the records it
  needs via CRUD first.

## 3. Frontend data access

```ts
import { api, useCards, useEntities } from '../api.gen'   // typed, generated
const cards = useCards({ filter: "done = false", sort: "-created" })
const cards2 = useEntities('cards', { sort: "-created" })  // also fully typed
await api.cards.create({ title: "Hi", columnId: col.id })
```

- ALWAYS import `useEntities`/`api`/`use<Name>()` from `'../api.gen'` (not
  from services/data) — the api.gen versions are TYPED to your schema, so
  `useEntities('cards')` returns `Card` records with no type argument. The
  raw `services/data` hook is untyped (fields become `any`).
- `useEntities(name, {filter, sort, perPage, expand})` returns
  `{items, loading, error, refresh, create, update, remove}` — realtime:
  every mounted list auto-refreshes on ANY mutation.
- Ids are STRINGS. Filters use PB syntax: `field = 'x' && n > 3`.
- `ApiService.request` is ONLY for `/api/custom/*` pb_hooks endpoints —
  never entity CRUD. Pass the path without the `/api` prefix:
  `ApiService.request('POST', '/custom/archive-done', {...})`.
- Never edit system-managed files: `pb_hooks/_craftbot.pb.js`,
  `lib/pb.ts`, `services/data.ts`, `*.gen.ts`.

## 4. Operations — `config/operations.json`

Unchanged: declare typed verbs for your custom endpoints (http executors
now point at `/api/custom/...`); scheduled ops run with NO params.

## 5. Multi-user auth — the auth module

When the app needs accounts (login, roles, per-user or shared data), do
NOT hand-write auth — PocketBase has it built in, and the platform ships a
ready module at `app/data/living_ui_modules/auth/`:

- `schema.auth.json` — collections to merge into `config/schema.json`:
  `users` (auth collection + `role` select, self-update rules),
  `memberships`, `invites` — all with explicit auth-gated API rules.
- `pb_hooks/auth.pb.js` — first-registered-user-becomes-admin + the
  `POST /api/custom/invites/accept` endpoint. Copy into `pb_hooks/`.
- `frontend/*.tsx` — AuthProvider (pb.authStore), LoginPage, RegisterPage,
  UserMenu, ProfilePage, MemberList, InviteModal — built on `@/lib/pb` and
  the vendored `@/components/ui/*`. Copy into `frontend/components/auth/`.

Per-user data = an `owner` relation field + ownership rules on the
collection (PB enforces on every CRUD/realtime call — no query filtering
code). Full integration steps and rule patterns: the module's README.
