# The Declared Backend — Full Reference

Deep-dive companion to SKILL.md's "The Backend Is Declared" section.
Everything here is verbatim-binding: the API surface, field spec,
platform capabilities (files, schedules, secrets, AI, external DB),
and the project layout.

Declare every entity in `config/schema.json`; at startup the engine
materializes the SQLAlchemy models AND a complete REST API per entity:

```
GET    /api/<plural>         list — equality filters on any field via query
                             params, plus orderBy=<field>&order=asc|desc,
                             limit, offset
POST   /api/<plural>         create (validates required fields, 422 names them)
POST   /api/<plural>/bulk    create many in ONE transaction (JSON array)
GET    /api/<plural>/{id}    fetch one (404 when missing)
PUT    /api/<plural>/{id}    partial update
DELETE /api/<plural>/{id}    delete — required refs cascade, optional refs null
GET    /api/_meta/schema     the schema + generated route map
```

Every entity automatically gets integer autoincrement `id` plus
`createdAt`/`updatedAt` — do NOT declare those. Wire format is camelCase
(matching your frontend types); the DB stores snake_case; the engine
converts. Field types: `string`, `text`, `integer`, `float`, `boolean`,
`datetime` (ISO strings), `json`, `ref` (add `"entity": "Name"`), and
`enum` (add `"values": ["todo", "doing", "done"]` — validated on write,
typed as a union in types.gen.ts). Add `"unique": true` to any scalar
field for a uniqueness constraint (duplicates get a 409 naming the field).

**Dependencies are the PLATFORM's job — never run `npm install` or
`pip install` yourself.** Every template dependency is installed by the
platform (it starts installing the moment the project is created, in
parallel with your first steps). If an early type-error note says
"Cannot find module 'react'/'lucide-react'/..." for a TEMPLATE dependency,
that install is still running — keep building; the note clears itself.
Running a second npm concurrently CORRUPTS node_modules and kills the
live preview. Need a package the template doesn't have? Add it to
package.json dependencies and say so in your notes — validation's install
step fetches it.

Renaming or removing a schema.json field is SAFE at any point: the
platform reconciles the database on the next backend start/validate
(new columns added, stale columns removed, shared data preserved). Never
hand-edit or delete living_ui.db to "fix" schema drift.

**File storage is built in — never hand-roll uploads.** The system
routes `POST/GET/DELETE /api/files` (+ `GET /api/files/{id}` serving)
store any file with metadata in the database; the frontend half is
`<FileUpload>`/`<ImageInput>` and `files.list()/fileUrl()` from
services/data. Store the returned `url` string in a schema string field.
Bytes default to CraftBot's workspace (so the platform/agent can read
them directly); override with `FILES_DIR=` in backend/.env; per-upload
cap via `MAX_UPLOAD_MB=`.

**Ops can run on a schedule.** Add a `"schedule"` key to any op in
config/operations.json — `"every 15m"`, `"every 2h"`, `"hourly"`, or
`"daily 09:00"` — and the platform fires it while the app is running (no
params: the op's defaults must suffice). Results append to
logs/schedule.log; last-run state in logs/schedule_state.json. Perfect
with the integration bridge: a `daily 09:00` op whose route emails the
user a digest. See references/OPERATIONS.md.

**Secrets live in backend/.env, nowhere else.** User-provided API keys
(Stripe, weather, ...) go in backend/.env and are read with
`from services.secrets import get_secret`. Never hardcode, never print,
never put them in LIVING_UI.md. CraftBot-connected services need NO keys
— use the integration bridge (references/INTEGRATIONS.md). Payments:
store `STRIPE_SECRET_KEY` in .env, call Stripe's REST API from a custom
route with httpx, return the checkout URL to the frontend.

**In-app AI is one call.** `await integration.llm(prompt)` /
`await integration.describe_image(url)` from
services/integration_client.py use CraftBot's own models — no API keys,
works whenever the app runs under CraftBot. Summarize/classify/extract
features cost a few lines in a custom route. See
references/INTEGRATIONS.md.

**External database (Supabase / any Postgres).** The app defaults to a
local SQLite file; to run it on Supabase instead, write ONE file —
`backend/.env`:

```
DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
```

Then validate. Everything follows automatically: the backend starts
against Supabase, the engine creates + reconciles the declared tables
there, and the livingui CLI's data commands work unchanged (`psycopg2`
is already in requirements). Rules:
- Ask the USER for the connection string (Supabase → Project Settings →
  Database → Connection string, URI format). Never invent one.
- NEVER hardcode the URL in code, never echo it into chat, notes, or
  LIVING_UI.md — it contains the database password. backend/.env is its
  only home.
- Use a dedicated Supabase project (or schema) per Living UI — two apps
  sharing one database collide on table names.
- Remote data is REAL: the `reset` op and destructive SQL now hit
  Supabase (no local file backups). Confirm with the user first.
- To switch back to local SQLite, delete backend/.env and restart.

The generated list endpoint also supports `?q=` (case-insensitive search
across string/text/enum fields) and range filters `<field>_gte/_lte/_gt/_lt`
on integer/float/datetime/ref fields, and every entity has
`GET /api/<plural>/_stats?groupBy=<field>&agg=count|sum|avg&field=<numField>`
for dashboard counts — no custom routes needed for any of this.
Example:

```json
{
  "entities": {
    "BoardColumn": {
      "description": "A lane on the board",
      "fields": {
        "title": {"type": "string", "required": true},
        "position": {"type": "integer", "default": 0}
      }
    },
    "Card": {
      "fields": {
        "title": {"type": "string", "required": true},
        "dueDate": {"type": "datetime"},
        "labels": {"type": "json", "default": []},
        "columnId": {"type": "ref", "entity": "BoardColumn", "required": true}
      }
    }
  }
}
```

`from models import Card` works immediately in custom routes and tests.
The generated CRUD is pre-tested (the pipeline auto-generates CRUD tests
from the schema) — you write tests only for YOUR custom endpoints.

**routes.py is for BEHAVIOR only**: multi-entity transactions, computed
aggregations, external fetches, domain verbs. One-line docstring on every
route; declare each as an op in `config/operations.json` (executor recipes
are embedded in that file).

### External public APIs (weather, news, prices, location)

ALL external data is fetched by the backend — never by frontend `fetch()`
(CORS) and never via browser permissions (`navigator.geolocation` auto-fails
in the embedded tab). The pattern: keyless public API + in-memory cache +
graceful offline degrade.

```python
import time
import httpx

_cache: dict = {}
CACHE_TTL_SECONDS = 600  # one named refresh window — tune here, nowhere else

@router.get("/weather")
async def get_weather():
    """Current weather for the user's location (IP-based, cached)."""
    cached = _cache.get("weather")
    if cached and time.time() - cached["at"] < CACHE_TTL_SECONDS:
        return cached["data"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            loc = (await client.get("https://ipapi.co/json/")).json()
            wx = (await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                        "current_weather": True},
            )).json()
        data = {"city": loc.get("city"), **wx.get("current_weather", {})}
        _cache["weather"] = {"at": time.time(), "data": data}
        return data
    except Exception:
        # Offline/rate-limited: last known value, never a 500
        return cached["data"] if cached else {"unavailable": True}
```

Same shape for news/quotes/prices: pick a keyless API, fetch in the
backend, cache with a timestamp, return the stale value when the network
fails. A user-entered location setting (persisted in the schema) always
beats detection. Data from CONNECTED services (Gmail, GitHub, Slack...)
goes through the integration bridge instead — see INTEGRATIONS.md.

See [MVC-A.md](references/MVC-A.md) for detailed architecture guidance.

## Directory Structure

```
project_root/
├── backend/                    # Python FastAPI backend
│   ├── main.py                 # FastAPI app entry + diagnostic 500s (SYSTEM)
│   ├── engine.py               # schema.json -> models + CRUD (SYSTEM)
│   ├── system_models.py        # Base + observation + StoredFile (SYSTEM)
│   ├── system_routes.py        # /state /action /ui-* routes (SYSTEM)
│   ├── files_routes.py         # /api/files upload/serve routes (SYSTEM)
│   ├── models.py               # re-exports (SYSTEM — never edit)
│   ├── routes.py               # CUSTOM endpoints only - EDIT THIS
│   ├── database.py             # DB connection, reads .env (SYSTEM)
│   ├── services/
│   │   ├── integration_client.py  # bridge: integrations + llm/vlm (SYSTEM)
│   │   └── secrets.py          # get_secret over backend/.env (SYSTEM)
│   ├── tests/                  # YOUR tests for custom endpoints
│   ├── .env                    # secrets + DATABASE_URL (create if needed)
│   └── living_ui.db            # SQLite database (auto-created)
│
├── frontend/                   # React TypeScript frontend
│   ├── main.tsx                # Entry point (rarely edit)
│   ├── App.tsx                 # Main app component
│   ├── AppController.ts        # App-specific orchestration (OPTIONAL)
│   ├── types.gen.ts            # GENERATED entity types (never edit)
│   ├── schema.gen.ts           # GENERATED entity metadata (never edit)
│   ├── types.ts                # App-specific non-entity types only
│   ├── components/             # React components - EDIT/ADD HERE
│   │   ├── ui/                 # Preset components + layout kit (SYSTEM)
│   │   └── MainView.tsx        # Main UI component
│   ├── services/               # API & UI capture (rarely edit)
│   │   ├── data.ts             # CRUD client + useEntities + files (SYSTEM)
│   │   ├── ApiService.ts       # Client for CUSTOM endpoints
│   │   └── UICapture.ts        # UI snapshot/screenshot for agent
│   └── styles/                 # global.css tokens + themes.css packs (SYSTEM)
│
├── config/schema.json          # THE data layer - DECLARE entities here
├── config/operations.json      # The app's verbs (+ schedules) for the CLI
├── config/manifest.json        # Project metadata (port info here)
├── index.html
├── package.json
├── vite.config.ts
└── LIVING_UI.md                # Project documentation - UPDATE THIS
```

## Files Summary

| File | Purpose | When to Edit |
|------|---------|--------------|
| `config/schema.json` | THE data layer — entities | Declare/extend entities |
| `backend/routes.py` | CUSTOM behavior endpoints | Behavior beyond CRUD only |
| `backend/tests/` | Tests for YOUR endpoints | With each custom route |
| `backend/.env` | Secrets, DATABASE_URL, FILES_DIR | When the app needs them |
| `frontend/types.gen.ts` | GENERATED entity types | Import, never edit |
| `frontend/components/` | UI components | Build the interface |
| `frontend/services/data.ts` | CRUD client + useEntities + files | Use, never edit |
| `config/operations.json` | Declared ops (+ schedules) | Via ops-sync, then curate |
| `LIVING_UI.md` | Documentation | Document your app |
