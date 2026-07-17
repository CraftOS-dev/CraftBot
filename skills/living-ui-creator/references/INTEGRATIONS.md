# External Integrations (AI, Google, Slack, Discord, ...)

Integrations happen in **`pb_hooks/main.pb.js`** — custom routes that call
the CraftBot host through its integration bridge, or `$http` for genuinely
public external APIs. The frontend never calls external services directly;
it awaits your `/api/custom/*` route with a loading state.

**Secrets and API keys are NOT available to apps.** There is no `.env`, no
secrets service, no credential storage. Anything that needs the user's
accounts or host credentials goes through the bridge — CraftBot injects
auth server-side, and tokens never touch app code or the database.

## The bridge

The platform starts every backend with two env vars:

- `CRAFTBOT_BRIDGE_URL` — the host bridge (per-project)
- `CRAFTBOT_BRIDGE_TOKEN` — Bearer token the bridge requires

Bridge endpoints (all POST unless noted, JSON in/out):

| Endpoint | Purpose |
|----------|---------|
| `/api/bridge/llm` | `{prompt, system_message?}` → CraftBot's LLM |
| `/api/bridge/vlm` | `{image_url, prompt?}` → `{description}` (vision) |
| `/api/integrations/proxy` | authenticated call to a connected service |
| `GET /api/integrations/available` | `{integrations: [{id, connected}]}` |

## In-app AI — callLLM (no API keys)

The `pb_hooks/main.pb.js` template ships a `callLLM(prompt, systemMessage?)`
helper that bridges to the CraftBot host. Keep it and call it from your
routes:

```js
routerAdd("POST", "/api/custom/summarize", (e) => {
  const cards = $app.findRecordsByFilter("cards", "done = false", "-created", 50, 0)
  const text = cards.map((c) => c.get("title")).join("\n")
  const summary = callLLM("Summarize these tasks in 3 bullets:\n" + text,
                          "You are a concise assistant.")
  if (!summary) return e.json(200, { summary: "", unavailable: true })
  return e.json(200, { summary: summary })
})
```

`callLLM` returns `""` on ANY failure (bridge down, timeout) — degrade
gracefully, never crash the request; the UI shows "AI unavailable". Calls
take seconds: run them in custom routes the frontend awaits with a loading
state, never in loops over many rows without telling the user.

## Connected services — the integration proxy

For the user's connected accounts (Gmail, Slack, Discord, Notion, GitHub,
...), POST to the bridge proxy; CraftBot injects the credentials:

```js
routerAdd("POST", "/api/custom/notify-slack", (e) => {
  const body = e.requestInfo().body
  const res = $http.send({
    url: $os.getenv("CRAFTBOT_BRIDGE_URL") + "/api/integrations/proxy",
    method: "POST",
    headers: {
      "content-type": "application/json",
      "Authorization": "Bearer " + $os.getenv("CRAFTBOT_BRIDGE_TOKEN"),
    },
    body: JSON.stringify({
      integration: "slack",
      method: "POST",
      url: "https://slack.com/api/chat.postMessage",
      body: { channel: "C0123456789", text: body.text },   // channel ID, not name
    }),
    timeout: 30,
  })
  const out = (res.json) || {}
  return e.json(200, { sent: out.status === 200, status: out.status })
})
```

The proxy replies `{status, data}` — `status` is the EXTERNAL API's code.
HTTP 424 from the bridge itself means the service is not connected: show
"Connect <service> in CraftBot settings", don't error out. Known
integration ids: `google_workspace` (Gmail, Calendar, Drive, YouTube),
`slack`, `discord`, `notion`, `telegram`, `github`, `jira`, `linkedin`,
`twitter`, `outlook`, `whatsapp` — confirm live with
`GET /api/integrations/available`.

## Plain external HTTP — $http

For genuinely public APIs (no auth, no user account), call them directly
from the hook — the goja VM's `$http.send({url, method, body?, headers?,
timeout})` returns `{statusCode, json, body}`:

```js
const res = $http.send({ url: "https://api.open-meteo.com/v1/forecast?...", timeout: 15 })
if (res.statusCode === 200) { /* res.json */ }
```

If the API needs a key, it is NOT a `$http` case — there are no keys.
Route it through the bridge or leave it out.

## Rules

- NEVER implement OAuth, credential storage, or key management — the
  bridge handles all auth.
- NEVER ask users for API keys; CraftBot already has their accounts.
- Bridge env vars missing (standalone run) → return an "unavailable"
  response, never a 500.
- Hook changes need `livingui <id> restart`; prove each route with a live
  curl (see VERIFY.md).
