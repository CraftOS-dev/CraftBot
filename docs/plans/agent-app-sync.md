# Agent-App framework adoption plan

Status: The supported local-app integration is implemented in CraftBot and remains uncommitted. Agent-App is pinned and unchanged. The current implementation and remaining release constraints are recorded at the end of this plan; operational instructions are in `docs/agent-app-sync.md`. The S01–S12 lists below retain the original rollout requirements, including production migration and legacy deletion gates that must not be silently marked complete by a code change.

Date: 2026-11-09

CraftBot branch: `improvement/agent-app-sync`

Base: `origin/V1.4.5` at `d3d5e8b2a126964ea0715bb089ef5ea8f2116a91`.

Agent-App research baseline: `CraftOS-dev/Agent-App` at `06622d24ca9d4c579230977774b3a9dbbb40dcdf` (2026-11-08). Refresh upstream before implementation and reproduce the findings against the version selected for adoption.

Scope: **change CraftBot only; consume Agent-App unchanged.** Agent-App source, tests, plugins, toolkits and protocol are read-only dependencies. No upstream patches, forks, new upstream APIs or upstream releases are part of this work. All new integration code and tests belong in CraftBot. Changes remain uncommitted.

## 1. Objective and scope

Make Agent-App the source of truth for app construction, packaging, installation, operation, verification, authentication, task delivery and lifecycle management. CraftBot provides its existing agent execution, conversations, browser tools and native app presentation through a small host binding.

Prefer existing framework behavior over preserving equivalent CraftBot-specific behavior. Adapt CraftBot to the framework's current CLI, skills, registry and bridge interfaces. Remove superseded CraftBot implementations after their consumers and installed data have migrated. When an interface cannot support a requested behavior, document the limitation and the smallest host-side accommodation; do not turn it into a framework modification or duplicate the framework internally.

The user-visible requirements are:

- Compatible marketplace installation remains deterministic and starts zero agent runs.
- Apps installed from the marketplace, created in CraftBot, imported as framework packages or converted from foreign sources converge on the same lifecycle and communication setup.
- Agent-App works natively in CraftBot: embedded app view, conversation association, progress, questions, cancellation and useful errors.
- App-originated agent work uses the framework task protocol and the requesting principal's authority.
- Existing user data, attachments and retained backups survive migration and rollback.
- Framework behavior is implemented once upstream and consumed as a pinned distribution.

Implementation excludes unrelated CraftBot refactors, a new general-purpose workflow engine, blanket support claims for every toolkit/runtime, and automatic conversion of every foreign application. Optional enhancements do not block the core integration unless an installed app actually depends on them.

## 2. Architecture and ownership

| Concern | Authority | CraftBot's role |
|---|---|---|
| Manifest, protocol, adapters and toolkits | Agent-App | Consume the pinned distribution |
| Requirements, quality standard and framework skills | Agent-App | Load skills and provide native agent/browser execution |
| Inspect, install, export and package provenance | Agent-App | Start jobs and render results |
| App identity and installed-app index | App manifest and framework registry | Associate app IDs with conversations and presentation preferences |
| Ports, processes, live/dev state and lifecycle locks | Agent-App | Invoke lifecycle commands and refresh displayed state |
| Validation and candidate verification results | Existing Agent-App CLI and skill contracts | Run an independent verifier and apply the skill verdict to CraftBot's delivery UI |
| Task claims, credentials, heartbeats and settlement | Existing Agent-App task protocol and selected bridge route | Execute isolated native runs and fulfill the host responsibilities of that existing route |
| Agent runs, conversations and tool execution | CraftBot generic runtime | Execute the work |
| View placement and navigation | CraftBot | Embed/open the framework-provided view URL |
| Optional connected-provider services | Existing app/backend interfaces and CraftBot integrations | Keep only required host access with existing credentials and grants |

Use the existing framework CLI as the integration boundary. Its machine-readable results and install events cover deterministic work; no new library API is a dependency of this plan.

The optional reference host has a separate launcher with fewer checks than the CLI. CraftBot will invoke the CLI lifecycle directly and use the plugins as integration examples. Leave the reference host unchanged.

### State rules

- Framework state remains authoritative; CraftBot stores no independent app port, process or persisted running/stopped truth for migrated apps.
- CraftBot metadata contains only host concerns such as app ID, conversation association, panel preferences and explicit management choices.
- The app task queue owns task truth. CraftBot's run store owns execution truth. A correlation record connects them without creating a second task state machine.
- Framework home selection is explicit and consistent across UI, actions and background work. Default to the shared per-user framework home; support a deliberate profile override where isolation is needed.
- CraftBot manages only apps explicitly attached to it. Closing a tab does not stop an app, and CraftBot shutdown must not stop unrelated apps managed by another harness.
- Toolkits, skills, CLI and protocol compatibility are versioned deliberately. Package version, manifest version and protocol version are distinct fields.

## 3. Product decisions for implementation

These defaults follow the agreed preference for maximum framework reuse. They are implementation targets, not changes already applied to existing installations.

| Existing behavior | Target behavior |
|---|---|
| Separate interview/synthesis wizard | Small request/attachment form followed by the upstream creator workflow in a conversation |
| App-specific factory repair/continuation engine | Normal CraftBot runs, generic cancellation/budgets and explicit Continue/Repair when needed |
| Delivery after incomplete or tooling-blocked verification | Only a valid independent pass authorizes delivery of a built/modified candidate |
| Scoped verification inference and synthesized smoke inputs | Upstream verifier, toolkit gates and app-authored tests; advanced scope optimization deferred |
| Flat schema and operation dumps in every prompt | Modular A2App discovery and relevant context |
| Legacy trigger instructions and `agent_requests` | Declared A2App capabilities/events and framework tasks |
| Custom external-app proxy and manifest | Upstream sidecar adoption or native framework conversion |
| CraftBot-specific sharing authentication | Upstream accounts, invitations and agent login; retain a transport only where needed |
| Forced iframe reload on deployment | Framework/app update watcher with unsaved-input protection |
| Mandatory host theme injection | App/blueprint styling; optional host theme support later |
| Source-parsed component/route counters | Real framework job stages and native run progress |
| PocketBase-specific online backup/retention subsystem | Framework backup/restore; explicitly show stop/backup/restart when required |
| Universal CraftBot LLM/VLM/proxy dependency | Optional provider extension; plain backend API calls remain deterministic |

Preserve generic CraftBot agent execution, conversations, attachments, browser tools, credentials and provider integrations. Removing app-specific orchestration must not remove these shared capabilities.

Existing backup schedules, links, theme settings and service dependencies need migration records and visible handling. Do not silently discard configured behavior. Archived backups remain accessible even if their old scheduler/UI is retired.

## 4. Integration constraints and CraftBot regression checks

| ID | Finding at the research baseline | Evidence level | Required response |
|---|---|---|---|
| F01 | A delegated task credential from an expired claim can progress and complete a newly claimed attempt | Reproduced with adapter-core and an injected clock | Test ownership loss, cancellation and supported credential revocation in the CraftBot binding; do not claim that a host guard fixes arbitrary stale callers |
| F02 | `serve` can start an app while `promote` is inside its lifecycle command | Reproduced with two CLI processes and a disposable fixture | Sequence CraftBot-issued operations per app; document that this cannot serialize independent external CLI callers |
| F03 | Reference-host `launchApp()` accepts manifest ownership drift rejected by CLI `serve` | Reproduced on a disposable fixture | Use the existing CLI launch path, leaving the reference host unchanged |
| F04 | Upstream CraftBot actions lose module-level helper names after CraftBot extracts their function source | Reproduced through the real registry; `agent_app_describe` raises `NameError: _operate` | Self-contained/importing bindings and actual executor integration tests |
| F05 | CraftBot's wizard produces a six-section document incompatible with upstream's current requirements contract | Source inspection | Replace the separate authoring workflow |
| F06 | CraftBot's verifier action promotes incomplete/tooling-blocked candidates | Source inspection | Honor the existing framework skill verdicts in CraftBot's run/delivery handling |
| F07 | Empty progress heartbeats can change `input-required` to `working` | Source inspection | Verify pause behavior of the selected existing bridge route; expose limitations rather than silently treating a question as answered |
| F08 | Successful HTTP delivery transfers execution management to the receiving harness | Source inspection | Select an existing bridge route and implement only its required CraftBot endpoint/runner; no new upstream observation API |
| F09 | Marketplace snapshot: 31 legacy-format listings, one newer-format listing, four unspecified | Catalogue and CLI inspection, 2026-11-09 | Install compatible packages directly; route incompatible apps through an explicit conversion workflow or retain their legacy path |

The previous selected CraftBot test run had 86 passes and one failure caused by a catalogue-test fixture omitting `_marketplace_previews` initialization. Re-establish the baseline; do not hide pre-existing failures inside migration changes.

## 5. Execution order

Each step is a reviewable change or a small group of dependent changes. Complete the stated exit gate before enabling dependent behavior. Keep implementation checkboxes unchecked until supported by evidence.

| Step | Work | Repository | Depends on |
|---|---|---|---|
| S01 | Baseline, supported capabilities and fixtures | CraftBot; Agent-App read-only | This plan |
| S02 | Existing lifecycle contract and host sequencing | CraftBot | S01 |
| S03 | Existing bridge contract and native run mapping | CraftBot | S01 |
| S04 | Existing verification workflow and delivery handling | CraftBot | S01, S02 |
| S05 | Unmodified dependency selection and binding design | CraftBot | S02, S03, S04 |
| S06 | Pinned runtime and thin CraftBot binding | CraftBot | S05 |
| S07 | Native registry, installation and operation | CraftBot | S06 |
| S08 | Two-way execution through the existing bridge | CraftBot | S05, S07 |
| S09 | Creator/modify workflow replacement | CraftBot | S04, S07, S08 |
| S10 | Supporting feature simplification | CraftBot | S07, S08, S09 |
| S11 | Marketplace compatibility and installed-app migration | CraftBot | Package checks can begin after S05; installed cutover requires S10 |
| S12 | Staged rollout, compatibility proof and legacy deletion | CraftBot | S11 |

### S01. Establish the implementation baseline

- [x] Refresh the upstream revision in a separate clean checkout and record the exact revision selected for integration.
- [ ] Inventory relevant tracked code, tests, build outputs, default-app packaging and profile backup/restore paths. Find all consumers before scheduling deletion.
- [ ] Record F01-F04 as constraints of the unchanged dependency. Keep tests for CraftBot's use of those interfaces in CraftBot; do not add or change upstream tests.
- [ ] Define a supported-capability matrix: native PocketBase/React, native React/Node, sidecar adoption and other toolkits whose toolchains are actually available. Use framework discovery instead of a new CraftBot-owned toolkit list.
- [ ] Create disposable fixture apps covering records, relations, uploaded files, accounts, a custom operation and app-originated work. Include a legacy installed-app fixture and a foreign app with explicit operation mappings.
- [ ] Record baseline test results and representative install/launch behavior. Count actual model/agent invocations for deterministic paths; do not infer zero calls solely from elapsed time.

Exit gate: reproducible fixtures, known failures separated from new failures, and a documented supported matrix. No real installed app is changed.

#### Increment 1 — marketplace baseline (2026-11-09)

- Refreshed upstream `main` in the separate review checkout. It remains at `06622d24ca9d4c579230977774b3a9dbbb40dcdf`; use this as the implementation baseline, with the shipped artifact pin finalized in S05. Upstream tracked files remain unchanged.
- Reproduced the selected CraftBot baseline: **86 passed, 1 failed**. The failure was the browser catalogue fixture's missing `_marketplace_previews` initialization.
- Repaired that fixture and checked that its thumbnail route resolves to the preview from the actual fallback repository.
- Extended the archive-install regression through the real browser handler and manager. Both repository aliases now cover successful and failed launches, one placeholder/project ID, session association, correct ready/error events, and zero agent-dispatch/model-call attempts.
- Result: **89 passed** for the command below, using the installed Python 3.10 test environment. The default Python 3.12 interpreter in this workspace does not have pytest installed.

```text
python -m pytest -q tests/test_marketplace_source.py tests/test_agent_app_triggers.py tests/test_agent_app_trigger_consent.py tests/test_agent_app_launch_lock.py tests/test_default_agent_app.py
```

This increment changes tests and this plan only. The install test substitutes network, kit sync, the server pipeline and external UI/session/factory services; it does not establish real framework startup, platform parity or zero model calls across a production install. S01 remains open: record the dependency constraints in CraftBot tests, complete the consumer/capability inventory and data fixtures, then measure the real install path before claiming its exit gate.

#### Scope correction after increment 2 (2026-11-09)

The attempted upstream regression-test increment was outside the intended scope and has been undone: both added test files and both package-script changes were removed. Agent-App has no remaining source changes from this work. F01/F02 remain observed dependency limitations; they are not work items to fix in Agent-App. Future tests of CraftBot's handling belong in CraftBot. S01 remains open.

#### Increment 3 — thin CraftBot CLI transport (2026-11-09)

The user selected the CLI binding as the next small step. This implements the transport portion of S06 without treating the preceding design/compatibility gates or the rest of S06 as complete.

- Added `app/agent_app/framework_cli.py`: `AgentAppCLI(package_dir, home=...)` runs either existing `bin/agent-app.js` or `bin/a2app.js` through CraftBot's Node resolver. The caller selects the binary, built package, framework home and working directory explicitly.
- Arguments remain literal argv; no shell command is assembled. Output retains the CLI's exit code, stdout and stderr. `CLIResult.json()` decodes only a complete JSON document; stdout line callbacks preserve NDJSON install events and ordinary text.
- Node probing runs off the event loop. Command timeouts and cancellation clean up the invocation's process tree, including cancellation during spawn. Output is limited to 8 MiB per stream with an explicit error rather than silent truncation. Ambient `A2APP_TOKEN` is not inherited; invocation-specific credentials stay in the child environment.
- A canceled command does not undo effects already completed or stop detached apps managed by the framework. Lifecycle recovery and native UI job handling remain later work.
- Added `tests/test_agent_app_framework_cli.py` with disposable Node processes, plus an optional read-only smoke test against an unchanged built package. No upstream source or tests were edited.
- Validation on Windows / Node 24.19.0 / Python 3.10: **110 passed** (21 new transport cases and the existing 89-test selection). The real-package smoke test exercised both version entry points and an empty registry in an isolated framework home. Ruff **0.16.1** formatting/lint checks passed for the new Python files.

Example for a caller with an explicitly selected package and profile:

```python
from app.agent_app.framework_cli import AgentAppCLI

cli = AgentAppCLI(package_dir, home=framework_home)
result = await cli.run("agent-app", ["list", "--json"], cwd=workspace_root)
# Check result.ok before using result.json(); stderr retains CLI diagnostics.
```

To include the real-package smoke test, set `CRAFTBOT_TEST_AGENT_APP_PACKAGE` to the built `agent-app-framework` package directory when running `python -m pytest -q tests/test_agent_app_framework_cli.py`. This is a test setting, not production package discovery. At the end of this increment, packaging/pinning, action registration, manager/UI wiring, bridge delivery and migration remained outstanding. The existing `runner.py` and installed-app behavior are unchanged.

#### Increment 4 — native framework registry query (2026-11-09)

- Added `app/agent_app/framework.py`: a small CraftBot entry point selects the built package through `CRAFTBOT_AGENT_APP_PACKAGE` and the framework home through the existing `A2APP_HOME` setting, defaulting to `~/.a2app`. Selection creates no files and does not use the legacy CraftBot registry. No global CLI lookup or automatic download is added.
- Added `agent_app_framework_list` in `app/data/action/agent_app_framework_actions.py`, discovered in the existing `agent_app` action set. Its function imports the binding locally so CraftBot's source-extracting executor can run it (F04). The separate name distinguishes framework IDs from legacy project IDs during migration.
- The action invokes exactly `agent-app list --json` with a 30-second deadline and returns the framework JSON unchanged under `data`. CLI diagnostics and exit codes remain visible; failures and malformed responses are errors rather than successful empty lists. Cancellation propagates into the transport.
- This uses the unchanged query semantics: upstream probes known apps and can set aside a corrupt registry while reporting it on stderr. CraftBot adds no pruning, lifecycle commands or independent registry writes. Existing install/lifecycle/UI paths still use the legacy implementation.
- Added `tests/test_agent_app_framework_actions.py`: real action discovery, source extraction and executor coverage; configuration defaults/overrides; failures; cancellation; and optional real-package checks with empty and populated disposable registries. The populated fixture retains its missing entry without changing its registry file.
- Validation: **75 passed** — 21 new action cases, 21 transport cases (including the real-package checks), and 33 existing action-set/discovery/schema cases. Ruff **0.16.1** formatting and lint checks passed for the new Python files. Agent-App source remains unchanged; no commits were created.

This increment required `CRAFTBOT_AGENT_APP_PACKAGE` to select an unchanged, built package containing `bin/` and `dist/`. Increment 5 below removes that requirement. `A2APP_HOME` still deliberately selects an isolated framework profile; otherwise the shared per-user home is used. These settings are host configuration, not action parameters.

For the disposable real-package checks, set `CRAFTBOT_TEST_AGENT_APP_PACKAGE` and run `python -m pytest -q tests/test_agent_app_framework_actions.py tests/test_agent_app_framework_cli.py`. The tests override `A2APP_HOME` and do not query the user's registry. At the end of this increment, packaging/pinning, further actions, manager/UI adoption, bridge delivery and migration remained open.

#### Increment 5 — pinned distribution and automatic discovery (2026-11-09)

- Bundled `agent-app-framework` **0.2.0** from unchanged upstream revision `06622d24ca9d4c579230977774b3a9dbbb40dcdf` in `app/vendor/agent-app/agent-app-framework.zip`. Its provenance and SHA-256 are recorded alongside it in `source.json`. The archive contains 473 files (1,291,935 compressed bytes), including both CLI entry points, the two production dependencies (`@a2app/sdk`, `@a2app/rules`), upstream licenses, six framework skills and eight blueprints. Bundling a blueprint does not establish support for that stack's entire lifecycle.
- Added `scripts/build_agent_app_framework.py`. It reads the pinned Git object through `git archive`, builds in a disposable directory with upstream's frozen lockfile and **pnpm 9.15.0**, and uses upstream's build/prepack scripts and `pnpm pack`. No upstream source file is patched. Two clean builds on Windows / Node 24.19.0 / Python 3.10 produced the same SHA-256: `b00b7605097a34d61fd83959f58724183ce7937302bbec8c7eaac56d168570d3`.
- Added the stdlib-only `app/agent_app_package.py`. It validates the archive checksum before unpacking into `STATE_ROOT/runtime/agent-app/<sha256>`, publishes a complete directory atomically, and checks cached files against the packaged bytes. Missing or modified distributions fail explicitly. A new pin uses a new directory; it does not overwrite a package another process might still be using. This is an executable cache, not a second app registry.
- Added an offline `agent-app-framework` stage to the shared provisioning pipeline. Installer/doctor checks use the selected code/state roots; doctor creates nothing. Source checkouts also prepare the same cache automatically on first use. No npm/pnpm, download or agent call is involved in unpacking. The existing CraftBot Node resolver still supplies Node.
- Updated `configured_cli()` to use the bundled package by default, retaining `CRAFTBOT_AGENT_APP_PACKAGE` as an explicit development override. Package preparation/verification runs off the action event loop. `A2APP_HOME` selection is unchanged.
- The source-payload builder verifies the distribution and requires the archive, pin, binding, action and provisioning files in the release ZIP. The normal release workflow already calls this builder. Release tests model the future tracked-file list without staging or committing the working changes.
- Validation: **114 passed** across package, CLI transport, native actions, default-app/release-payload, provisioning order and action discovery/schema tests. The shipped distribution ran from a disposable installed-code/profile layout without an upstream checkout: both versions, empty registry, skills, blueprints and a React/Node scaffold passed. No app dependencies were installed and no app server was started. Ruff **0.16.1** formatting/lint checks passed. Upstream remains clean; no commits were made.

Normal use now requires no package-path setting: invoke `agent_app_framework_list` with `{}`. The bundled-distribution tests run without `CRAFTBOT_TEST_AGENT_APP_PACKAGE`; that setting additionally enables comparisons against a separate unchanged build.

Maintainer rebuild (Git, Node >=20 and pnpm required only on the build machine):

```text
python scripts/build_agent_app_framework.py --source <Agent-App-checkout>
```

The script reads the revision from `source.json`, ignores checkout working changes, and requires the rebuilt checksum to match. Use `--update-pin` only for a deliberate, reviewed distribution update. The 1.3 MB archive and pin are source assets intended to be committed together when commits are authorized; they remain uncommitted here. Full clean-machine installer runs on all three operating systems, further actions, manager/UI adoption, bridge delivery and migration remain later work.

#### Increment 6 — framework registry apps in the native app list (2026-11-09)

- The browser adapter now calls the same `list_apps()` binding on WebSocket connection and app-list refresh. Queries run in the background, coalesce across clients, and are cancelled during adapter shutdown. Legacy lists and socket pings do not wait for CLI probes. This invokes `agent-app list --json` directly, without an agent run.
- A separate `agent_app_framework_list` event updates a transient frontend snapshot. Framework IDs never enter the legacy manager, project registry, iframe host or lifecycle handlers. Existing projects keep their current behavior, including when their IDs collide with framework IDs.
- At this increment, the Agent App sidebar and collapsed flyout gained view-only registry rows and manual refresh. Later work integrated these rows into the existing sidebar, added app controls and removed manual refresh. Current snapshots update on connection and app lifecycle changes.
- Loading and failure are explicit. Failed refreshes and disconnections retain rows marked with their last known status; a successful empty result clears them. Upstream stderr notices remain visible even when the CLI successfully returns an empty list after registry recovery.
- Added eight backend cases, including the real bundled CLI against an isolated registry and an authenticated WebSocket ping during a pending query. Added six browser cases covering statuses, ID collisions, refresh/failure/recovery, reconnects, diagnostics and the collapsed flyout. Shared UI fixtures now use the production sidebar dimensions; unrelated socket fixtures stub framework discovery to avoid reading the user's registry.
- Validation: **44 Python tests passed** across registry discovery, WebSocket authentication/lanes, resource notifications and the Mini Browser socket-routing regression. **31 Playwright tests passed**, including existing app-panel and trigger-feedback checks. TypeScript checking and the production Vite build passed; the build reports its large-chunk warning. Sidebar and flyout screenshots were inspected. Ruff 0.16.1 lint passed; formatting passed for the adapter and registry/auth tests, with pre-existing formatting issues elsewhere in `test_mini_browser_ws.py` left outside this change.

At the end of this increment, opening, starting, stopping, removing, embedding and attaching framework apps to conversations remained later steps. No second persistent registry or framework lifecycle implementation was added. Agent-App remained unchanged and no commits were made. S07 remains open.

#### Increment 7 — open an already-running local framework app (2026-11-09)

- Added `open_app_view()` to CraftBot's CLI binding. It refreshes `list --json`, matches the selected registry path and app ID, and invokes the existing `agent-app <path> open --print-only`. Upstream verifies the running app's identity; CraftBot checks the returned ID and local URL before exposing the view. This never starts an app, launches an OS browser, prunes the registry or invokes an agent.
- The new WebSocket request replies only to the requesting connection. Its separate read-only lane avoids waiting behind legacy lifecycle commands. Request IDs keep stale replies from opening an earlier selection; disconnects and timeouts invalidate pending requests.
- Local registry rows now open `/framework-app` in CraftBot's main app area, including from the collapsed flyout. A dedicated presentation component reuses CraftBot's frame URL handling, browser permission declarations and surface styling, without entering the legacy project store, iframe pool, consent workflow or theme bridge. An iframe load is navigation feedback, not an additional app-health claim.
- Stopped, missing, unregistered, replaced and unreachable apps show explicit guidance and Retry. The view queries again on reconnect, preserving its iframe and edits when the verified URL is unchanged. A lost response or stalled frame has a retry path; retry verifies again before navigating. The frame is scoped to this page: navigating away closes it, and returning verifies and loads it again. Persistent chat-panel presentation and conversation attachment are later work.
- Connected remote entries remain display-only. Apps using `sidecar.json` show an explicit unsupported-view message: the pinned CLI returns their control address, while the adopted UI runs elsewhere. CraftBot does not guess a port, scrape boot logs or modify upstream to invent a view-address contract.
- Validation: **59 Python tests passed**, with two optional separate-build smoke tests skipped because `CRAFTBOT_TEST_AGENT_APP_PACKAGE` was not supplied. The real bundled CLI ran against a disposable registry and local HTTP fixture, opened the matching identity, refused a replacement identity on the same port, and left the app/registry files unchanged. Native socket routing, path/ID collisions, stale statuses, invalid URLs, failures and cancellation were covered.
- **47 distinct Playwright cases passed**: 16 framework-opening cases plus 31 registry-list, existing panel and trigger-feedback regressions. The last frame styling adjustment was followed by all 16 opening cases. TypeScript, production Vite build, Ruff 0.16.1 lint/formatting and diff whitespace checks passed; Vite retains its large-chunk warning. The final app-view screenshot was inspected.

Agent-App source and its packaged pin remained unchanged. All implementation and tests were in CraftBot, with no commits or staging changes by the agent. At the end of this increment, Start/Stop through the existing CLI was the next small step. S07 remains open.

#### Increment 8 — Start/Stop local registry apps (2026-11-09)

- Added `change_app_state()` to the CraftBot binding. Inside a per-app command sequence it refreshes the registry, checks the selected path and identity, and invokes exactly `agent-app <path> serve` or `agent-app <path> stop`. Different apps can proceed independently. Canonical paths share the sequence across callers in this CraftBot process; independent harnesses remain subject to upstream's existing locking limitations. No framework lock file is created or altered by the binding.
- Start retains upstream's build/health/ownership checks. It does not imply dependency installation, browser opening or agent execution. Stop targets the live served instance, preserving upstream's recorded-process checks. Development instances and task bridges remain running; the UI explains this in the Stop tooltip and reports surviving instances/bridges after completion.
- Every attempted command is followed by a registry query. Exit zero alone cannot become a running/stopped assertion: an unmanaged instance with no serve record, failed health check, status-query failure, malformed output or timeout remains an explicit failure or uncertain outcome. The diagnostic disclosure added in this increment was later removed; current controls show action errors inline. Command deadlines are 660 seconds for serve (including upstream's ten-minute build budget) and 30 seconds for stop, with registry probes separately bounded at 30 seconds.
- The browser adapter broadcasts operation progress and completion to connected tabs and replays in-flight operations on reconnect. Another request for the same app joins the current operation with explicit feedback; it does not queue a hidden opposite command. The pending map is transient presentation state, not a second process registry. Framework apps are never registered with the legacy manager or added to its shutdown lifecycle.
- Registry observations use a shared sequence number. A probe begun before a command cannot overwrite its later snapshot; an obsolete background read queries again so newly connected tabs that joined it still receive fresh data. This was exercised with deliberately reordered reads; the sequence avoids equal-timestamp ordering on Windows.
- Added Start/Stop controls to local registry rows in the sidebar/flyout and the framework app view. Controls disable while busy, disconnected or displaying stale registry data. Starting from the app view triggers fresh URL/identity verification; stopping clears the displayed frame and invalidates earlier open replies. Connected remote entries remain display-only, and missing/unreachable entries have no lifecycle controls. The existing sidecar view-address limitation remains.
- Added `SocketClient.sendNow()` for these explicit mutations. A disconnected or failed send never enters the reconnect outbox. A lost connection marks the operation outcome unknown; reconnect can rejoin an active server operation or refresh actual registry state. There is no automatic command replay, persistent job recovery, cancellation UI or automatic stop when leaving the page.
- Validation: **103 distinct Python cases passed** across lifecycle, registry, opening, native actions, socket authentication/lanes and resource notifications; two optional separate-build smoke tests were skipped. The 17 lifecycle cases include real bundled CLI start, idempotent Start with the same PID, Stop, idempotent Stop, restart, and refusal after manifest ownership drift. All real work used a disposable app/profile and cleaned up through upstream Stop. Tests also cover per-app sequencing, cross-tab coalescing, cancellation, changed identities, command failures, state mismatches and stale reads.
- **56 distinct Playwright cases passed**, including nine lifecycle cases and existing registry, opening, app-panel and trigger-feedback coverage. TypeScript, production Vite build, Ruff 0.16.1 lint/formatting and diff whitespace checks passed. Vite retains its large-chunk warning. Sidebar controls and the app-view Stop control were visually inspected.

Agent-App source, the package pin and bundled archive remain unchanged. All edits are in CraftBot; no commits or staging changes were made by the agent. S02/S07 remain open for the remaining lifecycle and management paths. The next small step is conversation attachment for registry apps; two-way task delivery follows its separately reviewed bridge binding.

### S02. Use the existing lifecycle and sequence CraftBot's commands

- [ ] Map CraftBot lifecycle entry points onto the unchanged `agent-app` commands and their actual result formats.
- [ ] Use one CraftBot-side per-app job sequence for conflicting host-issued operations, including UI, action and background entry points. Reuse existing generic coordination where possible.
- [ ] Use CLI launch rather than the optional reference-host launcher. Preserve the CLI's identity, ownership and failure checks.
- [ ] Follow the current stop -> promote -> serve sequence and report each outcome truthfully. A successful promotion is not yet a running app.
- [ ] Record recovery behavior using the existing backup/restore/export commands. Keep code rollback distinct from database restore.
- [ ] Document the boundary: CraftBot sequencing does not repair upstream locks or coordinate an independent harness issuing conflicting commands. Do not write or steal internal framework lock files.

Validation: CraftBot entry points cannot overlap conflicting jobs; CLI failures reach the UI; no ready event follows a failed promotion or launch; process ownership and data recovery checks remain covered in CraftBot.

Exit gate: a tested command mapping and clearly bounded host coordination, with Agent-App unchanged.

### S03. Map the existing bridge onto native CraftBot runs

- [ ] Evaluate the current headless and inbound delivery routes, using existing plugins as read-only examples. Select the route that reuses the most existing bridge behavior while supporting native CraftBot execution.
- [ ] Record which responsibilities that route already handles and which it explicitly delegates to the receiving host. Do not add a new framework run-observation protocol.
- [ ] Test the actual request/credential shape, task identity, completion signal, queue delay, cancellation and restart behavior from a CraftBot-owned fixture.
- [ ] Keep requesting-principal credentials isolated per run and use existing credential-management APIs where supported. Never fall back to owner authority.
- [ ] Check claim loss and paused questions against the unchanged protocol. Stop local work when ownership is lost; do not assume that stopping a local run invalidates a credential everywhere.
- [ ] If a mode cannot be made reliable through the current interface, record the limitation and withhold that mode rather than inventing protocol semantics or silently replaying work.

Validation: scoped execution, actual task settlement, repeated delivery, pause/resume and cancellation in the selected route. Tests assert CraftBot's behavior and explicitly identify dependency limitations.

Exit gate: a concrete, tested integration with an existing bridge route; no framework modifications are required by the design.

### S04. Follow the existing verification workflow in CraftBot

- [ ] Load the framework's existing creator, modify, importer and walk-verify instructions unchanged. Remove conflicting CraftBot prompt rules.
- [ ] Run the independent verifier through CraftBot's generic agent/browser facilities and preserve the existing `pass`, `defects`, `incomplete` and `blocked` meanings.
- [ ] Track which candidate and verifier run a result belongs to in CraftBot run metadata; do not introduce a new framework verdict file or API.
- [ ] Make CraftBot's built/modified-app delivery handling require a valid pass for that candidate, followed by successful framework promotion and serving.
- [ ] Keep compatible marketplace installation on the existing deterministic path; data-only operations do not initiate a build or verification run.

Validation: incomplete/blocked results and changed candidates cannot announce delivery in CraftBot; an independent pass follows the existing CLI gate; compatible installation still starts zero agent runs.

Exit gate: CraftBot follows the framework's current workflow and reports readiness truthfully, without changing shared skills or CLI enforcement.

### S05. Select the unchanged dependency and design the thin binding

- [x] Pin an existing upstream artifact or reproducible build of an exact revision, with matching toolkits and skills. Preserve upstream contents and record provenance; do not maintain a patched copy. See increment 5.
- [ ] Verify supported entry points and clean-machine packaging before wiring the installer to them.
- [ ] Design the smallest CraftBot-owned dispatcher around the existing CLI, using the integration starter and plugins as references rather than editing them.
- [ ] Make CraftBot action functions compatible with its source-extracting registry by importing the local dispatcher or using a supported native registration path. Test through the real executor.
- [ ] Reuse framework discovery/schemas where available and explicitly select `agent-app` versus `a2app`; a module named `promote` must still route to the operation client.
- [ ] Define task/run correlation and authenticated local transport only where needed by the selected existing bridge route. Keep credentials out of prompts, logs and process-wide mutable state.

Validation: dependency provenance, real registry/executor calls, command argument/result handling, and a native-run fixture using the existing bridge contract.

Exit gate: CraftBot can consume a pinned, unchanged Agent-App distribution through a small local binding.

### S06. Introduce the thin CraftBot binding

- [x] Bundle the pinned framework artifact through CraftBot's installer and source/release packaging. Reuse its existing Node resolution; do not require a global CLI installation. See increment 5; full cross-platform clean-machine installer validation remains open.
- [ ] Implement one asynchronous command transport with absolute executables, argument arrays, bounded execution, streamed output and process-tree cancellation. Keep credentials scoped to the invocation.
- [ ] Preserve command-specific output: install NDJSON, lifecycle JSON and human-readable A2App discovery screens must not be forced through one brittle parser.
- [ ] Register the shared actions without duplicate names. Temporary aliases delegate to one implementation and have a removal list.
- [ ] Load the framework skill bundle and blueprint references from the pinned artifact. Remove contradictory prompt instructions for migrated apps.
- [ ] Add a narrow transitional backend selector. Existing legacy apps continue through the frozen legacy path; all eligible new apps use upstream. No new feature development in the legacy backend.

Primary CraftBot touchpoints: `app/agent_app/runner.py`, `app/data/action/agent_app_actions.py`, `app/node_runtime.py`, `agent_core/core/prompts/application.py`, installer/release packaging and skill loading.

Exit gate: actual UI/action invocations reach the pinned runtime with correct arguments and without blocking the server loop or flashing Windows consoles.

### S07. Move app management, installation and operation to the framework

- [ ] Read the framework registry and derive process state through its commands. Store only CraftBot conversation/presentation metadata by canonical app ID.
- [ ] Make framework-home/profile selection consistent across actions, UI and background jobs. Reconcile external changes from other harnesses without taking over unrelated apps.
- [ ] Route marketplace, ZIP, directory and Git packages through the same inspect/install pipeline. Persist enough install-job receipt information to recover the UI after restart without blindly reinstalling.
- [ ] Stream install stages into the existing native app placeholder and preserve its session association. Distinguish failed, repairable, installed/stopped and ready states.
- [ ] Route launch, stop, remove, backup, restore and export through upstream commands. Expose destructive consequences through existing product controls.
- [ ] Replace flat schema/operation injection with credential-aware modular discovery and relevant context. Use the canonical operation client rather than the lagging Python SDK until parity is established.
- [ ] Model view and control addresses separately for sidecar/remote cases. Show capabilities and unsupported paths honestly.
- [ ] Preserve native panels, navigation, media permissions and safe origin handling. A frame load is not proof of app health.

Primary touchpoints: `app/agent_app/manager.py`, `agent_view.py`, `marketplace_source.py`, browser adapter routes, frontend `features/agentApps`, settings and app references.

Exit gate: install/open/operate/stop/restart works natively through upstream; compatible marketplace installation records zero model or agent calls; no duplicate project registry authority.

### S08. Connect every supported app to native agent execution

- [ ] Register the CraftBot harness profile without overwriting user configuration or selecting another harness implicitly.
- [ ] Implement the CraftBot endpoint/runner for the existing route selected in S03. Reuse the bridge's current heartbeat/settlement behavior and implement only the responsibilities that route delegates to the host.
- [ ] Use per-task/per-principal isolated execution contexts. Exclude delegated tasks from ordinary trigger aggregation and avoid sharing credentials through app-wide session state.
- [ ] Correlate the task with its verified app ID, live/dev environment, requesting principal and local run using fields actually available in the current protocol. Local directory routing must not redirect live tasks into a dev database.
- [ ] Route progress, questions, answers and cancellation into the native UI. Propagate cancellation to the actual run and tools, not only its dispatch wrapper.
- [ ] Reconcile task/run correlations after either process restarts. Use idempotency records for repeat deliveries and existing irreversible-action accounting where applicable; do not claim exactly-once external effects.
- [ ] Make app attachment common to marketplace install, creation, package import and conversion: identity, conversation/view, capabilities, persisted grants and selected bridge.
- [ ] Preserve explicit app-level consent for agent work and re-review expanded capabilities. Avoid repeated approval prompts for unchanged persisted grants.
- [ ] For adopted foreign apps, require declared event/task wiring when app-originated agent work is a requirement. An operations-only sidecar must not be advertised as task-capable.

Exit gate: an app submits work through the unchanged bridge contract, CraftBot executes as the requesting principal, and supported queueing, pause, cancellation and restart paths have been demonstrated. Any unsupported mode is explicitly identified rather than enabled with assumed guarantees.

### S09. Replace the creation and modification workflow

- [ ] Reduce the custom creation entry point to request/attachments and supported options; let upstream creator author the canonical requirements and task ledger.
- [ ] Use the upstream creator, modify, importer and operator activities without separate CraftBot requirements/quality prompts.
- [ ] Provide independent native verifier execution and record its result in CraftBot as described in S04.
- [ ] Drive dev -> validate -> independent verify -> stop live -> promote -> serve through the shared workflow. Readiness follows the actual serving result.
- [ ] Replace app-specific repair missions with normal run continuation and explicit Continue/Repair where necessary. Preserve generic budgets, pause and user cancellation.
- [ ] Stop writing new `.factory` arcs, scoped-verification baselines and defect-distillation records for migrated apps.
- [ ] Replace `notify_ready` policy and custom verifier tool semantics with canonical operations or short-lived compatibility aliases.

Primary touchpoints: `app/agent_app/wizard.py`, `walk_verify.py`, `verify_scope.py`, `op_smoke.py`, `ops_verify.py`, `app/factory/host_craftbot.py`, app actions, prompts and framework-specific skills.

Exit gate: a new app and a later code change complete through upstream contracts; incomplete/blocked verification remains visible and never announces delivery; data-only work skips the build flow.

### S10. Simplify supporting app features

- [ ] Use upstream update handling for code/data refresh; remove deployment cache-busting that navigates over unsaved input.
- [ ] Keep app-owned styling by default; remove mandatory legacy theme messages from migrated apps. Preserve generic frame/panel mechanics.
- [ ] Replace inferred construction counters and manufactured completion percentages with actual job/run stages and task-ledger progress where available.
- [ ] Adopt existing framework backup/restore and removal preservation behavior. Preserve existing archives and disclose temporary stop/restart when required; adding online snapshots to a toolkit is outside scope.
- [ ] Replace custom app-sharing authentication with upstream account/invite/login flows. Treat tunnel transport separately, require the supported public URL/TLS behavior, and do not expose single-user apps as though they already had multi-user access control.
- [ ] Inventory actual users of CraftBot's direct LLM/VLM/integration bridge. Preserve the minimal required host integration through existing app/backend interfaces, or migrate app consumers to ordinary backend integration. Do not introduce a new framework provider contract. Deterministic provider calls do not become agent turns.
- [ ] Replace custom external runtime/proxy assumptions with upstream sidecar contracts. Gate unsupported lifecycle/data backup features explicitly.
- [ ] Adapt default-app provisioning, full-profile backup/restore and app export. Full user backup and sanitized distribution export remain distinct operations.

Exit gate: selected simplifications are reflected in the UI and migration policy; no installed feature silently loses its data or authority checks.

### S11. Handle marketplace compatibility and migrate installed apps

#### Marketplace and bundled packages

- [ ] Refresh catalogue compatibility counts and inspect unknown-version packages.
- [ ] Install compatible published packages directly through the unchanged framework, with zero agent runs. Do not claim that incompatible legacy packages can use that same path unchanged.
- [ ] Route incompatible sources through the existing importer/conversion workflow when conversion is requested, or keep their current legacy support during transition. Conversion is distinct from deterministic installation.
- [ ] Validate installation and task attachment with the pinned runtime. Keep source compatibility explicit in CraftBot; external catalogue publication is outside this implementation.
- [ ] Repackage CraftBot's bundled default app using a verified compatible artifact, converting that app if needed; retain idempotent provisioning receipts. Installing the bundled artifact does not repeat its conversion.

#### Installed apps and user data

- [ ] Build a dry-run inventory and migration report: format/toolkit, schema, records/relations, files, accounts, operations, provider dependencies, links, pending/in-flight work, backups and CraftBot metadata.
- [ ] Implement a dedicated, journaled migration utility. Never use sanitized package install or in-place package import on a populated user app.
- [ ] Quiesce affected writers and agent work for cutover. Preserve a consistent database/files snapshot and the matching previous code/configuration.
- [ ] Build and verify a migrated candidate separately. Preserve IDs where supported; otherwise record an explicit mapping for app IDs, records, accounts, sessions and references.
- [ ] Preserve existing accounts and ownership semantics. Rotate runtime secrets and rebind host grants without inventing broader authorization.
- [ ] Reconcile legacy pending/in-flight requests. Do not automatically replay work whose external effects are uncertain; retain its status/evidence and provide an explicit resolution path.
- [ ] Validate record counts, relationships, file contents, representative operations and authentication behavior before switching the live binding.
- [ ] Make cutover resumable and rollback explicit. Rollback restores the matched code/data/configuration set; after new writes, require reconciliation or a fresh capture before reverting.
- [ ] Retain original data and old backup archives until the migration is verified and retention/removal is intentional.
- [ ] Migrate old links, conversation associations, panel references, backup settings and provider configuration visibly. Keep unsupported apps on the frozen legacy path until a supported migration exists.

Exit gate: compatible marketplace installation stays deterministic, incompatible sources have an explicit supported path, and populated legacy fixture apps migrate and roll back without loss. Production migration requires an explicit target inventory and verified recovery artifacts.

### S12. Roll out, prove compatibility and remove the legacy implementation

- [ ] Pilot one converted marketplace app with app-originated work, then a newly built app, a modified app, an imported package and a converted foreign app.
- [ ] Exercise real native UI behavior: progress, ready/failed states, questions, cancellation, unsaved input, app references and restart reconciliation.
- [ ] Verify cross-harness portability: an app created outside CraftBot works inside it, and a CraftBot-created app works through another supported harness.
- [ ] Test supported OS installers and clean machines, including spaces/non-ASCII paths, missing toolchains, interrupted jobs and offline diagnostics.
- [ ] Run the focused suites listed below, then the repository-required checks. Record known limitations separately from passes.
- [ ] Enable new-framework defaults for supported paths; retain migration fallback only for identified legacy installations.
- [ ] Remove legacy source, aliases, prompts, obsolete tests/settings and state writers after the deletion criteria in section 7 are met.
- [ ] Document the supported runtime pin, upgrade process, user-visible changes and recovery procedure. Publish/release through the normal repository workflow.

Exit gate: one maintained framework implementation, a narrow host binding and no active legacy consumer hidden behind a compatibility alias.

## 6. Acceptance and test matrix

| Scenario | Required evidence |
|---|---|
| Compatible marketplace install | Native streamed progress and usable app; zero agent/model invocations |
| Package import | Framework classification/sanitization; required independent verification; no publisher runtime credentials/grants retained |
| Foreign adoption/conversion | Declared capability limits; working operations; task wiring tested when promised |
| Build and modify | Canonical requirements, independent pass for exact candidate, successful promotion/serve |
| Incomplete/blocked verification | Candidate remains undelivered; useful visible state; no false ready announcement |
| Lifecycle concurrency | CraftBot-issued conflicting jobs serialize per app; independent external callers remain an explicitly documented dependency limitation |
| Data safety | Dev writes never reach live; migration/restore failure leaves recoverable data; files/relations/accounts preserved |
| Task authority | Requesting principal and scoped credential used; CraftBot handles local ownership loss/cancellation and supported revocation; global stale-credential guarantees are not claimed |
| Task recovery | Duplicate delivery, host/bridge/app restart, long queue wait, question/resume and cancellation behave correctly |
| Native action execution | Real registry extraction and executor path; no missing globals or duplicate registrations |
| Multiple hosts/profiles | Consistent index, explicit management ownership, no stopping another host's app |
| UI freshness | App data refreshes correctly; code updates protect unsaved input; sidecar view/control addresses work |
| Backup and removal | Recovery artifacts retained according to framework policy; old archives remain accessible |
| Distribution | Pinned bundle works outside development checkout on each supported OS |

Relevant existing CraftBot suites include `tests/test_marketplace_source.py`, `tests/test_agent_app_triggers.py`, `tests/test_agent_app_trigger_consent.py`, `tests/test_agent_app_launch_lock.py`, `tests/test_default_agent_app.py`, app lifecycle/data/instance tests under `app/agent_app/`, and the frontend panel/frame tests. Replace tests of retired policy with tests of the new contract; preserve regression coverage for data safety and process ownership.

CraftBot-owned integration coverage should exercise the unchanged framework's install/package, bridge/task credentials/delivery, lifecycle, native binding and sidecar interfaces. Existing upstream suites may be run read-only as dependency evidence. Do not modify them, and do not treat fake-CLI wrapper tests as full host integration evidence.

## 7. Deletion criteria

Delete a legacy subsystem only when all of the following are true:

1. Its supported consumers use the upstream path or have an explicit deferred-migration record.
2. No migrated app, action, prompt, installer, default app or profile-restore path references it.
3. Required data/archives and rollback artifacts are retained independently of the deleted code.
4. The replacement passes its acceptance scenarios on the supported platforms.
5. Compatibility aliases are either removed or narrow delegates with a documented end condition.

Expected removals/reductions include the vendored `agent-app/` implementation; legacy portions of `manager.py`, `runner.py`, `instances.py` and `lifecycle/`; `marketplace_source.py`; custom external A2App proxy behavior; wizard synthesis; app-specific factory code; old verification/scope/smoke machinery; request hooks and trigger instructions; old framework prompts/skills; and app-specific state/settings no longer used.

Do not delete generic session, action, credential, browser, scheduling or process utilities merely because the app subsystem currently calls them. Recheck all callers first. Keep migration-only readers isolated from normal new-app execution.

## 8. Change and release discipline

- Leave Agent-App unchanged, including its tests and plugins. All implementation changes stay in CraftBot; the dependency is pinned and consumed without local patches.
- Split changes at the step boundaries. Each implementation PR records behavior changed, validation, migration consequences and rollback behavior.
- Test the pinned upstream version in required CI; use a separate compatibility job for upcoming upstream changes.
- Keep new-framework enablement controlled during migration. Switching code paths is not a substitute for migrating user data.
- Do not silently retry irreversible external actions when task/run state is ambiguous.
- Do not remove legacy fallback until the supported installed-app inventory is accounted for.
- Estimate durations after S01 establishes the fixture matrix and actual migration inventory; no calendar promises are implied by this plan.

## 9. Source references

CraftBot paths below refer to the branch base; line numbers will change during implementation.

- `app/agent_app/manager.py`: current registration, install/import, lifecycle/watchdog and legacy request dispatch.
- `app/agent_app/runner.py` and `app/agent_app/lifecycle/`: vendored framework execution and dev/live behavior.
- `app/data/action/agent_app_actions.py`: custom workflow actions and delivery semantics.
- `app/agent_app/wizard.py`, `walk_verify.py`, `verify_scope.py`, `construction_events.py`: competing workflow/specification and presentation logic.
- `app/factory/host_craftbot.py`, `app/factory/engine/`: app-specific continuation and repair supervision.
- `app/triggers/runtime.py`, `app/triggers/service.py`: generic durable execution and aggregation rules.
- `agent_core/core/action_framework/registry.py`, `agent_core/core/impl/action/executor.py`: source extraction and action execution.
- `app/ui_layer/adapters/browser_adapter.py`, frontend `features/agentApps/`: native app controls and presentation.
- `app/ui_layer/settings/profile_bundle.py`, `app/provision/default_agent_app.py`, `scripts/bundle_default_agent_app.py`: backup/restore and bundled-app migration consumers.
- [Agent-App packaging contract](https://github.com/CraftOS-dev/Agent-App/blob/06622d24ca9d4c579230977774b3a9dbbb40dcdf/spec/v0_2/packaging.md).
- [Agent-App authentication and task authority](https://github.com/CraftOS-dev/Agent-App/blob/06622d24ca9d4c579230977774b3a9dbbb40dcdf/spec/v0_2/auth.md).
- [Agent-App CLI lifecycle](https://github.com/CraftOS-dev/Agent-App/tree/06622d24ca9d4c579230977774b3a9dbbb40dcdf/framework/cli/src/commands).
- [Agent-App bridge](https://github.com/CraftOS-dev/Agent-App/blob/06622d24ca9d4c579230977774b3a9dbbb40dcdf/framework/cli/src/lib/bridge.ts).
- [Shared integration starter](https://github.com/CraftOS-dev/Agent-App/tree/06622d24ca9d4c579230977774b3a9dbbb40dcdf/harness-plugins/integration-starter).
- [Upstream CraftBot binding](https://github.com/CraftOS-dev/Agent-App/tree/06622d24ca9d4c579230977774b3a9dbbb40dcdf/harness-plugins/craftbot).
- [Framework skills and quality standard](https://github.com/CraftOS-dev/Agent-App/tree/06622d24ca9d4c579230977774b3a9dbbb40dcdf/skills).


## Current implementation checkpoint (2026-11-09, uncommitted)

CraftBot now consumes the unchanged Agent-App CLI, registry, packaging, skills, blueprints, lifecycle and task protocol for supported new apps. Original installed apps retain their compatibility backend until an explicit migration succeeds. No Agent-App source/test/plugin changes or Git commits were made.

| Area | Implemented behavior and evidence |
|---|---|
| Pin and distribution | Verified bundled CLI/SDK/toolkits/skills at `06622d24ca9d4c579230977774b3a9dbbb40dcdf`; reproducible packaging and hash-checked cache; provisioner and release payload checks |
| Native workflows | Ordinary create/modify/import/convert/operate chats use original framework skills and references; isolated independent verifier reports bind to the current validation stamp; promotion retains the upstream exact-tree gate |
| Deterministic management | Native registry, inspect/catalogue/install, streamed durable jobs, Start/Stop, backup/restore/export/remove and account commands; no model calls for package acquisition/lifecycle |
| Two-way tasks | Core-runtime host works without browser; private inbound endpoint, explicit app grants, owner/member authority, per-task scoped credentials and isolated context, progress/questions, cancellation and restart/retry receipts |
| Native presentation | App views, persistent panels, conversation attachment, startup preferences, registry mentions and migrated reference redirects; app-owned styles; no forced reload over unsaved input |
| Profile sharing | Sanitized app packages install separately with new identity; runtime data, credentials and task grants are not copied; job/errors are surfaced after profile import |
| Bundled board | Converted only app-owned Kanban code onto the existing PocketBase blueprint. Independent verification covers 56 executed non-destructive operations plus five destructive shape checks; complete gate and exact fingerprint in package provenance |
| Default provisioning | Fresh installs acquire that verified artifact through an offline catalogue using upstream install; fresh identity, startup preference, no model calls, idempotent receipts and occupied-destination checks |
| Installed-app migration | Read-only preview, separate candidate workflow, verified empty PocketBase target, stopped-writer snapshots, collection/relationship/account/record/file checks, journal, explicit cutover and rollback. Both installations and old archives retained; uncertain work never replayed |
| Cleanup boundary | New app entry points bypass the custom wizard/factory/verifier/theme/registry/request stack. Those implementations remain only for existing legacy consumers and recovery; generic sessions/browser/actions remain shared |
| Validation and rollout | Real bundled CLI/adapter/package tests, native task action extraction, Windows PocketBase package installation and app→CraftBot→app round-trip, browser regressions/typecheck/build. Linux/macOS/Windows CI defined but not remotely executed without a commit/push |

The real bundled-board integration test installed into a fresh path containing spaces, verified fresh identity and repeat-install idempotency, stopped and restored it using the core startup preference, enabled the canonical bridge, received a Kanban work request, operated with its delegated credential, wrote an attributed comment back, and completed the task. Installation and restart emitted no agent trigger. The task used a deterministic native turn, not a paid model response.

Final local validation: 611 backend tests passed in the expanded run, with four opt-in cases subsequently passing in separate real-CLI/default-board runs; 60 browser tests passed; 58 overlapping integration checks passed in the isolated Python environment. Typecheck, production frontend build, Ruff and whitespace checks passed. The Agent-App checkout is clean, bundle hashes match provenance, the branch still points at its original base commit, and the existing Git index was preserved.

Catalogue inspection through the pinned CLI found the primary `CraftOS-dev/agent-app-collection@main` unavailable (404), with upstream fallback to `CraftOS-dev/living-ui-marketplace@main`: 36 entries, 31 explicitly legacy; four unspecified-version entries were confirmed legacy by inspection; `dev-studio` requires a blueprint absent from this pin. No existing published entry was directly installable as-is. Native compatible catalogue/package fixtures and the bundled Kanban artifact prove the transport; external marketplace publication is separate work.

Remaining rollout constraints, not hidden implementation claims:

- Existing user apps are not automatically migrated. External runtimes or schema-changing conversions need app-specific mapping and independent verification. The generic automatic data transfer is limited to compatible PocketBase schemas; old scheduled-backup settings are disclosed and not silently transferred.
- Delete the frozen legacy backend only after an actual installed-app inventory satisfies section 7. Deleting it now would remove existing app functionality and rollback support.
- Sidecar apps with separate View/control addresses and deployed/shared remote presentation remain explicitly unsupported by the current native View resolver. No inferred URL or fake task capability is supplied.
- Upstream stale-claim and independent cross-harness lifecycle races (F01/F02) remain dependency limitations. CraftBot checks current ownership and serializes its own lifecycle calls; it does not claim to repair other harnesses.
- Remote CI/clean-machine Linux and macOS execution, model-driven workflow pilot acceptance, marketplace publication and release remain unperformed. No credentials, production state or deployment were used for these tests.

See `docs/agent-app-sync.md` for commands, component ownership, task permissions, upgrade/recovery procedures and validation instructions.
