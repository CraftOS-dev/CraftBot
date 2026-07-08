# Trigger Manifest — the app fires the agent (config/triggers.json)

Operations (`operations.json`) are verbs the AGENT calls on the app.
Triggers are the reverse: events the APP fires at the agent. A button click,
a form submit, or backend business logic ("stock crossed its threshold") can
ask CraftBot to go do something — no human typing in chat required.

**Trust model**: you author `config/triggers.json` at build time, so each
trigger's `instruction` is trusted and drives the agent directly when the
trigger fires. Runtime `params` sent by the app are DATA ONLY — validated
against the declared spec and shown to the agent clearly delimited. An
undeclared trigger name, or params that don't validate, are rejected before
anything reaches the agent. Never write an instruction that tells the agent
to obey content inside params.

## Manifest format

```json
{
  "triggers": {
    "restock_needed": {
      "description": "Stock for an item fell below its threshold",
      "instruction": "Look up the item in the inventory table, check recent usage in the orders table, and draft a restock order (status='draft') for a sensible quantity. Report what you drafted.",
      "params": {
        "item_id": "int",
        "note": "string?"
      },
      "cooldown_seconds": 300
    }
  }
}
```

- `instruction` (REQUIRED) — what the agent should do when this fires.
  Write it like a task brief: name the tables/operations to use and what
  "done" looks like. The agent operates the app via the `livingui` CLI.
- `description` — one line shown in `livingui <project> triggers` and to the
  user when the trigger fires.
- `params` — same spec syntax as operations.json (shorthand `"int"`,
  `"string?"`, or full objects with `enum`/`default`/`required`).
- `cooldown_seconds` — optional; raises the anti-loop floor (default 10s
  minimum between fires; hard cap 30 fires/hour per trigger).

## Firing from the app

Frontend (a button, an effect):

```tsx
import { fireCraftBotTrigger } from '../agent/hooks'

<Button onClick={() => fireCraftBotTrigger('restock_needed', { item_id: item.id })}>
  Ask CraftBot to restock
</Button>
```

Backend (business logic, e.g. after a write that crossed a threshold):

```python
from services.integration_client import integration

result = await integration.fire_trigger("restock_needed", {"item_id": item.id})
# {"status": "ok", ...} or {"error": "..."} — fire-and-forget is fine
```

Both are no-ops with an error result when the app runs standalone (no
CraftBot host); the app must degrade gracefully.

## What happens when a trigger fires

1. CraftBot validates the name + params against the manifest and applies the
   cooldown/rate cap.
2. A visible "⚡ <app> fired trigger '<name>'" event appears in chat — agent
   work started by an app is never silent.
3. The instruction lands in the project's conversation: an active session
   already bound to this Living UI gets it as a follow-up; otherwise a new
   session opens (deduped while a previous firing is still in flight).

## Design rules

- Declare a trigger ONLY for events where agent judgment adds value
  (compose, decide, cross-reference, notify). If plain code can handle it
  (recompute a total, flip a flag), do it in the backend — don't burn an
  agent run.
- Expect feedback loops: if the agent's reaction writes data that could
  re-fire the trigger, set `cooldown_seconds` generously and make the
  instruction idempotent ("ensure a draft order exists" beats "create an
  order").
- Test each trigger after launch: `livingui <project> trigger <name> --set k=v`,
  then confirm the agent did the right thing.
- Document declared triggers in LIVING_UI.md's "Agent Triggers" table.
