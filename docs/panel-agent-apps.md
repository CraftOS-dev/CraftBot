# Agent Apps in the chat panel

An established chat can show installed Agent Apps beside its conversation, in the
same workspace used by Browser and Outputs. The single split-panel icon opens a
searchable **Open in panel** page with Browser, installed apps, and existing
outputs. Selecting content opens its tab. Browser is not pre-opened or pinned.
The **+** button returns to the same chooser; it is not limited to adding apps.
Closing an app tab detaches it; closing Browser removes its tab without stopping
its session's browser process. Opening the panel from the chat returns to the
chooser, while existing content tabs remain available above it.

A running app displays its existing interactive view. A stopped app offers
**Launch**. Adding a tab, restoring a chat, hiding the panel, or removing a tab
never launches, stops or deletes the app. Use existing app management controls to
stop or delete it. **Open full app** navigates to the existing app page and reuses
the same frame where it remains in the bounded cache.

An Agent App reference's preview also offers **Open in panel**. This only opens
the view: it does not submit a message, add another reference, grant the agent
access, or switch the conversation to the app's backing chat. The reference
system's captured context and read permissions remain unchanged.

## State and lifecycle

App tabs and selection belong to the chat and persist in this browser tab's
session storage, using `UI_STATE.chat.panelApps(sessionId)`. `chat.panelBrowserOpen` tracks whether Browser was explicitly opened;
`chat.panelLastMode` retains selection intent for output-only hosts. They survive normal
navigation and reload. They do not synchronize to another device or browser tab.
The record contains project IDs only; names, status, URL, deployment version,
icons and theme come from the existing app catalog. Browser, app and output tabs have close actions. Closing a background output
does not change the active app view.

Missing IDs are pruned after a successful catalog response, never because the
initial catalog is empty or a connection/request fails. Deleting the chat clears
its panel-app record. Removing a selected app chooses a neighboring tab. Removing
the final app returns the panel to its **Open in panel** chooser.

New generated outputs and a browser-start transition retain their existing
automatic activation behavior. They can replace the app on screen without
removing its tabs. Selecting Apps restores the selected app. Draft chats have no
Apps picker. An app's backing chat excludes that same app from its nested panel,
and collapsing the backing chat releases its nested app view.

## Code structure

Paths are relative to `app/ui_layer/browser/frontend/src/`:

- `components/ChatWorkspace/ChatWorkspace.tsx` owns the common layout, shared tab strip, resizing, animations and focus restoration. `PanelSwitcher.tsx`
  supplies the single direct toggle. Browser and Apps supply
  narrow rendering contracts (`BrowserPanelMode`, `AppsPanelMode`); generated
  output rendering stays in its feature. Each tab in the strip carries its own
  select and close actions; tab ids are only unique keys and are never parsed.
- `components/ChatWorkspace/OutputReference.tsx` owns generated-output references
  and their context. The former `GenerativeUI/OutputWorkspace` has moved here.
- `features/agentApps/usePanelApps.tsx` reads the existing project selectors,
  subscribes to catalog freshness and manages per-chat app identities.
- `components/ChatWorkspace/PanelChooser.tsx` is the inline content chooser for
  Browser, apps and outputs. `usePanelApps` supplies installed-app choices, open
  tab metadata and the selected app surface; it has no modal picker or nested
  tab strip.
- `features/agentApps/panelAppsState.ts` contains validated, pure add/select/prune
  operations. A chat holds at most 100 attached apps; attaching more is ignored.
- `features/agentApps/AgentAppSurface.tsx` renders app status, construction or the
  running view, shared by the panel and full app page. It has no backing chat or
  route ownership. Existing construction UI and theme catalog are reused.
- `features/agentApps/useAgentAppTheme.ts` preserves saved themes and existing
  `livingui-theme` / `craftbot-theme-request` wire contracts.
- `features/agentApps/frameHost.ts` is the extracted persistent iframe pool. DOM
  resources stay private to this module, outside Redux. A surface acquires an
  exclusive lease; stale releases cannot hide another owner's frame.
- `features/agentApps/useAgentAppFrame.ts` places a leased frame over its React
  placeholder and cleans up observers, timers, event listeners and animation work.
- `features/agentApps/PanelAppContext.ts` exposes only the presentation action
  needed by reference chips, including eligibility for the current surface.

The app page retains navigation, its backing chat, the theme picker and destructive
management UI. The backend's existing project manager, launch locking, port
allocation and WebSocket launch/list messages are unchanged. No new protocol,
dependency, plugin registry or app process is introduced.

## Frame host contract

There is one frame per project in a document and at most five cached frames.
Acquiring an already owned project or a full cache of owned frames returns a
recoverable unavailable state. Releasing a lease hides the frame but retains its
live UI until the cache needs space. Eviction considers only unowned frames;
server stop/delete and catalog reconciliation dispose obsolete frames even when
their React surfaces are absent. Runtime deployment changes update the frame
source; ordinary catalog refreshes do not.

The placement hook tracks ancestor size, scrolling, visibility and clipping. It
follows workspace motion and ancestor CSS transitions with animation frames while
motion is active, rather than polling continuously. Resizing and local modal
interactions suppress frame input. Parent `aria-hidden`/`inert` state hides the
pooled frame even though its DOM lives outside React's panel subtree. The pool
remains below the application's modal layer.

Installed apps keep their separate HTTP(S) origin and existing media delegation.
The localhost rewrite preserves the existing SameSite cookie behavior. Generated
HTML's restricted sandbox is separate and is not reused for installed apps.
Theme replies validate the originating frame window and exact runtime origin;
outgoing messages target that origin. Runtime addresses come from the catalog,
not user-entered URLs or persisted panel state.

A frame `load` event indicates navigation completion, not application health.
The process status remains backend-owned. A slow navigation offers Retry after
20 seconds. Embedding restrictions, redirects, a broken app or a runtime that
cannot be reached from the browser can still prevent display. Opening the full
app page does not bypass an app's embedding policy. This feature retains the
existing local runtime addressing model rather than introducing a remote proxy.

## Verification

Verified on 2026-10-26: TypeScript checking and the production build passed. The
full 88-test browser regression run passed; after adding stalled-navigation
coverage and final visual fixes, all 11 panel tests passed again. The frame-host
and existing cross-origin media checks also passed. Build output retains Vite's
large-chunk advisory. No live app processes, production app data or model calls
were used for these checks.

From the frontend directory:

```powershell
.\node_modules\.bin\tsc.cmd --noEmit
npm run build
npx playwright test --workers=2
```

When rebuilding a running static-server instance manually, set its backend port
before building (PowerShell: `$env:VITE_BACKEND_PORT = '7926'; npm run build`,
using that instance's actual port). The normal `run.py` launcher supplies this
value automatically. A bare Vite production build omits the direct-backend
WebSocket address and cannot connect through the static server's `/ws` route.

`tests/panel-agent-apps.*` mounts the real chat, app page, Redux store and frame
host against an offline transport and cross-origin fixture apps. Coverage includes
state retention, page handoff, explicit launch, independent chats, reload, failed
catalogs, deletion, inline chooser search and explicit Browser opening, reference opening, browser/output takeover,
deployment refresh, narrow layout and hidden backing chats. Host tests cover
exclusive ownership, stale cleanup, bounded cache eviction, message origins and
persisted-record validation. Existing output, reference and media tests remain
part of the suite. Two output test clock pauses use browser time with a future
margin to avoid attempting to pause an installed clock in its past.

Manual checks against a real installed native and supported external app are still
useful for their own authentication, responsive layout, permission prompts and
deployment behavior; automated fixtures do not exercise production app data or
start real app processes.
