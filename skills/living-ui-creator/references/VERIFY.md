# Living UI Verification

The ladder of evidence, weakest to strongest:

1. **verify_build** — the code compiles. Nothing more.
2. **Self-testing in the browser** — you watched each feature work.
3. **curl against the running backend** — routes and data are real.
4. **walk_verify** — the independent gate that decides PASS.

**A green build is NOT evidence a feature exists.** The failure mode this
process exists to kill: an app that builds cleanly with zero features
implemented, reported as "fully implemented". Never argue from a passing
build that a feature is present — go exercise it.

## 1. Compile truth — verify_build

Call `verify_build` (pass the project path) after edits and before ending.
It runs the real build (`npm run build:debug` from the project root —
never per-file `tsc`) and groups failures by ROOT CAUSE: a cascade of 590
identical "Cannot find module" errors comes back as ONE cause. Fix the
root cause, re-run; if the cause count didn't drop, you misdiagnosed —
re-read the actual error, never repeat a fix that didn't work. Running
verify_build repeatedly without changing code is not progress.

## 2. Self-test every feature in the browser

The app URL hot-reloads on save. For EACH feature, in the order a first
user would hit it:

```
mcp_playwright-mcp_browser_navigate        → app URL
mcp_playwright-mcp_browser_snapshot        (NO filename — a11y tree + element refs inline)
mcp_playwright-mcp_browser_click / browser_type / browser_fill_form   → USE it, realistic data
mcp_playwright-mcp_browser_snapshot        → confirm the app RESPONDED
mcp_playwright-mcp_browser_console_messages → any runtime error = broken, even though it compiled
```

"The control exists" is not working — it must DO the thing: data
appeared, value updated, navigation happened.

**Persistence survives reload (critical, once per data-saving feature):**
create a record, `browser_navigate` to the app URL again (full reload),
snapshot. If the data is gone, the feature is broken — the most common
way an app looks finished and isn't. Usual causes: local-only `useState`
instead of `useEntities`/`api.gen`, or the collection missing from
`config/schema.json`.

If the browser tools are down, that costs you one way to LOOK — not the
ability to build. Fall back to curl + logs (below) and say which method
you used; never report a feature verified that you never saw run.

## 3. Prove the backend with curl

`livingui <id> status` prints the ui and api URLs.

```bash
livingui <id> status                          # running? ui/api URLs, table row counts
# PB CRUD — exists for every collection in config/schema.json:
curl "<api>/api/collections/cards/records?perPage=5"
curl -X POST "<api>/api/collections/cards/records" \
     -H 'Content-Type: application/json' -d '{"title":"probe"}'
# Custom endpoints — prove EVERY route you wrote, with real records:
curl -X POST "<api>/api/custom/archive-done" \
     -H 'Content-Type: application/json' -d '{"columnId":"<real-id>"}'
livingui <id> logs --tail 50                  # server output + captured browser console
```

A custom route counts as done only after a live curl returned the
expected JSON (create the records it needs via CRUD first). Remember hook
changes need `livingui <id> restart`. Read `logs` after exercising the
app and treat every ERROR as a defect to fix.

## 4. The independent gate — walk_verify

You do not sign off on your own work. `walk_verify` is a read-only agent
that drives the RUNNING app in a real browser against the requirements —
it never edits code, and the build is not finished until it passes. It:

- turns the requirements into a numbered feature list and DOES each one
  with realistic data;
- passes a feature ONLY on concrete evidence from an action it ran;
- checks the console after each flow and re-loads once to check
  persistence.

Its verdict is mechanical:

```
VERDICT: PASS | FAIL | BLOCKED
FEATURES:
- <feature> — PASS/FAIL — <the flow run and what was observed>
```

- **PASS** — every feature passed with observed evidence.
- **FAIL** — it SAW the app misbehave: a feature it could not exercise
  (missing/dead/placeholder control), a console error during normal use,
  data lost on reload. There is no "minor": one console error = FAIL, a
  feature that "mostly" works = FAIL.
- **BLOCKED** — the app could not be exercised AT ALL (URL unreachable,
  browser tooling down). Not the app's fault, not a FAIL — fix the
  environment and re-run, don't "fix" features that may be fine.

A FAIL report is a work order: for each failed feature, change code —
re-read the requirement, find the missing UI/state/wiring, implement it,
re-verify. "The build passes" is never a response to "there is no
onboarding UI".

## Final checklist before ending

- [ ] `verify_build` ok (zero root causes)
- [ ] Every requirement exercised by YOU this run, with evidence (browser
      or curl) of what you did and what you observed
- [ ] Persistence-survives-reload checked for data-saving features
- [ ] Console and `livingui <id> logs` clean during normal use
- [ ] Custom routes proved by live curl; ops declared in
      `config/operations.json` for every side-effectful verb
- [ ] No faked green: no `as any`, no placeholder/"coming soon"/dead
      buttons, no hardcoded fake data standing in for behavior
