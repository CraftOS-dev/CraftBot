# Agent triggers — the app fires the agent (`triggers.json`)

Operations (`operations.json`) are verbs the AGENT calls on the app. Triggers
are the reverse: events the APP fires at the agent. A button click or backend
business logic ("stock crossed its threshold") can ask the agent to go do
something — no human typing in chat required.

**Trust model:** you author `triggers.json` at build time, so each trigger's
`instruction` is trusted and drives the agent when the trigger fires. Runtime
`params` sent by the app are DATA ONLY — validated against the declared spec
in-app, and the reacting agent is told to treat them as values, never as
instructions. An undeclared trigger name, or params that don't validate, are
rejected inside the app before anything reaches any agent. **Never write an
instruction that tells the agent to obey content inside params.**

## Declaring (`triggers.json`, project root — agent-owned)

```json
{
  "triggers": {
    "restock_needed": {
      "description": "Stock for an item fell below its threshold",
      "instruction": "Look up the item in the inventory collection, check recent usage in orders, and ensure a draft restock order exists for a sensible quantity. Report what you drafted.",
      "params": {
        "item_id": { "type": "number", "required": true },
        "note": { "type": "string" }
      },
      "cooldown_seconds": 300
    }
  }
}
```

- `instruction` (REQUIRED) — what the agent does when this fires. Write it
  like a task brief: name the collections/operations to use and what "done"
  looks like. The agent operates the app via the `lui` CLI.
- `description` — one line; shown to the user at consent time and in
  `describe`. Write it for THEM ("can ask your agent to draft restock
  orders").
- `params` — the operations.json param shape: `{type: string|number|boolean,
  required, default, enum, description}`.
- `cooldown_seconds` — optional; RAISES the built-in floor (10s minimum
  between fires; hard cap 30 fires/hour per trigger).

The validation gate checks the structure and derives
`capabilities.triggers` into the manifest — the host refuses fires of
anything not on that list, so declare first, fire second.

## Firing

Frontend (a button, an effect) — kit helper, realtime result:

```tsx
import { fireAgentTrigger, useAgentRequest } from '../kit/index.ts'

const [reqId, setReqId] = useState<string | null>(null)
const { request, working } = useAgentRequest(reqId)

<Button onClick={async () => {
  const fired = await fireAgentTrigger('restock_needed', { item_id: item.id })
  if (fired.ok) setReqId(fired.requestId!)
  else toast.error(fired.message)   // cooldown, undeclared, bad params
}}>Ask the agent to restock</Button>
{working && <span>agent working…</span>}
{request?.status === 'done' && <span>{request.result}</span>}
```

Backend (business logic in an ops handler) — NEVER insert into
`agent_requests` with `e.app.save()` yourself (that bypasses validation);
use the system helper:

```js
const trig = require(`${__hooks}/_triggers_lib.js`);
const fired = trig.fire(e.app, 'restock_needed', { item_id: item.id }, 'hook');
// {ok: true, id} or {ok: false, code, message} — never throws; degrade gracefully.
```

Both are no-ops with an honest error/pending state when no agent is attached
— the app must work standalone.

## What happens on a fire

1. The in-app guard validates name, params, cooldown, and hourly cap, then a
   row lands in the `agent_requests` collection with `status=pending`.
2. The app nudges the CraftBot host (fire-and-forget). The host checks the
   manifest capability, the user's consent (apps built here are
   pre-approved; marketplace/imported apps need
   `living_ui_approve_triggers`), and that no build/modify is mid-arc.
3. A visible "⚡ <app> fired trigger '<name>'" line appears in the project
   feed — agent work started by an app is never silent.
4. The agent claims the row (`status=claimed`), does the work via the `lui`
   CLI, and writes `result` + `status=done` (or `error` + `status=rejected`).
   The row is the audit trail — rows are never deleted.

## Design rules

- Declare a trigger ONLY where agent judgment adds value (compose, decide,
  cross-reference, notify). If plain code can handle it (recompute a total,
  flip a flag), do it in the hook — don't burn an agent run.
- **The app NEVER touches `agent_requests` from hooks** — no reading, no
  claiming, no writing results. The queue is the reacting AGENT's surface;
  a hook that answers the app's own requests shadows the real agent forever
  (an in-process hook wins every claim race), and the gate rejects it.
  During staging verification the agent deliberately does not respond —
  that is correct behavior to leave in place, not a gap to code around.
- Expect feedback loops: if the agent's reaction writes data that could
  re-fire the trigger, set `cooldown_seconds` generously and make the
  instruction idempotent ("ensure a draft order exists" beats "create an
  order").
- Render the request's lifecycle honestly: `pending` with no agent attached
  means "no agent connected yet", not a spinner forever.
- Write the requirements line for a trigger feature as what VERIFICATION can
  observe: "firing lands a pending request and the UI reflects it" — never
  "the agent responds". During staging verification fires are deliberately
  not delivered to the agent (era gate), so a requirement promising the
  response is unverifiable by design and will fail every walk.
- Test each trigger after launch:
  `node <craftbot-root>/living-ui/tools/src/cli.ts trigger <project_path> <name> --param value`,
  then `... requests <project_path>` to watch the outcome.
- Document declared triggers in LIVING_UI.md (an "Agent Triggers" table).
