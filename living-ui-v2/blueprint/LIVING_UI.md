# {{PROJECT_NAME}}

> Per-project plan / context / index. The building agent keeps this current
> (spec A3). Only agent-owned areas are listed under "Editable".

## What this app does

{{PROJECT_DESCRIPTION}}

## Requirements

See `reference/requirements.md` (binding). Feature checklist:

- [ ] (features land here as they are planned/built)

## Entities

| Collection | Purpose | Notes |
|------------|---------|-------|
| items      | Example starter collection | Replace or extend via pb_migrations |

## Operations

Declared in `operations.json`; discoverable at `GET /api/_ops`.

## Ownership map

- Editable: `frontend/src/app/`, `pb/pb_migrations/`, `pb/pb_hooks/ops.pb.js`,
  `operations.json` (non-system entries), this file.
- System-managed (never edit): `frontend/src/kit/`, `frontend/src/main.tsx`,
  `pb/pb_hooks/_system.pb.js`, `manifest.json`, build configs.
