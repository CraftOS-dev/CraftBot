# {{PROJECT_NAME}}

> **Agent control surface**: operate this app ONLY via the `livingui` CLI —
> `livingui {{PROJECT_ID}} --help` shows its tables, operations, and commands.
> Data goes through `select/insert --file/update --where`; behavior through
> `run <op> --params-file params.json`. Never open `living_ui.db` directly.


{{PROJECT_DESCRIPTION}}

## Overview

<!-- Agent: Briefly explain what this app does and who it's for -->

## Requirements

<!-- Agent: Document gathered requirements from Phase 0 here -->

### Entities & Data Model
<!-- What are the main entities? What fields does each have? How do they relate? -->

### Layout & Design
<!-- Layout style, color scheme, theme preference, visual style -->

### Features
<!-- CRUD operations, search/filter, media support, drag-and-drop, detail views, etc. -->

### Assumptions
<!-- What did you assume? List assumptions made for areas not explicitly discussed -->

## Data Model

### Backend Models (backend/models.py)

<!-- Agent: List the SQLAlchemy models you created -->

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
| backend/models.py | Database models |
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

## Agent Triggers (config/triggers.json)

<!-- Agent: if this app fires triggers at CraftBot, list them here -->

Declared triggers let the app itself ask CraftBot to do something — a button
in the UI (`fireCraftBotTrigger(name, params)` from `frontend/agent/hooks.ts`)
or backend logic (`integration.fire_trigger(name, params)` from
`services/integration_client.py`). Only triggers declared in
`config/triggers.json` are accepted. Test with `livingui {{PROJECT_ID}} trigger <name>`.

| Trigger | Fired when | What CraftBot does |
|---------|------------|--------------------|
| (none declared) | | |

## Testing

<!-- Agent: How to verify the app works -->

1. Create a new item
2. Refresh the page
3. Verify item persists
