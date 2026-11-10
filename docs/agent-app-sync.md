# CraftBot's Agent-App binding

New apps use Agent-App's existing CLI, registry, skills, blueprints, authentication,
package installer, task queue and lifecycle. CraftBot supplies conversations,
execution, progress, app panels and explicit host permissions. Agent-App is not
patched. The pin is `06622d24ca9d4c579230977774b3a9dbbb40dcdf`.

## Using it

Use the **+** beside **Agent App** for the existing Marketplace, Create Custom
and Import dialog. Compatible packages install directly; progress uses the
existing toast and success offers **Open app**. The separate framework management
page is removed; old `/apps` links redirect to Settings → Agent App. Internal job
receipts remain available to the host for diagnosis and interrupted-install recovery.
A timeout is not permission to repeat an installation: inspect its receipt,
destination and the refreshed registry first.

Creation starts as an `agent_app` conversation with a persisted
`agent_app_framework_pending` marker and the chosen app name. The sidebar shows
it under Agent App before scaffolding, without inventing a framework registry ID.
Registration binds that same conversation to the real app and clears the pending
marker. Startup upgrades older pending creation conversations recorded by this
host; unrelated chats are not reclassified by title.

Creation opens the original `ConstructionDock` and `AgentAppWorkspace` side chat,
including the existing animated mascot. CraftBot's creation receipt keeps a
presentation-only `building` flag until the CLI reports the live app running;
scaffolding and independent-verifier handoffs retain the construction view.
`agentAppBuild` replays the builder's todos on reconnect, and the existing
`agent_app_todos` feed streams progress under `framework-build:<sessionId>`.
The live app replaces only the centre surface, preserving the same chat and draft.

The marketplace cards and CLI share `agent_app.marketplace_ref` (overridden by
`CRAFTBOT_MARKETPLACE_REF`), passed as the existing `A2APP_MARKETPLACE_REF` option.
Additional installed toolkits can be selected with
`agent_app.framework_toolkits_dir`; an explicit `A2APP_TOOLKITS_DIR` takes precedence.
These are separate from the immutable bundled framework. In the checked staging
catalogue, migrated PocketBase apps require the marketplace's
`blueprint-pocketbase-kit`; Development Studio instead records
`blueprint-dev-studio`, which is not in the pinned framework package.

Settings → Reset → AgentApp apps includes local framework registry apps and
legacy projects. It cancels pending installs, stops app conversations, uses the
existing CLI Stop/Remove flow (including data preservation), and forgets missing
entries. Removal failures are reported. Workspace-only resets preserve registered
app folders; selecting both options removes apps before clearing workspace files.
The ordinary chat reset continues to preserve apps.

An app's settings provide Start/Stop, startup preferences and
backup/export/restore/removal. Its side chat handles app work, including the
existing validation, independent verification and account-management workflows.
Opening a panel does not start or stop the process. App frames retain unsaved
input across navigation; the migrated Kanban asks before reloading updated code.
The full app page uses the same resizable CraftBot chat panel as legacy Kanban,
with shared collapse/size preferences and a vertical split on mobile. Registry
apps attach to their existing CraftBot conversation through the host; opening
this chat does not start an agent turn or enable app-task permissions.
These are dedicated `agent_app` sessions, identified separately from legacy
projects. They use the framework action set, appear under the app rather than
Chat & Task, and show working/unread status on the app row. Commands issued from
Main or another conversation cannot replace the app's backing session.

Registry-app turns automatically load the unchanged `framework-operator` skill;
delegated app tasks receive it too. Current-view questions use `a2app context`,
then discover declared context operations when an app's optional binding is empty.
Selected IDs must be re-fetched through A2App; saved-project timestamps are not
selection evidence. Task credentials can read context but cannot manage saved
credentials. Development Studio publishes its browser view through declared
`workspace-context` / `view-context-publish` operations and read-only `views`
records because its pinned, locked blueprint exposes no context-binding hook.
No separate CraftBot protocol or upstream framework modification is involved.

Enable **app tasks** in an app's settings to select CraftBot as its harness.
Review the declared operations. By default the delegated task can operate its
app. Owner requests use the app's existing side-chat session and history;
they do not create a Chat & Task entry. Credentials are scoped to each request's
turn and carried by a receipt key across continuations and answers. Queued
requests cannot overwrite each other's credentials or restrict ordinary chat.
Requests from other signed-in app users retain isolated context so they cannot
read the owner's chat or profile. The separate owner-tools
permission permits local file/shell work with CraftBot's privileges; member
requests never receive that host access. Source changes require a new review.
Another harness's bridge is not silently replaced.

Registry app views check the live task queue without remounting the app. A waiting
request without current consent opens CraftBot's existing permission-dialog design;
denying it keeps that request blocked, and a new request or source revision can ask
again. Approval is bound to the reviewed source fingerprint. Delivery failures are
shown beside the app and in Requests settings, without credentials or raw exception
text. Queue checks neither claim tasks nor start model calls.

Protocol 0.2 handoffs still require the framework-issued task credential. For a
registered local protocol 0.1 app with `authMode: none`, CraftBot can privately use
the framework's existing local credential reader after verifying live identity,
owner principal and the exact task claim. That credential stays in host memory;
the delegated turn can operate only that app and its assigned task. This fallback
never applies to multi-user apps or a protocol 0.2 task missing its credential.
No framework files are patched. The native integration tests support an additional
`CRAFTBOT_TEST_LEGACY_ADAPTER_ENTRY` pointing to an unchanged protocol 0.1 adapter
build to exercise permission, handoff, app reads and task completion end to end.

Creation, modification and conversion use the unchanged `framework-*` skills.
Independent verification runs the unchanged `framework-walk-verify` skill in a
fresh `framework_walk_verify` child subagent, linked to the app's build conversation.
`agent_app_framework_workflow(activity='verify')` waits for the child's evidence and
verdict; it does not create a separate chat. Browser/API requests enqueue that
action in the app conversation. CraftBot binds the verdict to the validation stamp
and dev instance, rejects stale passes, and cancels the child with its parent run.
The builder retains responsibility for repairs and promotion. A build/gate
pass alone is not delivery; the verified candidate must be promoted and served.
CraftBot registers its four native Agent-App actions from the running code tree
after loading custom actions from state. An older copy under `CRAFTBOT_HOME`
cannot override these host bindings; existing user files are preserved. Verify
actions require a calling conversation, so a missing caller fails explicitly
instead of requeueing the request into the same conversation.
App data operations use modular discovery through `a2app`, without injecting
private records into general chat context.

## Ownership and storage

| Component | Responsibility |
|---|---|
| `app/vendor/agent-app/` | Unmodified built dependency and source/hash provenance |
| `app/agent_app_package.py` | Verify/extract the packaged runtime |
| `app/agent_app/framework_cli.py` | Literal arguments, NDJSON output, subprocess lifetime and timeout |
| `framework.py`, `framework_commands.py` | Registry identity checks, native commands and host lifecycle serialization |
| `framework_host.py`, `framework_store.py` | Conversations, jobs, independent verdicts and presentation receipts |
| `framework_bridge.py` | Authenticated inbound task handoff, scoped authority, heartbeat, stop and restart accounting |
| `framework_migration.py` | Explicit data-preserving legacy migration and recovery |
| `framework_profile.py`, `framework_references.py` | Sanitized distribution sharing and registry-backed references |
| `agent-app/`, legacy manager/factory | Frozen compatibility for existing legacy apps and recovery only |

`A2APP_HOME` selects the same framework profile for the UI, actions and task
bridge; by default it is `~/.a2app`. `CRAFTBOT_AGENT_APP_PACKAGE` is an optional
development override; ordinary installations use the packaged runtime.
CraftBot's state directory holds `agent-app-host.sqlite3` (metadata and receipts,
never delegated bearer tokens), cached runtime files and migration recovery
artifacts. Agent-App remains authoritative for registration, processes and data.

The core agent owns the host, so a browser client is optional. Startup restores
explicit app startup preferences and unchanged task grants. Interrupted tasks
remain interrupted and are not replayed automatically. Delivery receipts do not
reconstruct authority after restart. Exactly-once external effects are not claimed.

## Existing apps and recovery

Existing legacy apps continue using their current runtime. CraftBot has no
migration screen; the unused migration component and stylesheet have been removed.
The migration backend, receipts and reference mappings remain in place pending a
separate cleanup. A future migration must preserve app behavior and data, verify
the replacement independently, and review task permissions before switching.

An interrupted transfer is a recovery item, never an automatic retry. Inspect the
journal's recovery path and both installations. Do not delete either data tree
to force a retry. External runtimes and changed schemas need an app-specific data
mapping; they retain the old backend until that mapping is verified. Old backup
archives stay intact; the replacement uses native backup controls and does not
inherit the old automatic schedule.

Profile sharing is distribution, not a full data backup: it exports sanitized app
packages, then separately installs them into the receiving profile. It does not
transfer users, records, runtime credentials, task grants or ownership. Keep
native app backups for data recovery.

## Maintaining the pin and bundled Kanban

Rebuild the framework distribution with `scripts/build_agent_app_framework.py`
from a clean, unmodified upstream checkout. Review the pin and hash, run the
native regression matrix and inspect changed upstream contracts. Do not patch
cached/vendor files or copy their behavior into the host to hide a dependency
limitation.

The original Kanban ZIP is retained as pinned source input. Only its app-owned
schema/domain code/UI is carried into a fresh unchanged PocketBase blueprint.
CraftBot-owned overlays adapt that app to canonical operations and tasks.

```powershell
$env:PYTHONPATH = (Get-Location).Path
# Use a disposable CRAFTBOT_HOME and A2APP_HOME for all candidate work.
python scripts/upgrade_bundled_kanban.py C:/scratch/new-kanban-candidate
# Through the existing CLI: dev --install, validate, independent walk-verify.
# The independent report must include verdict=pass and the current gateFingerprint.
python scripts/package_bundled_kanban.py C:/scratch/new-kanban-candidate C:/scratch/verification.json
```

The package helper invokes upstream export, normalizes ZIP framing/timestamps and
records provenance. The exporter removes data, credentials and dependencies.
The included verification ledger covers 56 executed non-destructive operations
and five destructive shape checks; destructive operations were not fired.
Fresh-install provisioning consumes the finished ZIP through an offline local
catalogue, with no conversion or agent run. Node/PocketBase dependencies may
still require network access on first installation.

## Validation

Settings cleanup on 2026-11-10: removed Advanced from registry app settings,
including missing-app cards. The owner-tools permission now lives under Requests.
Conversation shortcuts, manual verification buttons and raw capability/command
diagnostics are no longer shown; normal action errors remain inline. Existing
backend workflows and Agent-App are unchanged. All 19 focused settings/menu/
lifecycle browser tests passed, along with TypeScript and the production build.
The running Development Studio settings were checked after reloading the UI.

Session follow-up on 2026-11-10: registry side chats now match Kanban's dedicated
session behavior. Existing ordinary app conversations are reclassified in place
without clearing history; Main, unrelated chats, other apps and delegated tasks
cannot be adopted. The checks passed 133 backend tests (two optional install
tests skipped) and 42 browser tests, plus TypeScript, Ruff and the production
build. After restarting the live host, Development Studio retained its session
ID and four displayed messages, disappeared from Chat & Task, and remained
available beside its app. Main's eight messages matched the pre-restart digest.
Editor selections held only in an app's browser state are not automatically
included in a side-chat message.

Side-chat follow-up on 2026-11-10: extracted the existing Kanban app/chat split
into `AgentAppWorkspace` and reused it for registry app pages. The 50 relevant
browser regressions passed, including message routing, stale attachment replies,
attachment retry, desktop/mobile resizing, draft preservation and existing app
panel/lifecycle behavior. TypeScript and the production build passed. The running
Development Studio page was also checked for the restored chat and unsent-draft
preservation across collapse/reopen. No upstream Agent-App changes were needed.

Follow-up on 2026-11-10: sidebar app menus now contain Start/Stop and Delete only.
Settings remain under Settings → Agent App; visible registry refresh buttons were
removed. Delete now offers an explicit "Remove from list" fallback when the
unchanged CLI refuses a folder without ownership canon. That fallback uses
`forget` without `--force`, keeps files, and clears CraftBot's saved startup/task
permissions. Custom-toolkit apps with a recorded parent blueprint receive a fresh
data snapshot before upstream removal archives their backups. If that capture
fails, removal is aborted. The Advanced section present during that follow-up
was subsequently removed by the settings cleanup described above.

This follow-up passed 40 backend tests, 33 focused browser regressions and the
real-host settings walkthrough, plus TypeScript checking and a production build.
The live walkthrough checks normal removal, missing entries, the no-canon
fallback and preservation of the latest custom-toolkit data in the removal
archive. Test navigation now uses Settings → Agent App rather than a sidebar
settings shortcut. Existing user apps were not deleted during this check.
The sidebar menu portal also sits above the mobile drawer backdrop, with a
regression that opens and cancels Delete through the real narrow-screen layout.

Local results on 2026-11-09: the expanded backend run passed 673 tests with the
real adapter and bundled-board opt-ins enabled. Five additional production HTTP
routing regressions passed (678 backend checks in total). All 73 selected Playwright
regressions passed, as did the separate real-host settings walkthrough with its
public tunnel check enabled and the real bundled-board iframe walkthrough
(75 browser tests). TypeScript checking and the
production frontend build passed. The build retains its existing large-chunk
advisory. These are local Windows results, not remote CI results.

The expanded run found and fixed terminal app tasks leaving CraftBot runs marked
as working, completed tasks blocking later backups, the Create form's name and
access mode being left to model-generated scaffold arguments, native marketplace
toolkit refusals incorrectly launching conversion, and Windows file locks during
first-use package publication. The host now finishes a terminal task in its
normal post-turn path, and backup checks only active task authority. Form choices
bind to existing upstream scaffold flags. Package publication retries Windows
sharing/access locks for at most ten seconds without replacing an existing cache
or weakening its content checks. Account setup/invite links and one-time use are
also exercised against the real adapter, along with member-scoped data access,
write refusal, cancellation and normal terminal-turn bookkeeping.

CLI help no longer invokes CraftBot lifecycle hooks or requires promotion
verification, and stopping a development instance leaves the live bridge alone.
Native creation guidance points to CraftBot's request setting instead of offering
the upstream CLI's default external Pi harness. Production settings URLs now
reload correctly when their app-path query contains dots (for example `.a2app`);
missing asset files still return 404.
Apps without static request declarations show an explanation of runtime requests
instead of the misleading "View requests (0)" disclosure.

A manual walkthrough uploaded the bundled Kanban ZIP through CraftBot's Import
form, observed every native install stage, edited a card and checked persistence,
then assigned a real scoped task to CraftBot and approved its returned result.
The attached CraftBot conversation also created, read and edited a second card.
Folder, ZIP and local-catalogue installs use the real bundled CLI in isolated
tests; exported/imported packages exclude publisher data and credentials. A Git
source was cloned and inspected through CraftBot, but this is not a claim that
every remote Git host or private repository has been tested.

The live Create form produced a persistent Notes app, which completed independent
verification and was promoted to its live instance. That first creation exposed
the missing name binding; the disposable app retains its generated name, while
the fix was checked against real CLI scaffolding with both no-auth and multi-user
form choices. A foreign counter folder was
converted through the real Import form, independently verified, then modified
through its attached CraftBot conversation. The new Increase by 5 operation kept
the app's identity and existing live value. Direct UI checks covered persistence,
negative values, reset, keyboard use and a narrow viewport. CraftBot auto-launch
restarted that app with its saved value of 11; the temporary auto-launch setting
was then turned back off. The real bundled-board browser test creates a card
within CraftBot's iframe, switches conversations, stops/starts from the sidebar
and checks that the saved card survives.

After restarting CraftBot with the fixes, the live Notes UI submitted a summary
request through CraftBot's native bridge. A real model response returned to the
app, the host delivery became `completed`, and the chat stopped showing work in
progress. "Use as summary" saved the result across reload, and "Back up now"
immediately created a 71.8 KB snapshot. Reloading the production app-settings
deep link also succeeded. No external Pi process was needed for this round-trip.

The isolated real-host settings walkthrough covers backup/restore, repeated
exports, persisted schedule/log-cleanup preferences, LAN sharing of a stopped app,
link revocation, a real public tunnel, backup deletion, removing an installed app
and forgetting a missing app. Destructive cases use disposable fixture apps.
Scheduled-backup timing and retention are checked with controlled clocks; this
run did not wait a full day for a production schedule. Public access from a second
physical device and every external marketplace/Git provider remain unverified.

Use `requirements/test-agent-app-sync.txt` for the isolated host-test environment.
The CI workflow exercises the actual pinned adapter on Linux, macOS and Windows.
Set `CRAFTBOT_TEST_ADAPTER_ENTRY` to an unmodified built adapter-core entry point
to run the real task tests locally. Set `CRAFTBOT_TEST_BUNDLED_BOARD=1` to include
the real default-app installation/round-trip test (downloads dependencies).

Run `python -m pytest --import-mode=importlib` for the framework, package,
default-app, registry, reference and retained legacy regressions. The bundled
round-trip test uses an actual PocketBase app, bridge, scoped CLI and native
task runner, with a deterministic turn instead of a model response.

In `app/ui_layer/browser/frontend`, run `npx tsc --noEmit`, `npm run build` and
the framework, panel and references Playwright tests. Use `--workers=4` on
Windows. Static checks use Ruff on the changed Python files.

Current boundaries: separate sidecar View/control addresses and deployed remote
Views are not embedded; incompatible marketplace entries need conversion;
upstream stale-claim/cross-harness lifecycle races remain documented dependency
constraints. A local test pass is not a remote CI or release result. The original
rollout/deletion gates remain in `docs/plans/agent-app-sync.md`.

Registry settings reuse the original CraftBot card, backup and sharing controls.
CraftBot stores log-cleanup and backup-schedule preferences in its host receipts.
Backup/restore call the unchanged CLI, briefly stopping and restarting a running
app; active app tasks defer the action. For custom toolkits that are not installed,
CraftBot can resolve an explicit parent blueprint in `framework.lock.json` and
use the pinned framework's atomic backup helpers with that blueprint's data
contract. It never guesses the data directory or edits app/toolkit metadata.
Failed restarts retain a recovery receipt.
Retention applies only to CraftBot's scheduled snapshots; manual, external and
upstream safety snapshots are preserved. Housekeeping imports the pinned
framework's existing backup-list and locking functions without modifying it.

LAN/public sharing uses a CraftBot gateway and the existing tunnel transport.
The gateway requires a channel-specific link/session, validates browser origins
and upstream identity, and never injects an admin credential. Multi-user apps
retain account sign-in and permissions. Stop/close/shutdown revoke the channel,
including open WebSockets; links remain valid across a scheduled backup pause.
Sharing writes no grant files into an upstream project. Creating a link starts a
stopped app, and sharing remains usable if backup metadata cannot load. Missing
app folders can be removed from the list using upstream `forget`; available apps
still use `remove` with its archival safeguards. Every export has a fresh path.

`framework-settings-live.test.ts` drives the real host and bundled CLI through
the settings UI using disposable app data. It checks backup/restore, repeated
exports, LAN links, revocation and both removal paths. Local verification also
enabled its optional real public tunnel check; CI leaves that network-dependent
check off. No user app is publicly exposed by these tests.
