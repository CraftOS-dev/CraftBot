# {{PROJECT_NAME}}

> **Agent control surface**: operate this app ONLY via the `livingui` CLI —
> `livingui {{PROJECT_ID}} --help` shows its tables, operations, and commands.
> Data goes through `select/insert --file/update --where`; behavior through
> `run <op> --params-file params.json`. Never open `living_ui.db` directly.


{{PROJECT_DESCRIPTION}}

## Overview

<!-- Agent: Briefly explain what this app does and who it's for -->

## Requirements

This is THE requirement ledger and progress tracker for this app. Phase 0
fills it with SUPER-DETAILED, ID'd checkbox items covering the app's whole
scope; every item gets ticked (`- [ ]` → `- [x]`) as it is fulfilled.
Validation refuses missing, thin, or unfinished ledgers.

<!-- REQ:BEGIN -->
### Features
<!-- Core capabilities — everything the app DOES. IDs F1, F2, ... -->
<!-- - [ ] F1: ... -->

### Data
<!-- Models, fields, schema, persistence rules. IDs D1, D2, ... -->
<!-- - [ ] D1: ... -->

### Design
<!-- Visual/UX: icons, imagery, layout, alignment, hierarchy, pages/tabs,
     color usage — concrete and comprehensive. IDs V1, V2, ... -->
<!-- - [ ] V1: ... -->

### CLI
<!-- Every operation CraftBot needs to operate this app via `livingui`
     (config/operations.json). IDs C1, C2, ... -->
<!-- - [ ] C1: ... -->

### Quality of Life
<!-- Scope-specific power-UX: shortcuts, drag & drop, multi-select, context
     menus, mobile layout, and much more — invent for THIS app. IDs Q1, ... -->
<!-- - [ ] Q1: ... -->
<!-- REQ:END -->

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

## Testing

<!-- Agent: How to verify the app works -->

1. Create a new item
2. Refresh the page
3. Verify item persists
