# Agent App pipeline issues (from live-run analysis)

Findings from real session logs, ordered by impact. Each item is a concrete,
verified defect in how CraftBot builds/modifies apps, not in any one app.

## From the Clock weather modify (2026-09-08, lui_72371f3d, 25 turns / ~11 min)

- [ ] **Cookbooks are not injected into `notify_ready` error responses.**
  The run burned 3 of its 5 failed gate cycles rediscovering PocketBase JSVM
  quirks (`fetch()` does not exist in Goja → `$http.send`; response body is
  bytes/nil, not string). `appfactory/cookbooks/third_party_fetch.md` and
  `pocketbase_traps.md` document exactly these, keyed by exactly these error
  keywords, but `_select_cookbooks` only feeds factory FIX-mission briefs
  (walk-verify defect path). The launch-error path returns raw errors.
  Fix: reuse `_select_cookbooks` on `notify_ready`'s `test_errors` text and
  append matching cookbook excerpts to the error message.

- [ ] **PocketBase JSVM traps are not in the modify skill's loaded text.**
  `agent-app-modify/SKILL.md` says "everything in the creator skill applies"
  but the creator's reference files (INTEGRATIONS.md etc. with `$http.send`
  patterns) are not loaded with it, so the first server-side fetch an agent
  writes in a modify is wrong by default.

- [ ] **Non-parallel action batches silently drop siblings.**
  Twice the agent batched `agent_app_notify_ready` with a `read_file` /
  `stream_edit`; the non-parallelizable action ran alone and the sibling was
  discarded, costing a full extra turn each time to re-issue it.
  Fix: auto-queue dropped siblings for the next turn instead of discarding.

- [ ] **Dev-copy creation cost 71s of the first gate cycle on Windows.**
  `DevProvisioner.create_copy` copies `frontend/node_modules` file-by-file.
  Fix: junction/hardlink node_modules into the dev copy (drop the link when
  package.json changes — sync_code already detects that case).

- [ ] **Baseline process overhead is ~4 turns minimum** (ack, clarifying
  question, set_requirement, use_skill, update_todos) before any code is
  read. By design (spec discipline), but worth knowing when judging run
  length: ~9 turns is the realistic floor for a supervised modify.

## From the Receipt Record build (2026-09-08, lui_1dbb9b85, 37+ min, undelivered)

User asked: "upload or take picture of a receipt, then it automatically scan,
and store in a database". Delivered state: parked on a question, manual-entry
app, no scanning.

- [ ] **Description/interview contradictions are silently resolved.** The
  description says "automatically scan"; the interview recorded "Manual entry
  only (store image but no extraction)" for q3. The requirements writer
  resolved the conflict toward the click without flagging it, wrote
  "Scanning/OCR/extraction is explicitly NOT performed" into the spec, and
  the spec is BINDING ("the builder cannot question it"). The core feature
  of the app was dropped before the build started and nothing surfaced it.
  Fix: the requirements writer must detect description-vs-answer conflicts
  and ask ONE confirming question instead of silently picking a side.

- [ ] **Spec inflation.** "Where input is silent, decide" + "Quality of
  Life" + "cover the full scope" turned a simple receipt tracker into a
  15-feature binding contract (CSV column mapping + upsert-by-external-id,
  camera capture w/ retake, bulk draft review inbox, keyboard shortcuts,
  export center). The walker then enforces every line: 7 defects per round,
  two rounds, three fix missions, still undelivered. Scope needs a budget
  proportional to the ask.

- [ ] **Windows file lock kills fix iterations (~14 min lost).**
  `open_dev`'s REUSE path (sync_code + reset_db) never stops the still-
  running dev PocketBase from the previous successful boot, so
  `reset_db`'s rmtree hits WinError 32 on `pb_data/auxiliary.db` on every
  fix iteration that follows a successful notify_ready. The agent flailed:
  restarted the LIVE app (wrong process), 10+ PowerShell quoting failures,
  downloaded Sysinternals handle64.exe, killed PocketBase processes by
  name. Fix: DevProvisioner must kill the recorded dev process before
  reset_db on reuse (it holds the handle in `_processes` / record pid).

- [ ] **First build misclassified as a MODIFY arc.** `start_development_run`
  keys arc kind on `live_db_exists`, but the scaffold's superuser bootstrap
  creates `pb_data` before dispatch, so a brand-new build opened
  `arc: "modify"`: fix missions carried the agent-app-modify skill instead
  of agent-app-creator, resume briefs said "CONTINUE MODIFY", and delivery
  would announce "Your change is live" for a first build.
  Fix: kind = modify only when `delivered_at` is set (promoted or arrived
  finished), not on the existence of a bootstrap database.

- [ ] **Internal decisions escalated to the user.** Mid-fix, the agent sent
  "Downloaded Handle.zip... tell me what to do next"; at the end it parked
  asking the user which of three duplicate migrations (which it created
  itself across fix rounds) to delete. Both are agent-owned decisions. The
  mission brief forbids status messages but nothing discourages
  implementation questions.

- [ ] **LLM decision parse failures cost ~2.5 min** (two consecutive
  "Unable to parse action decision" at 13:04:43/13:05:56, each retry ~70s).

- [ ] **walk_verify burned a full cycle on an unparseable report** (first
  walker died in 22s, verdict unparseable, retried from scratch).

- [ ] **Question-pause records empty question text** in arc.json
  (`paused.question: ""`) — on_run_end doesn't capture the asked question.
  Cosmetic, but a dormancy dashboard would want it.

- [ ] **Multipart upload in the PB JSVM re-derived from type stubs (~10
  min).** Same knowledge-delivery gap as the Clock cookbook item above; no
  cookbook covers `formFile`/`fileFromMultipart` at all.

## From the Brainstorm Graph failed evolve (2026-09-08, lui_70f26c25, ~92 min, STUCK at 12/12 missions)

A modify of the AI-research-suggestions feature that died on the mission
budget at 16:48 after ~92 minutes and 5+ fix missions. The defect churn was
real, but most of the budget went to infrastructure.

- [ ] **The Windows dev-lock treadmill taxes EVERY fix iteration** (upgrade
  of the Receipt Record finding). Six separate lock incidents in this one
  arc: each successful `notify_ready` leaves the dev PocketBase running, so
  the next iteration's reset hits WinError 32, the agent burns 2-4 turns
  hunting and killing the PID on port 3900 by hand, then retries. The fix
  (kill the recorded dev process before reset_db on reuse) is the single
  highest-impact platform change on Windows.

- [ ] **Corrupted staging copies are adopted forever.** `create_copy`'s
  failure cleanup is an rmtree that can itself fail on locked files,
  leaving a partial tree (pb/ + manifest.json, no frontend/). The reuse
  path adopts any dir with a manifest.json, so the broken copy is reused
  until an agent manually deletes it (observed: "staging is missing the
  entire frontend/ directory"). Reuse must check structural completeness
  (frontend/package.json + .lui) or recreate.

- [ ] **Infrastructure failures spend the same mission budget as real fix
  work.** The arc died at 12/12 missions with a large share consumed by
  lock errors, staging corruption, and process hunting — none of which is
  evidence about the app. Either infra-classified `notify_ready` failures
  should not bill the wallet, or the stuck report must separate "app
  attempts" from "environment failures" so the user sees the truth.

- [ ] **The dispute loop has no tie-breaker.** The builder disputed the
  verdict with CLI evidence (op returns 200 via `lui run`); the verifier
  kept failing the same feature (UI shows an error toast — the UI path is
  what users see, and it was genuinely broken/flaky). CLI-op success is not
  UI-path success, and the current guidance ("re-verify; if it comes back
  the same, treat as broken") ping-pongs for rounds before that lands. The
  dispute path should require reproducing through the UI (walk_verify's
  Playwright MCP browser), not the CLI, for UI-observed defects.

- [ ] **The stuck report shows a raw fingerprint hash to the user**
  ("Most persistent failure: 96bf2132126b (2×)"). Should render the feature
  names from the last round's cards instead.

- [ ] **Questions without suggested_responses are invisible to the
  question-park.** The final message ("Deployment is blocked... tell me to
  continue and I'll debug ops.pb.js") had no suggested_responses, so
  `awaiting_answer` was false, the arc read as idle, and the supervisor
  announced "❌ could not be completed" THREE MINUTES after the agent asked
  the user a question — contradictory UX. Second occurrence of this
  heuristic gap in one day (Handle.zip message was the first).

- [ ] **Agents keep reaching for raw `http_request` to 127.0.0.1** and get
  SSRF-blocked repeatedly (16:19, 16:21) before remembering
  `agent_app_http`; the block message could name the right action.

## walk_verify Playwright MCP ref-click fixed (2026-09-10)

- [x] Every verifier click died with `Unknown engine "ref"`, aborting the whole
  walk before it judged anything. Proven empirically (scratch harness driving
  the MCP end-to-end): @playwright/mcp `browser_click` takes `target`, which
  accepts EITHER a snapshot ref OR a Playwright selector. The walk_verify agent
  was passing the ref WITH its `ref=` prefix (copying the snapshot's `[ref=e2]`
  marker), so `target="ref=e2"` was parsed as a selector → unknown engine. Fix:
  walk_verify instructions now require the BARE ref token (`e2`, never `ref=e2`).
  Verified: `target="e2"` clicks OK on 0.0.80; `target="ref=e2"` reproduces the
  error. Also pinned `@playwright/mcp@latest` → `@playwright/mcp@0.0.80` (the
  verified-good version) so it cannot silently float into a breaking release.

## Custom browser probe RETIRED (2026-09-10)

- [x] The custom `browser_probe` action, the `ProbePool` warm-session
  infrastructure, the `lui probe`/`probe-server` CLI, and the in-process
  boot smoke were removed. They reimplemented, thinly, what Playwright MCP
  already does: the DSL had no `select`/`press`/`force`, so it could not
  drive native `<select>` dropdowns or transformed-canvas controls and kept
  forcing agents to mutilate generated apps to fit the probe. walk_verify
  now drives the app solely via Playwright MCP (accessibility-tree refs,
  `browser_select_option`, `browser_press_key`), which is the configured
  primary browser tool. The probe-first mandate (a `probed_at` gate on the
  main agent) is gone with it.
- [x] Walk #1 discovering the obvious bug (2+ min + fix-mission ceremony) —
  two floors now run first: the pipeline auto-invokes the CHANGED server
  ops (structural selection: route-symbol/ops.json diff vs baseline; never
  destructive ops, never bridge-action apps) and returns failures with
  response bodies in the notify_ready result; and walk_verify refuses an
  unprobed boot (probe-first mandate, fail-open when no browser exists).

## Resolved by the SHADOW environment rewrite (2026-09-08)

The dual-environment (dev-copy) machinery was deleted and replaced: an
environment is now the project's OWN tree booted with three redirected
inputs (hidden port, fresh per-boot data dir, content-addressed build
artifact). Nothing is copied; nothing is deleted in place on the hot path.

- [x] Windows lock treadmill — structurally impossible: every boot gets
  fresh dirs + a fresh port; old state is swept lazily.
- [x] Corrupted staging copies — no copies exist to corrupt.
- [x] 71s dev-copy creation — no copy; node_modules used in place.
- [x] Port squatting by zombie dev processes — new port per boot.
- [x] Edit-here-run-there confusion — one tree; "your edits ARE the
  candidate"; lui CLI auto-routes to the shadow via .lui/shadow.json.
- [x] First build misclassified as MODIFY arc — kind now keyed on
  delivered_at, not on the scaffold's bootstrap pb_data.
- [x] Gate build blanking the live UI — shadow gates build to
  `_shadow/<id>/builds/<fingerprint>/`; pb/pb_public changes only at
  promote (and reuse keeps the 68-200s build-skip).

## Resolved during the same investigation (kept for the record)

- [x] Deploys were invisible to warm browsers: PocketBase served `index.html`
  with no `Cache-Control`, and the CraftBot iframe pool ignored src changes.
  Fixed 2026-09-08: `no-store` on the SPA entry via the system hook
  (kit-synced to all apps) + version-stamped iframe src (`?v=<readyAt>`) +
  pool honors changed src.
- [x] Marketplace/status/factory fragility: replaced by the Arc + supervisor
  rewrite (see memory: project-factory-arc-rewrite).
