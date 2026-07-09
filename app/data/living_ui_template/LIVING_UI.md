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

### Custom Routes (backend/routes.py)

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
| config/schema.json | Declared entities -> generated models + CRUD API |
| backend/routes.py | API endpoints |
| frontend/types.ts | TypeScript interfaces |
| frontend/AppController.ts | State management |
| frontend/components/MainView.tsx | Main UI |

## State Flow

```
User Action → Frontend Component → AppController → Backend API → SQLite DB
                                        ↓
                                  Update UI State
```

## Testing

<!-- Agent: How to verify the app works -->

1. Create a new item
2. Refresh the page
3. Verify item persists
