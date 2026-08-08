# Using ANY CraftBot integration (Slack, Notion, GitHub, …) — one pattern

Every connected service is used the SAME way: `callAction` runs CraftBot's
own tested implementation with semantic params. You never call a provider's
API, never touch credentials, never install SDKs. The capability map in your
context lists the connected integrations and their key action names.

```js
const bridge = require(`${__hooks}/_craftbot_bridge.js`);
const res = bridge.callAction(
  '<action_name>',                       // e.g. send_slack_message, create_notion_page
  { /* semantic params */ },
  { confirmIrreversible: true }          // required for sends/posts/deletes
);
if (res.status < 200 || res.status >= 300) {
  console.error('<action_name> failed:', res.error);   // log from RESULT, never intent
}
```

DON'T KNOW THE PARAMS? Discover them for free with a dry-run — validation
errors name the action's real schema fields, and nothing executes:
```js
bridge.callAction('send_slack_message', {}, { confirmIrreversible: true, dryRun: true });
// → res.error lists the expected params (e.g. channel, message, thread_ts)
```
A passing dry-run with your real params = the live call will reach the
provider. Dry-run every path you cannot execute at build time (scheduled
posts, sends).

## Worked example — email (PROVEN live; adapt the same shape for others)
```js
const res = bridge.callAction(
  'send_gmail',
  { subject: 'Daily digest', body: text },   // omit 'to' → the user's own inbox
  { confirmIrreversible: true }
);
```
Never hardcode recipients; never example.com addresses (bridge rejects them);
never build SMTP or OAuth — if you find yourself doing either, there is an
action for what you want.
