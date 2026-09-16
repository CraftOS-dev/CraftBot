# Web UI Data Freshness Plan

> **Status:** Proposed — awaiting sign-off on the decisions in §9
> **Date:** 2026-09-15
> **Scope:** `app/ui_layer/browser/frontend` (React + Redux Toolkit) and the backend that feeds it (`app/ui_layer/**`, `app/agent_app/**`, `agent_core/**`, `app/proactive`, `app/scheduler`, `craftos_integrations`)
> **Problem statement:** The web UI regularly shows stale data until the page is refreshed. Example: deleting an Agent App from the sidebar while Settings is open leaves the app listed in Settings → Agent App.

File:line references were taken during the audit on 2026-09-15 and will drift; search for the quoted symbol if a line no longer matches.

---

## 1. Summary

This isn't one bug. It's a missing piece of architecture, and it shows up in 40+ places.

**The model we are already committed to** (Redux migration, decision #4) is "cache everything by default, invalidate on server push". The caching half exists: `hasLoaded` guards appear 55 times across 8 Settings tabs, plus module and component caches elsewhere. The invalidation half doesn't:

1. **The backend has no "something changed" signal.** `UIEventType` (`app/ui_layer/events/event_types.py:11-59`) only covers chat, actions, run state, footage, navigation and onboarding. Many mutation replies carry only `{success}` or a single item, and changes made by the agent, the scheduler, watchdogs, integrations or file edits push nothing at all.
2. **The frontend has no always-on invalidation path.** Many copies of server data refresh only through listeners inside a component (`useSettingsWebSocket().onMessage`), which exist only while that component is mounted. Settings renders only the active tab, so every other tab is deaf.
3. **The transport silently gives up.** `SocketClient` stops reconnecting forever after 10 attempts, about 75 s (`store/socket/SocketClient.ts:41,56,188-192`). A backend restart or update leaves the whole UI frozen until a manual refresh.
4. **Several copies are simply wrong on arrival.** Broadcast replies get applied to views they weren't meant for, and cached values take precedence over live pushes.

A browser refresh "fixes" everything because it rebuilds all state from the connect snapshot (`browser_adapter.py:1142-1170`, `_get_initial_state` at `:9452`).

**The fix is one small mechanism on each side, then systematic wiring:**

- **Backend:** a single `notify_resource_changed(resource, ids)` primitive, called from the **domain layer** (managers, config reloads, file watchers), not the WebSocket handlers. It is coalesced and thread-safe, and is broadcast as one message type: `resource_changed`.
- **Frontend:** a `ResourceSync` layer. Every server-backed resource declares how to fetch itself; components use `useResource(...)` instead of hand-rolled fetch-once effects; one middleware turns `resource_changed` (and reconnects) into refetches for the data the user is currently looking at.
- **Transport:** never give up reconnecting, and don't drop user actions during a blip.
- **Plus a list of targeted correctness fixes** (§6) that invalidation alone doesn't solve.

---

## 2. How the system works today (relevant facts)

| Fact | Evidence |
|---|---|
| One WebSocket shared by the Redux middleware, `WebSocketContext` and `useSettingsWebSocket` | `store/socket/socketInstance.ts:9-15`, `useSettingsWebSocket.ts:31-38` |
| Almost every backend reply goes to **all** clients via `_broadcast`; WhatsApp QR/status and a few snapshot sends are the exceptions | `browser_adapter.py:8277-8296` (`_broadcast`), `:8180-8189` (`_send_to`) |
| Replies aren't correlated with requests: any tab's `*_get`/`*_list` reply lands in every tab's slice | `messageRegistry.ts:29-41`, `WorkspaceContext.tsx:306` |
| Slice handlers (`register(type, …)`) are always on; component `onMessage` listeners only exist while mounted | `messageRegistry.ts:20-27`; e.g. `AgentAppSettings.tsx:57-69` |
| Settings renders only the active tab | `SettingsPage.tsx` `switch (activeCategory)` |
| On reconnect only `agent_app_list` is re-requested (plus model settings on Model tab mount); no `hasLoaded` flag is ever reset | `WebSocketContext.tsx:352-356,371-374` |
| The only existing backend push paths: event-stream polling for chat/actions/status, the Agent App callback registry, `notify_session_updated`, the skills config watcher, dashboard metrics polling | `ui_controller.py:424-471,301-312`; `app/agent_app/broadcast.py:45-81`; `agent_base.py:3453-3472`; `browser_adapter.py:8320-8338` |
| Infrastructure we can reuse: `EventBus` (`app/ui_layer/events/event_bus.py`, exposed as `STATE.event_bus`); `ConfigWatcher` (`agent_core/core/impl/config/watcher.py`, uses `watchdog`, already a dependency); `SettingsManager.register_reload_callback`; `SessionManager` hooks (`agent_core/core/impl/session/manager.py:188-225`); the Agent App broadcast loop-capture pattern (`app/agent_app/broadcast.py:140-200`) | — |

---

## 3. Issue inventory

Severity: **H** = common and visible, **M** = visible in specific flows, **L** = rare or cosmetic.
The *Fix* column points to the workstream in §5–§6.

### 3.1 Transport and connection (T)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| T1 | After a backend restart or update longer than ~75 s, nothing updates anywhere until refresh; "Working…" indicators stick | `SocketClient` sets `giveUp=true` after 10 attempts; nothing resets it | `SocketClient.ts:41,56,188-192` | WS-0.1 | H |
| T2 | Clicks during a reconnect (delete app, theme change, subscribe to dashboard…) silently do nothing | Many `WebSocketContext` senders check `client.isConnected` and return instead of queuing | `WebSocketContext.tsx:553-738` (≈20 guards), `:718-725` (delete app) | WS-0.2 | M |
| T3 | After reconnect, every cached list is whatever it was before the outage | No invalidation on reconnect; `hasLoaded` never resets | `WebSocketContext.tsx:352-374` | WS-2.4 | H |
| T4 | Busy dots and run state stay stale after a disconnect | Run state isn't reconciled on reconnect | `agentSlice.ts:120-143` | WS-0.3 | M |
| T5 | `connectionSlice.reconnectAttempt` never dispatched; dead `version` copy in context | Leftover migration state | `connectionSlice`, `WebSocketContext.tsx:126,230` | WS-0.1 | L |

### 3.2 Agent Apps (A)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| A1 | **(Reported)** App deleted from sidebar, the Agent App page or another tab still listed in Settings → Agent App | Settings list is a second copy (`agentAppSettingsSlice`) that only listens for `agent_app_settings_get` and backup events; the refetch-on-delete listener lives in the component; the `hasLoaded` guard skips refetch on return; delete replies `{success, projectId}` only | `agentAppSettingsSlice.ts:141-192`, `AgentAppSettings.tsx:52-69`, `browser_adapter.py:3201-3247` | WS-1, WS-2 | H |
| A2 | Apps created, imported or installed by the agent never appear in Settings, even with the tab open | Settings slice ignores `agent_app_create` | `browser_adapter.py:3885-3900`, `agent_app_actions.py:260,2542,2670,2754,2893` | WS-2 (resource `agent_apps`) | H |
| A3 | App status in Settings (running, stopped, error) never changes | Settings slice ignores `agent_app_ready/status/error` | as A1 | WS-2 | H |
| A4 | App tab keeps showing "running", a spinner or a dead iframe after a background crash, watchdog escalation, failed restart, stale-status stop, auto-launch error or dispatch error | `update_project_status`, `stop_project` and the watchdog paths change status without notifying | `agent_app/manager.py:3809-3817,4343-4402,481-515,801-810,1739-1742,4127-4158,5004-5015,3957-3959`; `agent_app_actions.py:1443-1471` | WS-3.1 | H |
| A5 | Leftover backups of a deleted app never appear until refresh | Delete doesn't re-push settings or orphans | `browser_adapter.py:3201-3247` vs `:7844` | WS-2 (resource `agent_app_backups`) | M |
| A6 | Backup list and "last backup" stale after scheduled, pre-promote or pre-delete backups, and after "Back up now" | No push from backup jobs; the slice comment says the card refetches but it doesn't | `manager.py:556-601,650-671,4439-4459`; `agentAppSettingsSlice.ts:164-171` | WS-3.1 | M |
| A7 | Trigger consent approved by the agent isn't reflected in app settings | Only the UI path replies | `agent_app_actions.py:2296-2360` → `factory/host_craftbot.py:257` | WS-3.1 | L |
| A8 | Theme picked in one tab or browser never reaches others; a browser that ever picked a theme ignores server changes | `agent_app_theme_update` has no reply; the page prefers localStorage over `project.uiTheme` | `browser_adapter.py:2934-2944`; `AgentAppPage.tsx:37-64,128-143`; `agentAppSlice.ts:258-261` | WS-4.8 | M |
| A9 | Renames or icon changes broadcast for a **running** app are ignored until the next full list | `addProject` / `applyStatus` never overwrite a running project | `agentAppSlice.ts:75,86` | WS-4.9 | L |
| A10 | Construction dock todos and per-app state empty after refresh or reconnect mid-build | Only build events are replayed on `agent_app_list` | `browser_adapter.py:3104-3118`; `agentAppSlice.ts:311-328` | WS-4.10 | M |
| A11 | Marketplace catalog never refreshes for the app lifetime | Modal stays mounted in NavBar; fetches only if `apps` is empty | `CreateAgentAppModal.tsx:55,138-149` | WS-2 (static resource) | L |

### 3.3 Settings: General, agent files, model (S)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| S1 | USER.md / AGENT.md / SOUL.md look **reverted** after save → switch tab → return | `agent_file_write` isn't registered in `generalSettingsSlice`; reply has no content; the effect re-seeds the draft from the stale slice copy | `generalSettingsSlice.ts:80-94`; `GeneralSettings.tsx:134-151,279-303`; `browser_adapter.py:4267` | WS-2 (resource `agent_files`) + WS-4.1 | H |
| S2 | Agent edits to USER.md, AGENT.md or SOUL.md never appear | No watcher or notify | `write_file` / `stream_edit` actions; `app/onboarding/profile_writer.py` | WS-3.7 | M |
| S3 | Renaming the agent doesn't update the sidebar or chat until reload | `settings_update` has no slice listener; `agentSlice.name` only set on `init` / `onboarding_complete` | `agentSlice.ts:107-121,185-191`; `GeneralSettings.tsx:361-385` | WS-4.2 | M |
| S4 | Theme dropdown flips to "Dark" and the form looks unsaved every time General opens (Light or System saved) | Backend `settings_get` hard-codes `"theme": "dark"`; the component writes it into the draft | `browser_adapter.py:4166`; `GeneralSettings.tsx` `settings_get` handler | WS-4.3 | H |
| S5 | Another tab opening General overwrites this tab's unsaved name, language or theme | Broadcast `settings_get` applied to local drafts unconditionally | `GeneralSettings.tsx` `settings_get` handler | WS-4.1 | M |
| S6 | Saving model settings in one tab wipes unsaved model drafts in every other tab (and shows a toast there) | `model_settings_update` success handler resets drafts without checking origin | `ModelSettings.tsx:197-224` | WS-4.1 | M |
| S7 | Changing the provider dropdown mutates shared slice state before Save | Draft written to the slice | `ModelSettings.tsx:106,438-457` | WS-4.1 | L |
| S8 | `settings.json` edited by the agent reloads the backend but the Settings page shows old values | `SettingsManager` reload callbacks are backend-only | `agent_base.py:3386-3437` | WS-3.8 | M |
| S9 | Subscription token revoked in the background → Model settings still shows connected | No push | `craftos_integrations/llm_oauth/copilot.py:122` | WS-3.8 | L |
| S10 | "Update available" stays true after updating and reconnecting | Update check runs once per page load | `GeneralSettings.tsx:337`; `generalSettingsSlice` | WS-4.11 | L |

### 3.4 Skills, commands, MCP, integrations (K)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| K1 | Skill created by "Create skill from session" or other agent workflows missing until Reload or refresh | `SkillManager.reload()` without a target skill pushes nothing; `skill_list` only arrives via the `skills_config.json` watcher | `agent_base.py:1551-1580,3453-3472`; `skill/manager.py:274-297` | WS-3.2 | M |
| K2 | Slash-command list and `skill_meta` (reserved names) never refresh | `command_list` only on request, fetched once; `skill_meta` only on connect | `SlashCommandAutocomplete.tsx:56-60`; `browser_adapter.py:1148-1153,6551-6583` | WS-2 + WS-3.2 | M |
| K3 | SKILL.md files added or edited directly aren't picked up at all | `ConfigWatcher` only watches the JSON configs | `agent_base.py:3435-3478` | WS-3.2 (optional) | L |
| K4 | MCP servers changed by the agent (`mcp_config.json`) or `/mcp add/remove/enable` in chat don't update Settings → MCP | Reload pushes no `mcp_list`; the watcher is registered only if the file existed at startup | `agent_base.py:3439-3446`; `ui_layer/commands/builtin/mcp.py:122-203` | WS-3.3 | M |
| K5 | MCP tab fetches the list twice after every mutation; the Reload toast runs on a timer, not on the reply | Component sends `mcp_list` although the backend already broadcasts it | `MCPSettings.tsx:88,101,116,154-160` | WS-5 | L |
| K6 | Integrations connected, disconnected or reconfigured by the agent don't show in Settings | `integration_management.py` actions don't notify | `app/data/action/integrations/integration_management.py:292-389,675-681,781-808` | WS-3.4 | H |
| K7 | Listener paused after crash-loops, or WhatsApp needing re-link, never surfaces | State is only readable by pulling | `craftos_integrations/core/listeners.py:123,136-141`; `providers/whatsapp_web/_session.py:231-241,375-429` | WS-3.4 | M |
| K8 | Integrations "Manage" modal shows connected after another tab disconnects; any tab's disconnect closes the modal and shows a toast everywhere | Modal holds a copy (`managingIntegration`); disconnect handler not scoped to the originating request | `IntegrationsSettings.tsx:353,368,386,560-571,601-612` | WS-4.4 | M |

### 3.5 Proactive tasks, scheduler, memory (P, M)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| P1 | Recurring tasks added, updated or removed by the agent missing from Settings → Proactive | Actions don't notify; handlers reply `{taskId, success}`; refetch listener only while mounted | `app/data/action/recurring_*.py` → `app/proactive/manager.py:140-268`; `ProactiveSettings.tsx:319-348` | WS-2, WS-3.5 | H |
| P2 | Run counts, last or next run and outcome history never update | Scheduler fires and heartbeat outcomes don't notify | `app/scheduler/manager.py:546-680`; `app/proactive/manager.py:282-310` | WS-3.5 | M |
| P3 | Editing PROACTIVE.md directly isn't reflected **even after refresh** | Backend `ProactiveManager` caches `_data` with no watcher; the UI reads the cache | `app/proactive/manager.py:36,100-105`; `ui_layer/settings/proactive_settings.py:239` | WS-3.5 | M |
| P4 | Scheduled tasks created, removed or toggled by the agent don't update the scheduler view | Config saved, reloaded by the watcher, no push | `schedule_task*.py`; `agent_base.py:3699` | WS-3.5 | M |
| M1 | Memory written by the agent (memory processing, entity judge, file watcher reindex) never reaches an open Memory page or Settings → Memory | No notify anywhere outside UI handlers | `agent_base.py:1400-1413,776-800,412-417`; `memory_file_watcher.py:150,196-237`; `app/utils/file_index.py:823` | WS-3.6 | H |
| M2 | Memory page Refresh button reloads only the graph; items and indexed files stay stale | Button sends `memory_graph_get` only | `MemoryPage.tsx` refresh button (`send('memory_graph_get')`) | WS-4.5 | M |
| M3 | Memory schedule (daily time, threshold) changed elsewhere isn't shown until remount; each open tab's 4 s poll is broadcast to every client | Local-only state adopted on the first reply; polling via broadcast | `MemorySettings.tsx:38-42,89-98,180-184` | WS-2 + WS-4.1 | L |
| M4 | `memory_reset` isn't handled by the slice (only by the mounted Memory page) | Missing registration | `memorySettingsSlice.ts:158-218` | WS-2 | L |

### 3.6 Workspace (W)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| W1 | Files written or deleted by the agent appear only after the 30 s poll, or never if you're elsewhere | No workspace watcher; `file_list` only on request | `WorkspacePage.tsx:240-253`; `browser_adapter.py:8375-8440` | WS-3.9 | H |
| W2 | Open file preview never re-reads after the agent edits the file | Content read only when the selection changes | `WorkspacePage.tsx:220-230` | WS-3.9 + WS-4.6 | M |
| W3 | **Cross-tab overwrite:** tab B navigating or reading replaces tab A's file listing or preview under A's folder label; `applyCreate` appends into whatever folder A shows | Broadcast `file_*` replies applied without checking `directory` / `path` | `workspaceSlice.ts:97-155` | WS-4.6 | H |
| W4 | **Paste into another folder** replaces the current listing with the destination's contents and hangs 30 s before erroring | `listDirectory` stores its pending promise under `file_list_<ts>` but responses are matched by `msg.type`, so it never resolves; the slice applies the reply to the current view | `WorkspaceContext.tsx:210-215` vs `:304-311` | WS-4.6 | H |
| W5 | Workspace root listing isn't reloaded after reconnect | First navigation runs once per app lifetime | `WorkspaceContext.tsx:315-320` | WS-2.4 | L |

### 3.7 Dashboard, chat, sessions (D, C)

| ID | Symptom | Root cause | Evidence | Fix | Sev |
|---|---|---|---|---|---|
| D1 | Task stats, token usage and usage patterns **don't tick live** even with the dashboard open; 1h/1d/1w/1m frozen for the page lifetime | `filteredCache` per period is never invalidated, and widgets read `filteredData ?? dashboardMetrics`, so the cached value beats the live push | `widgets/shared.tsx` `useMetricsPeriod`; `TaskStatsWidget.tsx:14-17`; `TokenUsageWidget.tsx:12-14`; `UsagePatternsWidget.tsx:12-13`; `dashboardSlice.ts:46-57` | WS-4.7 | H |
| C1 | Sidebar order doesn't follow activity from triggers, schedules or integrations | `last_active_at` bumped without notify | `session/manager.py:479-498` | WS-3.10 | M |
| C2 | Sessions created or deleted outside UI handlers (project sessions, reset internals) don't appear or disappear in the sidebar | No `session_created` / `session_deleted` from those paths | `agent_app/manager.py:360-407,4503-4514`; `agent_base.py:2693-2709` | WS-3.10 | M |
| C3 | Unread dots don't sync across tabs, and one tab's write wipes another's entries | `lastSeenMessageIdBySession` read once at import, written whole-map, no `storage` listener | `WebSocketContext.tsx:99-119,232,499-508` | WS-4.12 | M |
| C4 | Playbook catalog cached in three places for the app lifetime | Each copy fetches only if empty | `Chat.tsx:408,679-682`; `PlaybookModal.tsx:57,68-74`; `TopBar.tsx:59` | WS-2 (static resource) | L |
| C5 | Activity blocks for sessions older than the in-memory snapshot may never load | No activity replay with `chat_history` (unverified) | `activitySlice.ts:114-153` | Investigate in WS-4 | L |

### 3.8 Already fine (no action)

- **Broadcasts full lists to every tab:** MCP (`mcp_list`), skills (`skill_list`) and integrations (`integration_list`) after UI mutations, plus `scheduler_config_update` and `memory_index_file_*`.
- **Pushed live:** session titles (`session_updated`), chat messages and activity while connected, the profile picture (mtime-busted URL), and dashboard counts coming from the live push.
- **Refetched on every mount:** model settings (`ModelSettings.tsx:365-374`).

---

## 4. Target architecture

### 4.1 Principles

1. **The server is the source of truth; every client copy is a cache.** A cache must know how to refresh itself.
2. **Invalidate, don't replicate.** The backend says *what* changed (`resource`, optional `ids`), and clients refetch what they display. The backend never needs to know view shapes, and one message type covers every domain.
3. **Notify from the domain layer, not the transport handler.** A change is a change whether the UI, the agent, a scheduler, a watchdog or another platform made it. Hooking managers, reload callbacks and file watchers covers all of them at once.
4. **Always-on subscriptions, not component listeners.** Whether data refreshes must never depend on which Settings tab happens to be mounted.
5. **Drafts are not caches.** Unsaved form input is protected from incoming server updates (§4.4).
6. **Additive protocol.** Existing message types keep working; each phase is shippable on its own.

### 4.2 Backend: `ResourceChangeNotifier`

New module `app/ui_layer/events/resource_changes.py`:

```python
class Resource(str, Enum):
    AGENT_APPS = "agent_apps"
    AGENT_APP_BACKUPS = "agent_app_backups"
    SESSIONS = "sessions"
    SKILLS = "skills"                 # skill list + skill_meta + command list
    MCP_SERVERS = "mcp_servers"
    INTEGRATIONS = "integrations"
    PROACTIVE = "proactive"           # tasks, planner output, mode
    SCHEDULER = "scheduler"           # scheduler config, run status, memory schedule
    MEMORY = "memory"                 # items, graph, indexed files, stats
    WORKSPACE_FILES = "workspace_files"   # ids = directory paths
    AGENT_FILES = "agent_files"           # ids = USER.md / AGENT.md / SOUL.md …
    GENERAL_SETTINGS = "general_settings"
    MODEL_SETTINGS = "model_settings"

def notify_resource_changed(resource: Resource, ids: Iterable[str] = (), reason: str = "") -> None: ...
```

Behaviour:
- **Thread-safe.** Callable from worker threads (watchdog observers, agent action threads, Agent App worker threads). Uses the same loop-capture approach as `app/agent_app/broadcast.py:140-200`.
- **Coalesced.** Changes per resource are merged over a short window (default 200 ms, ids unioned; if any change for a resource has no ids, the merged event means "everything"). A memory processing run that touches 50 items produces one event.
- **Published** as a new `UIEventType.RESOURCE_CHANGED` on the existing `EventBus`. `BrowserAdapter` subscribes once and broadcasts `{ "type": "resource_changed", "data": { "resource": "...", "ids": [...] } }`. Other adapters (TUI) can subscribe later.
- **`reason`** is for logging and debugging only; clients don't branch on it.
- **Wire message documented** in one place (module docstring) so frontend and backend share the vocabulary.

Adapter handlers keep their current replies, so older clients still work. They don't need to add ad-hoc refetch broadcasts any more, because the domain call they make already notifies.

### 4.3 Frontend: `ResourceSync`

New folder `src/store/resources/`, sibling to `store/socket/` and `store/uiState/`:

```ts
// defineResource.ts
interface ResourceDescriptor {
  name: ResourceName              // mirrors the backend Resource enum
  /** Sends the request(s) that (re)load this resource; ids narrow it when supported. */
  request(send: SocketSend, ids?: string[]): void
  /** 'visible' (default): refetch only while a component uses it, else mark stale.
   *  'always': refetch whenever invalidated (e.g. the sidebar's sessions and agent apps). */
  liveness?: 'visible' | 'always'
}

// catalog.ts — every server-backed resource and how it loads, in one place
export const RESOURCES = { agentAppsList, agentAppSettings, agentAppBackups, sessions,
  skills, commands, skillMeta, mcpServers, integrations, proactiveTasks, proactiveMode,
  schedulerConfig, memoryItems, memoryGraph, memoryIndexedFiles, memorySchedule,
  workspaceListing, workspaceOpenFile, agentFiles, generalSettings, modelSettings,
  playbooks, marketplace } as const
```

- **`ResourceSync` class (singleton, like `SocketClient`).** It tracks per-descriptor subscriber counts and a `stale` flag, and runs coalesced refetches (a microtask batch). It holds no Redux state; data stays in the existing slices.
- **`useResource(descriptor, ids?)` hook.** It replaces every hand-rolled `useEffect(() => { if (!hasLoaded) send(...) })`.
  - On mount it subscribes, and requests if never loaded or stale.
  - On unmount it unsubscribes.
- **Invalidation middleware.**
  - On `resource_changed`: for every descriptor mapped to that backend resource, refetch now if it has subscribers (or `liveness: 'always'`), otherwise mark it stale.
  - On socket **re-open after a close**: invalidate everything, since events may have been missed or the server restarted.
  - On `init` with a changed `version`: also invalidate everything, and reset the update check.
- **One backend resource can map to several descriptors.** For example, `agent_apps` feeds both the sidebar list (`agent_app_list`, always) and the Settings list (`agent_app_settings_get`, visible). That duplication is intentional for now (§8). It stops mattering because both copies are invalidated together.
- **Slices stay the owners of data** (Redux migration decisions #1–#4 unchanged). `hasLoaded` flags stay as the "has data" signal; `ResourceSync` owns freshness.

### 4.4 Drafts vs server values: `useServerDraft`

Several stale-data fixes make server updates arrive more often. That would make the existing "incoming update clobbers unsaved edits" bugs (S1, S5, S6, M3) worse, so they're fixed with one reusable hook:

```ts
const draft = useServerDraft(serverValue)   // draft.value, draft.set, draft.isDirty,
                                            // draft.remoteChanged, draft.reset(), draft.acceptRemote()
```

- **Not dirty:** follows `serverValue` automatically.
- **Dirty and the server value changes:** keeps the user's edit and sets `remoteChanged`, so the form can show "Changed elsewhere — reload / keep mine".
- **Save:** on success the draft resets to the saved value, and only in the tab that saved.

Used by: General (agent name, language), agent `.md` editors, Model forms, Memory schedule, Proactive task edit modal, integration config.

### 4.5 Request correlation (where replies must be scoped)

Broadcast replies are fine for data, but wrong for **promise resolution and per-view results** (W3, W4, K8, S6). Add an optional `requestId`:
- the client sends it
- the backend echoes it in the reply
- `WorkspaceContext`'s pending map and "result" handlers (toasts, modal close, draft reset) match on it

Slice data appliers stay request-agnostic, but check `directory` / `path` before applying list or preview replies.

---

## 5. Workstreams (implementation order)

Each workstream is independently shippable. The effort estimates (S ≈ ≤½ day, M ≈ 1–2 days, L ≈ 3+ days) are for an agent working with review.

### WS-0 — Transport reliability (frontend only) · S · fixes T1, T2, T4, T5

1. **WS-0.1 `SocketClient`.**
   - Remove give-up. Keep the capped backoff (≤30 s) forever.
   - Reset the backoff and attempt immediately on `online` and on `visibilitychange → visible`.
   - Dispatch `reconnectAttempt` to `connectionSlice`, so a small "Reconnecting…" indicator can be shown.
   - Delete the dead `version` state in `WebSocketContext`.
2. **WS-0.2 Queue, don't drop.**
   - Route all `WebSocketContext` senders through `client.send` (the outbox already exists).
   - Give outbox entries a max age (default 60 s) so a stale destructive action isn't replayed long after the user gave up. Expired entries surface a toast ("Couldn't reach CraftBot — action not sent").
3. **WS-0.3 Run state.** On `init`, replace `runStateBySession` wholesale (not merge) so sessions that finished during an outage stop showing busy.

**Acceptance:** stop the backend for 3 minutes, start it again, and the UI recovers without a refresh. A click made during a 5-second blip executes after reconnect.

### WS-1 — Invalidation infrastructure + Agent Apps pilot · M · fixes A1 end-to-end

1. Backend `resource_changes.py` (§4.2), `UIEventType.RESOURCE_CHANGED`, and the `BrowserAdapter` subscription and broadcast.
2. Frontend `store/resources/` (§4.3): `defineResource`, `ResourceSync`, `useResource`, the invalidation middleware, and reconnect invalidation.
3. **Pilot resource `agent_apps`:**
   - **Backend:** emit from `AgentAppManager` at the points where the project set or status changes (`_save_projects` / `update_project_status`, `stop_project`, `delete_project`, launch success and failure, create/import).
   - **Frontend:** descriptors `agentAppsList` (always) and `agentAppSettings` (visible). `AgentAppSettings.tsx` switches to `useResource` and its component-level launch/stop/delete listeners are deleted.
4. Backend unit tests for coalescing and thread-safety, plus a Playwright scenario for A1–A3 (§7).

**Acceptance:** A1, A2, A3 and A4 (for the paths wired here) pass in the two-tab harness.

### WS-2 — Migrate every Settings tab and cached view to `useResource` · M · fixes T3, A5, A11, S1(part), K2(part), P1(part), M3(part), M4, W5, C4

For each descriptor in the catalog:
- Replace the component's fetch-once effect with `useResource`.
- Move any refetch-on-message logic from component `onMessage` into the resource mapping.
- Map it to its backend resource.

Order: Proactive, Memory (Settings + page), General / agent files, Skills + commands + skill meta, MCP, Integrations, Model, Workspace, playbooks and marketplace (static: refresh only on reconnect or version change).

**Backend:** add emits in the existing UI handlers' domain calls for resources that currently reply `{success}` only: proactive task add/update/remove/reset, memory reset/remove/schedule, `agent_file_write`, `agent_app_project_setting_update`, backups. Add `skill_meta_get` and make `command_list` re-sendable, so `skills` invalidation can refresh all three.

**Acceptance:** for every tab, "mutate from tab A while tab B sits on a *different* Settings tab, then open the tab in B" shows fresh data without refresh.

### WS-3 — Agent- and background-initiated changes (backend) · L · fixes A4, A6, A7, S2, S8, S9, K1, K3, K4, K6, K7, P1–P4, M1, W1, W2, C1, C2

Emit `notify_resource_changed` at the domain layer:

| Sub | Resource | Emit points (domain layer) |
|---|---|---|
| WS-3.1 | `agent_apps`, `agent_app_backups` | Every status write in `agent_app/manager.py` (`update_project_status`, watchdog retry/escalation, stale-status detection, auto-launch, dispatch failure, launch failure), `stop_project`, `delete_project`, backup jobs, trigger consent (`factory/host_craftbot.py:257`) |
| WS-3.2 | `skills` | `SkillManager.reload()` (always, not only with a target), `enable_skill` / `disable_skill`, command registry changes. Optional: `ConfigWatcher` on the skills directories for SKILL.md edits (debounced) |
| WS-3.3 | `mcp_servers` | MCP client/config reload (`agent_base.py:3439-3446`), the `/mcp` command path. Register the config watch even when the file doesn't exist yet |
| WS-3.4 | `integrations` | Integration system connect/disconnect/account changes (`craftos_integrations/core/system.py:150-221`), listener pause/resume (`listeners.py:123-141`), WhatsApp session state transitions (`_session.py:375-429`) |
| WS-3.5 | `proactive`, `scheduler` | `ProactiveManager` save paths (`manager.py:140-268`), heartbeat/planner output (`:282-310`); a watcher on PROACTIVE.md that **invalidates the backend cache** then notifies (fixes P3); `SchedulerManager` add/remove/toggle and fire (`scheduler/manager.py:115-262,546-680`) |
| WS-3.6 | `memory` | Memory item store writes, memory processing completion (`agent_base.py:1400-1413`), entity judge (`:776-800`), `MemoryFileWatcher` reindex (`memory_file_watcher.py:196-237`), file index updates (`file_index.py:823`) |
| WS-3.7 | `agent_files` | A `ConfigWatcher`-style watch on USER.md / AGENT.md / SOUL.md (ids = filename), plus `agent_file_write` / `agent_file_restore` |
| WS-3.8 | `general_settings`, `model_settings` | `SettingsManager.register_reload_callback` (fires on `settings.json` change), subscription status changes (`llm_oauth`) |
| WS-3.9 | `workspace_files` | A `watchdog` recursive observer on `AGENT_WORKSPACE_ROOT`: debounced (500 ms), ids = changed parent directories, ignore patterns (`.git`, `node_modules`, `__pycache__`, the Agent App `pb_data`). Also emit from the `file_*` handlers so the UI's own actions don't wait on the watcher |
| WS-3.10 | `sessions` | `SessionManager` create/delete/touch (`session/manager.py:131-200,216-225,479-498`). Throttle touch-driven events (sidebar order only needs ~2 s resolution) |

**Acceptance:** the scenario matrix in §7.2 passes. Driving the agent via chat ("add a recurring task…", "remember that…", "write a file…", "stop app X") updates the open views within ~1 s.

### WS-4 — Targeted correctness fixes · M · (not solved by invalidation)

| Sub | Issue(s) | Fix |
|---|---|---|
| WS-4.1 | S1, S5, S6, S7, M3 | Introduce `useServerDraft` (§4.4); adopt in General, agent file editors, Model, Memory schedule, Proactive modal. Model provider dropdown becomes a draft (not written to the slice before Save) |
| WS-4.2 | S3 | `agentSlice` registers `settings_update` (success → set name); General saves update the slice |
| WS-4.3 | S4 | Remove `theme` from `settings_get` (theme is client-side persisted UI state); General stops reading theme from the server |
| WS-4.4 | K8 | Manage modal reads the integration from the slice by id (no copy); disconnect result toast and modal close scoped by `requestId` |
| WS-4.5 | M2 | Memory Refresh button refetches the whole `memory` resource |
| WS-4.6 | W2, W3, W4 | `requestId` correlation in `WorkspaceContext` + backend `file_*` echo; slice appliers ignore `file_list` for a directory other than `currentDirectory` and `file_read` for a path other than the open file; `listDirectory` resolves correctly and no longer mutates the visible listing; open file re-reads when `workspace_files` invalidation includes its directory (skip while the preview has unsaved edits, if any) |
| WS-4.7 | D1 | Period `total` reads the live `dashboard_metrics` directly; other periods' cache entries are stamped and re-requested when older than 10 s while the dashboard is subscribed |
| WS-4.8 | A8 | Backend persists and broadcasts `agent_app_theme_update` (projectId + uiTheme) and notifies `agent_apps`; the page treats the server theme as authoritative and localStorage as an initial-paint cache only |
| WS-4.9 | A9 | `addProject` / `applyStatus` always patch non-status fields; only the status transition rules protect running apps |
| WS-4.10 | A10 | `agent_app_list` replay includes current todos and per-app state alongside build events |
| WS-4.11 | S10 | On `init` with a different version: `resetUpdateCheck` (also covered by §4.3 version invalidation) |
| WS-4.12 | C3 | Move `lastSeenMessageIdBySession` into persisted UI state (`UI_STATE.chat.lastSeenMessageId(sessionId)`, lifetime `preference`). The existing uiState middleware already syncs across tabs, and per-key storage removes the whole-map clobber. Migrate the legacy key via `legacyMigration.ts` |

### WS-5 — Cleanup · S

- Delete component-level refetch listeners and duplicate refetch sends: MCP double fetch (K5), `AgentAppSettings` launch/stop/delete listeners, Proactive add/update/remove listeners, `MemoryPage` item listeners.
- Remove the unused `reconnectAttempt` / `version` leftovers.
- Document the pattern in the resource catalog header, as `store/uiState/catalog.ts` does: how to add a resource, when to use `always` vs `visible`, and where the backend emits.
- Update the Redux migration memo: `useSettingsWebSocket` consumers now load via `useResource`, which moves phase 6 forward.

---

## 6. Per-resource wiring checklist

The single table implementers work through. A resource is **done** when all four columns are ✅.

| Resource | Backend emit (UI handlers) | Backend emit (agent/background) | Frontend descriptor(s) + `useResource` adoption | Scenario test |
|---|---|---|---|---|
| `agent_apps` | WS-1 | WS-3.1 | `agentAppsList` (always), `agentAppSettings` | A1–A4 |
| `agent_app_backups` | WS-2 | WS-3.1 | `agentAppBackups` (ids = projectId) | A5, A6 |
| `sessions` | existing pushes | WS-3.10 | `sessions` (always) | C1, C2 |
| `skills` | WS-2 | WS-3.2 | `skills`, `commands`, `skillMeta` | K1, K2 |
| `mcp_servers` | existing `mcp_list` | WS-3.3 | `mcpServers` | K4 |
| `integrations` | existing `integration_list` | WS-3.4 | `integrations` | K6, K7 |
| `proactive` | WS-2 | WS-3.5 | `proactiveTasks`, `proactiveMode` | P1–P3 |
| `scheduler` | WS-2 | WS-3.5 | `schedulerConfig`, `memorySchedule` | P2, P4, M3 |
| `memory` | WS-2 | WS-3.6 | `memoryItems`, `memoryGraph`, `memoryIndexedFiles` | M1, M2, M4 |
| `workspace_files` | WS-3.9 | WS-3.9 | `workspaceListing` (ids = dir), `workspaceOpenFile` | W1–W5 |
| `agent_files` | WS-2 | WS-3.7 | `agentFiles` (ids = filename) | S1, S2 |
| `general_settings` | WS-2 | WS-3.8 | `generalSettings` | S3–S5 |
| `model_settings` | WS-2 | WS-3.8 | `modelSettings` | S6–S9 |
| static: `playbooks`, `marketplace` | — | — | refresh on reconnect / version change | A11, C4 |

---

## 7. Verification

### 7.1 Automated

- **Backend unit tests** for `resource_changes.py`:
  - coalescing: N calls in a window produce one event, ids unioned, and a no-ids call collapses to "all"
  - emits from a non-loop thread
  - no loop registered yet: queued or dropped safely, never raises
- **Backend emit tests**, one per domain emit point: perform the mutation with the notifier patched and assert `(resource, ids)`.
- **Frontend logic smoke tests** for `ResourceSync`, bundled with esbuild and run with node (same approach as the uiState smoke test on 2026-09-15):
  - subscriber counting
  - stale-marking vs immediate refetch
  - coalescing
  - reconnect invalidation
- **`tsc --noEmit` and `vite build`** on every workstream.

### 7.2 Two-tab browser harness (Playwright)

Proven workable on 2026-09-15:
- **Playwright install:** `agent-app/node_modules/playwright` is already present.
- **Target:** runs against the dev server on `:7925` in isolated headless profiles.
- **Tour:** seed `craftbot.ui.tour.completed.core=true`, or the guided tour navigates away after 800 ms.

Scenarios, each "act in tab A (or via the agent / file system), assert in tab B within 2 s, no reload":

| # | Act | Assert |
|---|---|---|
| 1 | Delete app from sidebar while B is on Settings → General; B opens Agent App tab | app absent (A1) |
| 2 | Create an app (agent or modal) with B on Settings → Agent App | app appears with status (A2, A3) |
| 3 | Kill an app process | status leaves "running" (A4) |
| 4 | Save USER.md, switch tab, return (single tab) | saved content shown (S1) |
| 5 | Edit USER.md on disk | editor updates when not dirty; "changed elsewhere" when dirty (S2, §4.4) |
| 6 | Rename agent | sidebar/chat name updates (S3) |
| 7 | Open General with Light theme saved | dropdown shows Light, form clean (S4) |
| 8 | Agent adds a recurring task (chat prompt) | Proactive list shows it (P1) |
| 9 | Agent stores a memory / memory processing runs | Memory page and Settings update (M1) |
| 10 | Write a file into the open workspace folder from the shell | listing updates within 1 s (W1) |
| 11 | Tab B navigates to a different folder | tab A's listing unchanged (W3) |
| 12 | Copy a file and paste into another folder | no hang, current listing intact (W4) |
| 13 | Dashboard open, send a chat message | task/token counts tick (D1) |
| 14 | Edit `mcp_config.json` | MCP tab updates (K4) |
| 15 | Stop backend 3 min, restart | UI recovers, all visible lists refresh (T1, T3) |
| 16 | Read a chat in B | unread dot clears in A (C3) |

Whether this harness gets committed (e.g. `app/ui_layer/browser/frontend/e2e/`) is decision D5.

### 7.3 Manual smoke per release

Scenarios 1, 4, 8, 10, 13 and 15 in a real browser.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Refetch storms:** memory processing, a busy workspace, scheduler ticks | Backend coalescing (200 ms), `visible` liveness (no refetch for unseen views), frontend microtask batching, session-touch throttling (2 s) |
| **Large payloads refetched often:** memory graph, big directories | ids narrow where supported (workspace per directory, agent files per filename); memory graph refetch only while the Memory page is mounted |
| **`watchdog` on a large workspace:** node_modules, pb_data | Ignore patterns, directory-level ids, debounce; fall back to the existing 30 s poll if the observer fails to start |
| **Emits from worker threads with no event loop yet** | Loop-capture pattern from `agent_app/broadcast.py`; drop silently before the adapter is ready (the connect snapshot covers it) |
| **Outbox replaying a destructive action late** | 60 s outbox TTL with a toast (WS-0.2) |
| **More frequent server updates clobbering drafts** | `useServerDraft` lands (WS-4.1) before or with WS-2 for the affected tabs |
| **Two copies of Agent App data remain** (`agentAppSlice` vs `agentAppSettingsSlice`) | Acceptable once both are invalidated together; merging them is a follow-up (they have different shapes and owners) |
| **Protocol drift** between the backend `Resource` enum and frontend `ResourceName` | One documented list on each side; a startup dev-mode warning when a `resource_changed` arrives with an unknown name |

---

## 9. Decisions needed

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Server push style | (a) invalidate + client refetch; (b) push full snapshots per view | **(a)**: one message type, backend stays view-agnostic, and it matches Redux decision #4 |
| D2 | Where the backend emits | (a) domain layer (managers, reload callbacks, watchers); (b) WebSocket handlers only | **(a)**: the only option that covers agent, scheduler, watchdog and integration changes |
| D3 | Workspace file watching | (a) `watchdog` observer on the workspace root; (b) shorten the poll; (c) UI-initiated changes only | **(a)** with ignore patterns; `watchdog` is already a dependency |
| D4 | Outbox during disconnect | (a) queue everything with a 60 s TTL; (b) queue only idempotent requests; (c) keep dropping | **(a)** |
| D5 | Commit the Playwright two-tab harness | (a) commit under `frontend/e2e/` with an npm script; (b) keep ad hoc | **(a)**: this bug class regresses silently |
| D6 | Scope of cross-tab draft protection (`useServerDraft`) | (a) all forms listed in WS-4.1; (b) only agent `.md` editors | **(a)**: invalidation makes the clobbering more frequent everywhere |
| D7 | Rollout order | WS-0 → WS-1 → WS-4.1 → WS-2 → WS-3 → rest of WS-4 → WS-5 | as listed: transport first (cheapest, biggest relief), then the pilot proves the mechanism end-to-end |

---

## 10. Out of scope

- Offline editing and conflict resolution beyond "keep my draft / accept remote".
- Per-client server-side subscriptions (only sending `resource_changed` to clients that care). Broadcast plus client-side filtering is sufficient at current scale.
- Merging duplicate slices, such as `agentAppSlice` with `agentAppSettingsSlice`, or skills data spread over four slices. Worth doing later; not required for freshness.
- The TUI adapter. It can subscribe to `RESOURCE_CHANGED` later with no backend changes.
