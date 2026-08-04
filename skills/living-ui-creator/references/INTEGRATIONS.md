# CraftBot Integrations (Gmail, Slack, Notion, …)

**Scope: CraftBot's own connected services ONLY.** Third-party public APIs
(weather, stocks, geocoding, …) are NOT this — call those directly from
pb_hooks with `$http.send` (see the "External data" section of the creator
skill).

CraftBot holds the user's connected accounts AND tested implementations of
every integration operation. Living UIs reach them through the bridge —
never build OAuth flows, never build SMTP mailers, never ask the user for
API keys or credentials, never reimplement a provider's API.

## PREFERRED: `callAction` — run CraftBot's own implementation

CraftBot has 1000+ integration actions (`send_gmail`, `send_slack_message`,
`create_notion_page`, `list_gmail`, …). `callAction` executes them with
**semantic params** — CraftBot owns the provider-API details (endpoints,
encodings, MIME envelopes), so your hook never needs to know them:

```js
routerAdd('POST', '/api/ops/notify', (e) => {
  const bridge = require(`${__hooks}/_craftbot_bridge.js`);
  const res = bridge.callAction(
    'send_gmail',
    { to: 'user@example.com', subject: 'Price alert', body: 'BTC crossed $65k' },
    { confirmIrreversible: true }   // required for actions that act on the real account
  );
  if (res.status < 200 || res.status >= 300) {
    console.error('notify failed:', res.error);
    return e.json(502, { error: res.error || ('bridge returned ' + res.status) });
  }
  return e.json(200, { sent: true });
});
```

- The action name must be a **literal string** — the gate derives the
  app's `capabilities.actions` grant from it (same derive-from-code flow as
  `external_hosts`); relaunch with `living_ui_notify_ready` after adding one.
- Params follow the action's input schema — semantic fields
  (`to`/`subject`/`body`, `channel`/`message`), never provider wire formats.
- **To reach YOUR USER, omit the recipient** — `send_gmail` with no `to`
  goes to the account owner. Never store, hardcode, or guess the user's
  email/identity in app code: identity is CraftBot's, same as credentials.
- Actions marked irreversible (sends, posts, deletes on the user's real
  account) need `{ confirmIrreversible: true }` or the bridge refuses.
- Non-2xx `res.status`: `res.error` says exactly why (grant missing, not
  connected, provider error) — read it before theorizing.
- **DRY-RUN before you declare an unexercisable path done.** A scheduled
  email/post cannot be real-tested at build time — so validate it:
  `callAction('send_gmail', sameParams, { confirmIrreversible: true, dryRun: true })`
  runs EVERY check (grant, param names, placeholder values, confirmation)
  and executes nothing. A 200 dry-run means the real call will reach the
  provider; a 400 names the bug now instead of at 8 AM. Wire the dry-run
  through the same code path the cron uses (e.g. an op param), not a copy.
- **Log from the RESULT, never from intent.** `console.log('sent')` above an
  unchecked call is a lie generator — an app once logged "sent" daily while
  the bridge refused every send. Branch on `res.status`, and log `res.error`
  on failure.

## FALLBACK: `callIntegration` — the raw proxy

Only for provider endpoints no action covers. This is a raw pass-through to
the provider's REAL API with credentials injected — you must use their
actual paths and payload shapes, so **research the endpoint first** (or copy
a working call from another app in the workspace); never invent a plausible
shape. Observed failure: a made-up `POST /send` with `{to, subject, body}` —
Gmail has no such endpoint, the bridge faithfully returned Google's 404, and
the agent wrongly concluded the bridge was broken. If you find yourself
hand-encoding MIME or OAuth here, stop — there is almost certainly an action
for it; use `callAction`.

## Degrade gracefully

Outside CraftBot (standalone deploy) all bridge calls return
`{status: 503, error: 'CraftBot integration bridge is unavailable'}` and
`callLLM` returns `''`. Skip the feature and show "Connect via CraftBot" —
never crash the route. Treat any non-2xx as "not available right now".

## Grants (fail closed, DERIVED from your code)

`manifest.json` is system-managed — you never edit it. The gate scans your
hooks and writes the grants itself:
- `callAction('<name>'` literals → `capabilities.actions`
- `callIntegration('<id>'` literals → `capabilities.integrations`

A 403 after relaunching means the name wasn't a literal (make it one) or the
user hasn't connected that service in CraftBot — say which service the app
needs and why; never work around the bridge.

## Available integrations

github, gmail, google_calendar, google_docs, google_drive, google_youtube,
google_workspace, outlook, slack, discord, notion, hubspot, jira, linkedin,
stripe, line, lark, lark_calendar, lark_drive, telegram_bot, telegram_user,
twitter, whatsapp_business

Only ones the user actually connected will work — check `res.status` rather
than assuming.
