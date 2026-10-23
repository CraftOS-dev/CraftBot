# Generative UI (issue #479)

Generative UI turns an agent answer into an interactive HTML/CSS/JavaScript
experience in a dedicated output workspace beside the conversation. The generated document requires no backend, database,
package installation, build, or server process. CraftBot's existing backend
records the artifact alongside the chat message.

## Agent contract

The agent chooses the output format based on the user's goal. Use `render_ui`
when manipulating inputs, exploring alternatives, inspecting changing information,
or tracking progress materially helps accomplish the task. Prefer text when
reading alone meets the need, and respect an explicitly requested output format.
Topic categories do not trigger UI generation; the examples in this document are
test cases, not a list of supported or preferred use cases.

Call `render_ui` with `title`, `html`, and optionally `libraries`,
`connect_origins` (exact public HTTPS API origins the output fetches),
`image_origins` (exact public HTTPS origins for web images) and
`images` (named local image files, for example from `generate_image`).
The action returns `artifact_id` and `revision`. To revise an existing answer,
send its ID with the complete replacement document in the same session.
Older revisions remain in history and can be selected in the output workspace. Revision lookup uses the session's event
stream and falls back to saved chat history after context folding or restart.

HTML is capped at 512,000 UTF-8 bytes. Titles are capped at 120 characters.
Use inline CSS and JavaScript, `addEventListener`, semantic controls, responsive
layouts, and loading/error states. External scripts, module dependencies,
inline event attributes, browser permissions, and API secrets are unsupported.
The runtime blocks form submission and link navigation itself.

The action description is part of every session's `<actions>` block, so every
turn pays for it. Keep it short: a rule the runtime can enforce (submit and
link blocking, reduced motion, the content policy) belongs in the runtime, not
in the description. The October 2026 visual revision cut it from 662 to 521
tokens (o200k) while adding `libraries`, `image_origins`, `images`, the
colour rule and the map helper.

## Visual libraries and images

The guidance asks for a visual centerpiece (a map, chart, diagram,
illustration, 3D scene or image) rather than plain forms, lists and tables.
An output lists the libraries it needs in `libraries`; each is preloaded as a
global before the output's own scripts run:

| Name | Global |
| --- | --- |
| `leaflet` | `L` (Leaflet 1.9, marker and control images inline); base map `L.tileLayer.craftbot()` |
| `three` | `THREE`, with `THREE.OrbitControls` |
| `chart` | `Chart` (Chart.js, all chart types registered) |
| `motion` | `Motion` (`animate`, `stagger`, `inView`, ...) |
| `lucide` | `lucide`; `lucide.createIcons()` fills `<i data-lucide="name">` |

Nothing is fetched from the network. `frontend/generativeUILibraries.ts` (a
Vite plugin) bundles each library with esbuild into one classic script, and
the panel loads it on demand and inlines it into the output's document. The
build fails if a bundle contains markup that could end its element. Chart.js
starts in the host's font and `--cb-*` colours and follows theme changes,
including the axis colours each chart copies into its own config when built.
Leaflet's controls, popups and attribution use the `--cb-*` tokens. With a reduced-motion
preference, Motion skips animations and Chart.js disables them. The names are
listed in `app/generative_ui.py` (`LIBRARIES`) and
`components/GenerativeUI/assets.ts`; keep both lists in step.

Map tiles come through CraftBot, not from the tile server. The sandboxed page
has an opaque origin, so its own requests carry no Referer and cannot identify
the app; OpenStreetMap's usage policy requires both, and its servers answered
such requests with a 403 "Access blocked" tile in a live run.
`L.tileLayer.craftbot()` loads tiles from `/api/generative-ui/tiles/{z}/{x}/{y}`
(the only host path the page's image policy allows). `app/map_tiles.py` fetches
each tile under CraftBot's own User-Agent, shares concurrent requests for one
tile, makes at most 4 upstream requests at once, and caches tiles in
`app/data/.usage/map_tiles/` for as long as the server's caching headers allow
(7 days when it sends none). The server, attribution and maximum zoom are the
`generative_ui` settings (`map_tiles_url`, `map_attribution`, `map_max_zoom`;
default OpenStreetMap). `/api/generative-ui/tiles` gives the page the
attribution and zoom, as `window.craftbot.map`.

Web images load from the origins in `image_origins`, which are validated like
`connect_origins`.

`images` maps names to local PNG, JPEG, GIF or WebP files (at most 8, 8 MB
each, 16 MB in total, type checked by content). The chat store copies them
beside `chat.db` (`generative_ui/<session key>/<artifact id>/<hash>.<ext>`)
and serves them from `/api/generative-ui/`. The panel reads them, and the
page receives them as data URLs in `window.craftbot.images.<name>`. They are
deleted with their output (closing its tab) and with their chat (clear,
delete or reset).

The conversation contains a compact Open output reference. One selected document
runs in a separate full-height output pane, independently of virtualized message
rows. New outputs open automatically; older revisions are selectable. Closing
the pane returns to conversation and stays closed across reloads for that session,
until the user reopens it or a new output arrives. Loading older history does not
reopen it. Desktop shows conversation and output side by side; narrow screens
switch between them. Phone preview and fullscreen resize the canvas without
reloading the document. Drag the divider to adjust the conversation/output split;
Arrow keys, Home and End also resize it, and double-click restores the default.
The split is remembered as a browser preference. At workspace widths below 860px,
the output takes the available space instead of squeezing both views together.
One adaptive header holds the output title, device preview, revision selector,
reload and panel controls. The preview sits on a separate inset canvas.
Pause shows a direct Resume button and retains saved progress. Reset asks for an
in-panel confirmation before clearing only that output's state. Preview errors
show a retry action with technical details behind a disclosure.
Panel entry/exit and fullscreen animate the shared grid tracks, so the chat,
divider, output and its toolbar move together. The toolbar keeps the same two-row
composition in split and fullscreen views. Preview sizing and menus use short eased motion.
Resizing by dragging stays immediate, and existing document state is retained.
Motion is disabled when the browser requests reduced motion. Generated documents
are also instructed to honor that preference and keep controls responsive.

Generated content receives a small base stylesheet and the host's public design
tokens: `--cb-bg`, `--cb-surface`, `--cb-text`, `--cb-muted`, `--cb-border`,
`--cb-accent`, and `--cb-font`. Every colour must follow CraftBot's light/dark
theme: the guidance allows only these tokens or CSS `light-dark(light, dark)`
(the runtime sets the document's `color-scheme` to the host theme). Inside the
sandbox `prefers-color-scheme` follows the operating system, not CraftBot, and
setting `color-scheme` on the iframe does not change that, so pages must not
use it. Theme updates cross the validated bridge without reloading the document
or resetting progress; a changed theme fires a `craftbot-theme` event on
`window`, so colours drawn by script (canvas, WebGL) can be redrawn.
`window.craftbot.theme` exposes the same visual tokens, without other host state.
The generation guidance favors a visual centerpiece, bold typography and
deliberate colour within those tokens. Existing artifacts with hardcoded colors
need a revision to adopt the tokens; the runtime does not overwrite their
authored CSS.

The runtime supplies a small synchronous API before generated scripts run:

```javascript
const state = { servings: 2, completedSteps: [], ...window.craftbot.state };
servingsInput.addEventListener('change', () => {
  state.servings = Number(servingsInput.value);
  window.craftbot.saveState(state);
});
```

State must be a JSON object of at most 65,536 UTF-8 bytes. Save changes when
they happen; state is not scraped from the DOM. Use absolute deadlines for
timers, rather than counting interval callbacks. Dates must be stored as JSON
timestamps and reconstructed on restore. State is shared by an artifact's
revisions in one chat session; preserve compatible state keys when revising.

State lives in CraftBot's Redux UI store and sessionStorage. It survives chat
navigation, virtualization/remounting, expansion, preview reloads, and page
reloads in the same browser tab. Closing the tab clears this first version's
progress; artifact code and metadata remain in SQLite chat history. Reset clears
progress for that session/artifact. Pause removes the iframe; resume restores
saved state, and does not guarantee background timers or notifications.

## Data access

Offline interfaces receive `connect-src 'none'`. An output may declare up to eight
exact public HTTPS API origins in `connect_origins`. These become its CSP
connection allowlist; undeclared origins and redirects to them stay blocked.
Origins use the default HTTPS port and contain no paths, query strings,
credentials, IP addresses, local hostnames, or wildcard expressions. The backend
normalizes and validates the list; the renderer independently validates persisted
metadata and fails closed if it is invalid. No providers or task categories are
hardcoded in the action or renderer. APIs must permit browser CORS without
private credentials. Other resource types remain blocked as described below.
Older artifacts without `connect_origins` load offline.

This is a browser connection policy, not a DNS firewall. Hostname validation
does not resolve DNS or prevent public-looking names resolving to private
addresses. Stronger network isolation remains part of hostile-code hardening.

## Runtime boundaries and remaining hardening

The preview uses an opaque-origin iframe with `allow-scripts allow-forms` and no
same-origin, popup, top-navigation, download, camera, microphone, geolocation,
or clipboard delegation. `allow-forms` enables local submit events;
`form-action 'none'` independently blocks network submission.

Host markup parsing uses parse5's pure syntax tree, which does not start image or
frame requests and preserves document/body attributes. Policy overrides, nested frames, external scripts, and inline
event handlers are removed before preview insertion. A CSP precedes generated
content: external scripts, frames, workers, fonts, media and other resource
types are blocked; images can use only data/blob sources and the output's
declared `image_origins`. Inline scripts and
styles are supported, but JavaScript evaluation through eval/Function is not.
Bridge messages must come from the exact live iframe window and carry its
per-mount token; payload types and state sizes are checked. No host credentials
or arbitrary tool calls are exposed. A page's own script errors and blocked
requests are not reported to the panel (they stay in the frame's console); the
panel shows an error only when the preview cannot load (its libraries or images
are unavailable, or it never signals ready).

**This is an initial browser runtime, not a complete hostile-code sandbox.**
An iframe can navigate its own browsing context through JavaScript; current
browser CSP does not provide a portable way to prohibit all such requests.
Intercepting links and stripping refresh metadata prevents ordinary navigation,
but is not an adversarial egress guarantee. An infinite loop can also hang the
browser renderer and prevent its pause/reload controls from responding.
Before claiming strict network containment and bounded CPU execution (and closing
the corresponding requirements in #479), choose an execution environment that
can enforce navigation and resource limits, or restrict generated behavior to a
trusted component/action vocabulary. These limits must not be described as solved
by iframe sandbox flags or a host watchdog.

The implementation favors generated HTML for custom interactions. Alternatives
researched include [AI SDK's tool-to-component pattern](https://ai-sdk.dev/docs/ai-sdk-ui/generative-user-interfaces),
[A2UI's declarative component protocol](https://a2ui.org/introduction/what-is-a2ui/),
and [OpenUI's controlled component libraries](https://github.com/thesysdev/openui).
Those trade free-form behavior for more controlled execution.

## Development preview and verification

From `app/ui_layer/browser/frontend`:

```sh
npm ci
npm run dev -- --host 127.0.0.1 --port 7935
# Open http://127.0.0.1:7935/tests/generative-ui.html

npx playwright install chromium
npm run test:generative-ui
npx tsc --noEmit
npm run build
```

The development-only harness uses the actual chat message and artifact renderer
with an isolated Redux store. It does not start a model, write a live database,
or enter the production build. Its cooking, weather and design documents live
under `frontend/tests/fixtures/`. The weather fixture calls the live service when
used manually; automated tests intercept responses to cover success and failure
deterministically.

Python regression checks from the repository root:

```sh
python -m pytest tests/test_generative_ui.py tests/test_chat_storage_sessions.py tests/test_ui_event_delivery.py tests/test_browser_ui_buffers.py -q
ruff check .
python -m compileall -q app agent_core agents decorators skills
```

Coverage includes artifact validation, event transport, additive SQLite migration,
session scoping, revision lookup, cooking progress/timers, expand/reset/pause/retry,
page reload, local temperature conversion, API failure states, design interaction,
keyboard controls, narrow layouts, parent/storage isolation, external resource
blocking, forged bridge messages, oversized state and visible runtime errors.
This does not substitute for a hostile-code containment audit or broad model
evaluation.

## Live agent evaluation — 8 October 2026

Ran the production browser interface on localhost:7945 with the configured
OpenAI `gpt-5.2-2025-12-11` model, using separate test history and no connected
MCP servers. The messages below never named Generative UI, `render_ui`, HTML,
JavaScript, or the artifact runtime. The agent received its normal core action
catalog and chose the response format itself.

| Natural request | Agent's choice | Live checks |
| --- | --- | --- |
| Help me cook tomato pasta for two, track completed steps, and adjust quantities if a friend joins. | `render_ui`, offline cook-along | Selecting 3 servings changed pasta from 200 g to 300 g and tomatoes from 400 g to 600 g. Checklist completion, notes, servings and an active timer survived a browser reload. |
| Check London weather for a walk, with Celsius/Fahrenheit and a way to check again before leaving. | `render_ui` with `weather` | Current conditions and a six-hour forecast loaded from the live API. Refresh updated the fetch time. Both temperature units appeared together. |
| Compare warm orange/muted green themes, heading sizes, spacing, and mobile/desktop for a coffee-shop landing page experiment. | `render_ui`, offline design experiment | Palette, heading-size and spacing controls changed the preview. The mobile selector updated the device state. |
| What's the capital of Portugal? Please answer in one sentence. | `send_message`, plain text | Replied: “The capital of Portugal is Lisbon.” No artifact was created. |

The first cooking run exposed a runtime integration bug: action registration
serializes only the function body, so module-level helper imports were absent
in the executor's namespace. Moved the imports inside `render_ui` and changed
the transport/history regression test to execute the registry's serialized
action through `ActionExecutor`. The fresh cooking run then succeeded.

A production reload also exposed a false timeout banner on a functioning
preview during history hydration. Each generated document now receives a fresh
iframe, the message listener registers in a layout effect, and a load handshake
recovers an early ready message. Translation synchronization also no longer
restarts readiness tracking for an already loaded iframe. Browser regressions
replace artifacts during hydration and change the app language, then advance
beyond the timeout to verify the previews remain ready.

The first generated weather document incorrectly treated the API's default
wind speed as m/s. A natural follow-up asking the agent to double-check the
units produced revision 2 with corrected km/h and mph values. Expansion also
loaded that revision successfully. This demonstrates revision delivery, but
also a remaining generated-content quality risk: a functioning interface can
misinterpret API data. [Open-Meteo's unit parameters](https://open-meteo.com/en/docs)
and returned unit metadata should be checked before conversions.

The cooking agent also asked a redundant text question about servings after
providing a working servings selector. Further evaluation should cover these
handoff choices, first-generation API accuracy, and whether the agent avoids
claiming to observe or change preview state it cannot access.

## Presentation revision

After feedback on both the chat framing and generated content, the host wrapper
was reduced to the answer itself and a small footer. Theme tokens and a base
stylesheet now help answers blend into the conversation. Generation guidance
explicitly targets the inline container width and favors plain lists, a clear
primary action, and optional details behind disclosures.

A natural follow-up in the live cooking conversation produced a single-step
layout. Its first revision still stacked into a 960px preview at the actual
708px chat width. A further refinement produced a 386px preview with compact
ingredients and timer beside the current step, optional notes, and a single
Done + Next action. Advancing a step and changing to three servings worked,
and the values survived a page reload. Switching between light and dark themes
updated the answer without losing progress; the timer also started successfully.
These results also show that design guidance improves defaults but does not
guarantee the quality of every generated layout.

## Dedicated output workspace

Further feedback replaced inline rendering with a separate output pane. Chat
keeps an Open output reference, while one selected revision runs outside the
virtualized timeline. The canvas fills the available height and can take the
entire content area or a phone-width viewport. Its selection/closed state is
scoped to the conversation, and the runtime state remains scoped to the artifact.

Four additional browser regressions cover output lifecycle, revision switching,
viewport/fullscreen changes without document reload, and session-specific closed
state while loading older history. All 14 browser tests pass; TypeScript and the
production build pass.

Live refinements of the pancake and Edinburgh weather examples opened as revision
2 automatically. Cooking progress, four-serving quantities, and paused timer
state survived reload. Weather selection, units and refresh worked. The original
weather document had persisted Date objects as strings, then called getTime on
restore; the agent revised its JSON restoration logic and the new version loaded
without that error. Guidance now explicitly describes JSON timestamps.

The larger portfolio revision exceeded the model response budget repeatedly,
producing incomplete action JSON. A smaller composition was requested rather
than treating the failed generation as a usable output. Complete-document
generation still depends on the provider's output budget.

The smaller portfolio composition succeeded. Its third revision corrected a
palette conflict between the host theme and the document's Sand/Ink themes.
Both theme buttons and project detail/back navigation worked in the live output
workspace. The final Sand view was checked full-screen. The runtime's native
controls now inherit authored text colors, covered by a browser assertion.

After removing topic-based selection examples and layout instructions, fresh
live requests initially produced conversational answers. Describing a need for
self-paced answer checking, repeatedly changing cost inputs, or trying furniture
positions prompted the agent to select `render_ui` without naming the action or
prescribing a UI. These are observations of model decisions, not deterministic
selection guarantees. The practice set's answer feedback and final summary
worked; a revision replaced a blocked browser confirmation with an in-page reset,
which cleared the saved answers and score. The cost split updated for a one-night
guest and changed accommodation costs, and disclosed rounding differences.
The room planner required revisions for collapsed CSS sizing and a DOM-ID/state
variable initialization collision. The final revision rendered without the error;
X/Y controls moved the selected furniture, and its corrected total 160×200cm bed
footprint cleared the desk/bookcase. Desktop and phone views were inspected.
Dragging was not confirmed by the browser driver; direct position controls were
the verified way to move items.
