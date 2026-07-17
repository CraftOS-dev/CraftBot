# {{PROJECT_NAME}}

> **Agent control surface**: operate this app ONLY via the `livingui` CLI —
> `livingui {{PROJECT_ID}} --help` shows its tables, operations, and commands.
> Data goes through `select/insert --file/update --where`; behavior through
> `run <op> --params-file params.json`. Never open `living_ui.db` directly.


{{PROJECT_DESCRIPTION}}

## Overview

<!-- Agent: Briefly explain what this app does and who it's for. The full
     requirements specification for this app lives in
     reference/requirements.md (and in your task instruction) — this file
     is DOCUMENTATION of what was built. -->

### Assumptions
<!-- What did you assume? List assumptions made for areas not explicitly discussed -->

## Data Model

### Entities (config/schema.json)

<!-- Agent: List the entities you declared in config/schema.json -->

| Model | Purpose | Key Fields |
|-------|---------|------------|
| Example | Description | field1, field2 |

## API Endpoints

### Custom Routes (pb_hooks/main.pb.js)

<!-- Agent: List the API endpoints you added -->

| Method | Path | Description |
|--------|------|-------------|
| GET | /example | Description |
| POST | /example | Description |

## Frontend Components

### Components (frontend/components/)

<!-- Agent: List the React components you created -->

| Component | Purpose |
|-----------|---------|
| MainView.tsx | Main UI layout |

## Key Files

| File | Purpose |
|------|---------|
| config/schema.json | Declared PocketBase collections -> CRUD API + realtime |
| pb_hooks/main.pb.js | Custom API endpoints (routerAdd) |
| frontend/types.gen.ts | Generated TypeScript interfaces |
| frontend/api.gen.ts | Generated typed collection helpers |
| frontend/components/MainView.tsx | Region shell (auto-mounts regions/*.tsx) |

## State Flow

```
User Action → Frontend Component → PocketBase SDK (lib/pb.ts) → PocketBase → SQLite DB
                                        ↓
                          Realtime subscription updates UI
```

## Testing

<!-- Agent: How to verify the app works -->

1. Create a new item
2. Refresh the page
3. Verify item persists
