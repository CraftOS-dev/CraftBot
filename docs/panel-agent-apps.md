# Agent Apps in the chat panel

A chat's panel, on its left, shows one thing at a time: its Generative UI
outputs, its browser, or an installed Agent App. The round buttons at the chat's
top left choose: **Outputs** (once the chat has one), **Browser**, and
**Agent Apps**. Pressing the Outputs or Browser button while it is on show
closes the panel, as before.

The Agent Apps button shows the sidebar's Agent Apps cube until the chat has an
app, then that app's icon. If the chat's app is hidden, pressing the button
shows it again directly. Otherwise it opens a menu of the installed apps, styled like the sidebar's Agent Apps flyout, with the chat's current app
highlighted; once the chat has an app the menu ends with **Close**. Picking an app shows it in the
panel and picking another replaces it. **Close** stops the chat having an app
and hides its pane. The list works with the keyboard (Arrow keys, Enter,
Escape). The app fills the pane with no bar above it, as on its own page; the
seam still resizes or closes the panel.

Opening and closing the panel (any content: outputs, browser or app) slide its
content in and out at the panel's open size, with the Agent App page's chat
panel motion (260 ms), whatever the OS reduced-motion setting, as that panel
does; an app keeps showing, without taking input, while it
slides out.

A running app displays its existing interactive view. A stopped app offers
**Launch**. Showing, switching, hiding or closing never launches, stops or
deletes an app; use the app's own management controls for that. The app's own
page reuses the same frame while it remains in the bounded cache.

An Agent App reference's preview also offers **Open in panel**. This only shows
the app: it does not submit a message, add another reference, grant the agent
access, or switch the conversation to the app's backing chat.

## State and lifecycle

Each chat remembers its app in this browser tab's session storage,
`UI_STATE.chat.panelApp(sessionId)` (a project id; '' before one is picked),
and what its panel shows in `UI_STATE.chat.panelMode(sessionId)` ('apps' for the
app). Both survive navigation and reload, but not another device or browser tab.
Names, status, URL, deployment version, icon and theme come from the app
catalog, never from this record.

A deleted app is forgotten after a catalog response that actually arrives, never
because a request failed or the connection dropped; deleting the chat clears it.
New generated outputs and the agent starting to browse take the panel over as
before; picking the app again brings it back with its state. Draft chats have no
Agent Apps button, and neither does an Agent App's own chat: its panel holds
only outputs and the browser.

## Code structure

Paths are relative to `app/ui_layer/browser/frontend/src/`:

- `components/ChatWorkspace/ChatWorkspace.tsx` owns the layout, the round panel
  buttons, resizing, animations and focus restoration. Browser and apps supply
  narrow contracts (`BrowserPanelMode`, `AppsPanelMode`); generated output
  rendering stays in its feature.
- `components/ChatWorkspace/AppPickerButton.tsx` is the Agent Apps button and
  its menu. Chat's `showAgentApps={false}` (the Agent App page) removes it.
- `components/ChatWorkspace/OutputReference.tsx` owns generated-output references
  and their context.
- `features/agentApps/usePanelApps.tsx` reads the project catalog and keeps the
  chat's app id.
- `features/agentApps/AgentAppSurface.tsx` renders app status, construction or the
  running view, shared by the panel and the full app page.
- `features/agentApps/useAgentAppTheme.ts` preserves saved themes and the existing
  `livingui-theme` / `craftbot-theme-request` wire contracts.
- `features/agentApps/frameHost.ts` is the persistent iframe pool. A surface
  acquires an exclusive lease; stale releases cannot hide another owner's frame.
- `features/agentApps/useAgentAppFrame.ts` places a leased frame over its React
  placeholder and cleans up observers, timers, listeners and animation work.
- `features/agentApps/PanelAppContext.ts` exposes the "show this app" action to
  reference chips.

The app page keeps navigation, its backing chat, the theme picker and the
destructive management UI. The backend's project manager, launch locking, port
allocation and WebSocket launch/list messages are unchanged.

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

Verified on 2026-10-27: TypeScript checking passed and the full 92-test browser
suite passed, including 14 panel tests and the frame-host and cross-origin media
checks. No live app processes, production app data or model calls were used.

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
host against an offline transport and cross-origin fixture apps. Coverage
includes the round buttons and the app list (mouse and keyboard), state
retention, page handoff, explicit launch, process states, independent chats,
reload, failed catalogs, deletion, reference opening, browser/output takeover,
deployment refresh, stalled and background loads, narrow layout and hidden
backing chats. Frame-host tests cover exclusive ownership, stale cleanup,
bounded cache eviction, load tracking and message origins.

Manual checks against a real installed native and supported external app are still
useful for their own authentication, responsive layout, permission prompts and
deployment behavior; automated fixtures do not exercise production app data or
start real app processes.
