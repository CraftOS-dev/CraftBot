# Rebuild CraftBot's terminal as a protocol client

**CraftBot should build its terminal edition as a Node 24 + Ink 8 client of the WebSocket protocol the Python backend already serves on 127.0.0.1:7926. The conversation prints inline into the terminal's native scrollback, and every other surface (sessions, settings, memory, workspace, dashboard, Mini Browser, Agent Apps) opens as a full-screen view on the alternate screen.** That choice needs almost no new Python. The backend already speaks a complete multi-client protocol (152 inbound message types, request ids, ordered per-client channels, liveness pings, snapshot resync), so the terminal is simply a second client of the same server. The BrowserAdapter teardown the brief proposes becomes optional hygiene, not a prerequisite. The real backend work is a boot-time "terminal edition" seam (a static prompt variant, `render_ui` removed from the action space, the web UI not served, backend logs moved off the console), protocol additions that only clients which declare them receive, and deleting the line-based CLI from 27 files. Agent Apps become terminal-native through views generated from each app's operations.json and live describe endpoint, plus a new declarative `views.json` in which every data source and every action names a declared op. That turns the owner's "every feature reachable through CLI ops" rule into something the build gate can enforce. Evidence from Claude Code, Gemini CLI, Codex, opencode and Hermes says users judge an agent TUI first on rendering integrity (no flicker, stable scroll, copy that yields source text, IME that follows the caret), and that every vendor that forced one screen mode on all users had to back down. Several assumptions in the brief do not hold on branch V1.4.5: there is no PyInstaller-packaged backend, Node 24 is already mandatory, Claude Code no longer runs on stock Ink, existing Agent Apps' rich web UIs cannot move into a terminal, and the Agent App build pipeline verifies apps in headless Chromium. Thirteen decisions are left for the owner, each listed at the end with a recommendation.

## Agent TUIs converged on a hybrid and paid for every forced default

### Upstream Ink 8 now ships what teams forked Ink to get in 2025

**Ink 8.0.0 (published 2026-10-03) requires Node 22+ and React 19.3+.** It ships synchronized output (DEC 2026), opt-in incremental rendering that skips unchanged line prefixes, an alternate-screen option, kitty keyboard support, bracketed paste through `usePaste`, `useCursor` for placing the real cursor for IME, `contentOffsetY` scroll offsets, and `suspendTerminal()` for handing the TTY to another program ([npm: ink](https://www.npmjs.com/package/ink); [Ink v8.0.0 release](https://github.com/vadimdemedes/ink/releases/tag/v8.0.0); [Ink README](https://github.com/vadimdemedes/ink)). Its structural weakness is unchanged. When a frame is taller than the viewport, Ink falls back to clearing and repainting the whole frame. **On Windows it always fully clears any frame that fills the viewport**, because Windows consoles scroll the buffer when the bottom-right cell is written ([unpkg: ink@8.0.0 build/ink.js](https://unpkg.com/ink@8.0.0/build/ink.js)).

Every serious agent built on Ink ended up owning more than Ink. Claude Code "abandoned Ink and built a custom renderer from scratch while retaining React" ([steipete.me](https://steipete.me/posts/2025/signature-flicker)). Its team calls the result "a small game engine" with a ~16 ms frame budget ([Simon Willison](https://simonwillison.net/2026/Jan/22/chris-lloyd/)), and its leaked source shows a forked `src/ink/` with a 1,722-line main loop and cell-level diffing ([Qwen Code design doc](https://github.com/QwenLM/qwen-code/blob/main/docs/design/virtual-viewport/README.md)). Gemini CLI pins a fork, `@jrichman/ink@6.6.9` ([gemini-cli package.json](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/package.json)), and Hermes Agent vendors `@hermes/ink` ([hermes-agent ui-tui package.json](https://github.com/NousResearch/hermes-agent/blob/main/ui-tui/package.json)).

The counterexample matters most for CraftBot. **Qwen Code refused to fork and built a virtualized viewport on stock Ink 7**, calling a wholesale fork "unsustainable maintenance" at its scale ([Qwen Code design doc](https://github.com/QwenLM/qwen-code/blob/main/docs/design/virtual-viewport/README.md)). OpenTUI is the only serious non-Ink React option, and it needs Bun or Node 26.4+ with experimental FFI and is still at 0.x ([OpenReplay](https://blog.openreplay.com/opentui-alternative-ink/); [npm: @opentui/core](https://www.npmjs.com/package/@opentui/core)). That is a poor foundation for a Windows-first product with heavy CJK use.

### The UI is a client of the agent everywhere except Claude Code

Claude Code runs its agent loop and its UI in one Bun process and added protocols afterwards: stream-json for SDKs and a supervisor daemon for background sessions ([Claude Code docs: headless](https://code.claude.com/docs/en/headless); [agent view](https://code.claude.com/docs/en/agent-view)). The others made the TUI a client. Codex's TUI speaks its app-server JSON-RPC protocol, either in process or over stdio and WebSocket ([Codex docs: App Server](https://learn.chatgpt.com/docs/app-server)). opencode's TUI is one client of an OpenAPI HTTP + SSE server, which is how it rebuilt the TUI twice without touching the agent ([opencode docs: server](https://opencode.ai/docs/server/)). The closest analog to CraftBot is Hermes, a Python agent whose Node/Ink TUI spawns the Python gateway and talks newline-delimited JSON-RPC over stdio ([hermes-agent ui-tui README](https://github.com/NousResearch/hermes-agent/blob/main/ui-tui/README.md)). Hermes had no server to reuse. CraftBot does, and that changes the answer (section a).

### Screen mode is a product risk, not an engineering detail

The industry has swung back and forth on screen mode:

- **Gemini CLI** made the alternate screen the default in v0.15.0 (2025-11-03) and rolled it back in v0.18.0 two weeks later ([changelog](https://github.com/google-gemini/gemini-cli/blob/main/docs/changelogs/index.md)).
- **Codex** discontinued its full-screen "tui2" on 2026-01-22 after users wrote "Terminal is king because anything works anywhere. Don't mess it up" ([codex #8344](https://github.com/openai/codex/issues/8344)). It then made fullscreen with mouse capture the default in 0.157.0 and got an all-caps "I CANT ... COPY TEXT" issue within days ([codex #48125](https://github.com/openai/codex/issues/48125)).
- **Claude Code** made fullscreen the default only for users who first used it on or after 2026-05-06. Before doing that it built in-app selection, transcript search, a key that dumps the conversation into native scrollback, and a crash guard that falls back to the classic renderer ([Claude Code docs: fullscreen](https://code.claude.com/docs/en/fullscreen)).

Codex's current source shows the middle path that has lasted. **Finished history is inserted into native scrollback once and never re-rendered. A small inline viewport holds the live part. The alternate screen is kept for overlays and the transcript** ([insert_history.rs](https://github.com/openai/codex/blob/main/codex-rs/tui/src/insert_history.rs); [tui.rs](https://github.com/openai/codex/blob/main/codex-rs/tui/src/tui.rs)).

### Users punish rendering bugs harder than missing features

The most-reacted TUI issues are about rendering integrity:

- Claude Code's uncontrolled scrolling (#3648, **836 reactions**) and jumps to the top of history (#826, **822**).
- Copy that yields hard-wrapped, indented text (#18170, 302).
- Pasted content the user cannot see (#3412, 314; opencode #8501, 329).
- Japanese IME input (#1547, 261; Gemini #1796, 191).

Sources: [#3648](https://github.com/anthropics/claude-code/issues/3648), [#826](https://github.com/anthropics/claude-code/issues/826), [#18170](https://github.com/anthropics/claude-code/issues/18170), [#3412](https://github.com/anthropics/claude-code/issues/3412), [opencode #8501](https://github.com/anomalyco/opencode/issues/8501), [#1547](https://github.com/anthropics/claude-code/issues/1547), [gemini-cli #1796](https://github.com/google-gemini/gemini-cli/issues/1796).

Taking away a visible context meter drew 253 reactions on Codex ([codex #23794](https://github.com/openai/codex/issues/23794)). Personality splits users. Claude Code's removed Buddy companion has 2,116 reactions asking for it back ([#45596](https://github.com/anthropics/claude-code/issues/45596)), while its spinner verbs were called "unprofessional and dismissive" ([#23430](https://github.com/anthropics/claude-code/issues/23430)). The design lesson is to ship personality behind a toggle and make integrity non-negotiable.

### Windows 10 is the hardest target, and it is the owner's platform

Windows Terminal became the default console host only on Windows 11 22H2. **Windows 10 still opens the legacy console host (conhost)** ([Wikipedia: Windows Terminal](https://en.wikipedia.org/wiki/Windows_Terminal)), whose VT documentation lists no bracketed paste, mouse or synchronized output ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/console/console-virtual-terminal-sequences)). Windows Terminal 1.24 ships synchronized output and 1.25 adds the kitty keyboard protocol ([Windows Terminal 1.25 preview](https://devblogs.microsoft.com/commandline/windows-terminal-preview-1-25-release/)). Terminals built on Windows' pseudo-console layer (ConPTY) mis-merge positioned writes, so fullscreen diffing leaves fragments on screen until a full repaint ([Claude Code docs: fullscreen](https://code.claude.com/docs/en/fullscreen)). In raw mode on Windows, Ctrl+C never becomes SIGINT, and closing the console window gives Node about ten seconds before termination ([Node docs: process](https://nodejs.org/api/process.html)).

For CJK input, the real cursor must sit at the caret. Claude Code's IME candidate windows appeared in the wrong place until 2.1.84 moved the native cursor to the input caret ([Claude Code CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)). Grapheme widths still differ between terminals (one ZWJ emoji measured anywhere from 2 to 6 cells) ([Mitchell Hashimoto](https://mitchellh.com/writing/grapheme-clusters-in-terminals)), which is another reason the owner's no-emoji rule helps.

## Ten assumptions in the brief that the evidence corrects

| Assumption in the brief | What the evidence shows | Consequence for the design |
|---|---|---|
| The terminal must ship "with the PyInstaller backend" | The frozen agent was retired in cab503a4 ("replace the frozen agent"). Only the installer EXE is PyInstaller, and it "bundles no agent code" ([craftbot.py](../craftbot.py)). Node 24 is already mandatory for every Agent App (`MIN_NODE_MAJOR = 24`) ([node_runtime.py](../app/node_runtime.py)) | Ship the TUI as a JavaScript bundle run by the Node runtime CraftBot already resolves. No Bun or single-executable build is needed |
| "Like Claude Code's terminal UI, in React + Ink" | Claude Code replaced Ink's renderer and runs UI and agent loop in one process ([steipete.me](https://steipete.me/posts/2025/signature-flicker)) | Copy Claude Code's interaction grammar, not its renderer or process model. CraftBot's Python agent stays out of the UI process |
| Moving AgentAppManager, persistence and the integration bridge out of BrowserAdapter is required | The TUI can be a WebSocket client of the same aiohttp server, which already serves many clients through one `ClientChannel` each ([ws_channel.py](../app/ui_layer/adapters/ws_channel.py)). Persistence, Agent Apps and the bridge keep working untouched | Move only the Agent App bootstrap, as hygiene. Leave persistence where it is |
| The terminal covers "every feature of today's browser UI" | About a dozen features are graphical by nature: Generative UI iframes, the Mini Browser screencast, the memory force graph, the draggable dashboard grid, voice input, image and PDF previews | Each is consciously dropped, rendered as text, or handed to the system browser or OS (table in section b) |
| Agent Apps work "through the terminal only (no browser)" | Existing apps' UIs are 3,676 to 42,523 lines of custom React, with canvas or SVG in up to 187 files, plus three.js, klinecharts and pdf.js. Their build is verified in headless Chromium (`agent-app verify`, walk_verify) ([verify.ts](../agent-app/tools/src/commands/verify.ts)) | "No browser" has to mean no browser in front of the user. Terminal-surface apps need a verifier that does not use a browser (section c) |
| Every Agent App feature is reachable through declared CLI ops | This is not a gate rule for CRUD. The creator skill says plain CRUD needs no verb ([SKILL.md](../skills/agent-app-creator/SKILL.md)), and apps call `pb.collection` directly in 1 to 5 files each | Terminal views can only name ops, which enforces the rule by construction. The gate adds it for terminal surfaces |
| Agent activity should stream like Claude Code | CraftBot has no token streaming. Replies arrive whole as `chat_message`, and tools arrive as `action_add`/`action_update` ([browser_adapter.py](../app/ui_layer/adapters/browser_adapter.py)) | Write each finished message into scrollback once. Do not add streaming |
| Claude-Code-style approvals and permission modes | CraftBot has no tool-approval protocol. Only agent questions and limit prompts block a run ([ui_controller.py](../app/ui_layer/controller/ui_controller.py)) | No Shift+Tab permission modes. The terminal keymap is designed from scratch, because the browser has no global shortcuts either |
| Replacing the old CLI loses nothing | The old CLI's one distinctive property was running with no Node.js ([README.md](../README.md)). `craftbot.py start --cli` already ran it detached with stdin from DEVNULL, so the service path never worked interactively ([craftbot.py](../craftbot.py)) | The terminal edition requires Node 24, which `install.py` can provide as a sidecar download |
| The browser stays byte-identical while state code is shared | The frontend slices import `i18n/config`, `socket/socketInstance` and `uiState`, which are tied to `window` and `localStorage` ([agentSlice.ts](../app/ui_layer/browser/frontend/src/store/slices/agentSlice.ts)) | The TUI swaps in replacements for those modules at bundle time and never edits the frontend |

The two corrections that change the plan most are the third and the fifth. The third makes the backend side small. The fifth makes the Agent App side the strategic part of the project, because an app's terminal surface has to be derived from its ops, not from its React code.

## (a) Architecture: a pure client on the protocol CraftBot already has

```
 Foreground topology: python run.py --tui                    Service topology: install mode "tui"
 run.py (owns the console, idles while the TUI runs)         craftbot.py start  -> run.py -> backend (detached, as today)
  |- backend: main.py -> python -m app.main                  craftbot.py tui    -> node craftbot-tui.mjs (foreground)
  |    hidden console, stdin null, logs to <state>/logs           |  ws://127.0.0.1:7926/ws
  |    aiohttp :7926  /ws  /api/*  /api/bridge/*                  v
  |- node app/ui_layer/terminal/dist/craftbot-tui.mjs --owner  backend :7926 keeps running after the TUI quits
       raw mode, ws -> :7926
 Agent App PocketBase processes :3100-3199  <- TUI calls their ops directly (agent-app lib/project.ts)
                                            -> backend /api/bridge/* via CRAFTBOT_BRIDGE_URL (unchanged)
```

| Decision | Choice | Main reason | Rejected |
|---|---|---|---|
| Process model | The TUI is a pure client and never spawns or kills the backend. run.py parents both processes (foreground), or the existing service runs the backend (service) | Reuses run.py's port freeing, readiness marker, conda handling and Node resolution. Only Node touches the TTY | The TUI spawning Python (Hermes style), or Python spawning the TUI with pipe RPC |
| Transport | The existing `/ws` JSON protocol on 127.0.0.1:7926, with the session-token subprotocol and an explicit Origin header | A complete multi-client protocol already exists, so the core needs zero Python changes | stdio JSON-RPC, ACP, a new HTTP + SSE API |
| Protocol growth | A `client_hello` message with capabilities. Additive messages go only to sockets that declared them | Browser frames stay byte-identical by construction, not by code review | Versioning the whole protocol |
| Renderer | Inline chat on the main screen, plus alternate-screen screens rendered by a second Ink root while the chat root is suspended, plus a plain mode | Native copy and search for the conversation, dense screens for everything else, and no Windows full clears in the chat | Fullscreen everywhere; inline everywhere |
| Ink | `ink@8.0.x` and `react@19.3.x` pinned exactly, no fork. CraftBot owns the text buffer, keymap, Markdown renderer, virtual list and terminal probe | Upstream 8 already has synchronized output, incremental rendering, alt screen, kitty keyboard, paste and the IME cursor | `@jrichman/ink`, a custom renderer, OpenTUI |
| State | A Redux Toolkit store built from the browser's slices, imported read-only, with four platform modules swapped in | One protocol model shared by both UIs, and nothing to drift | Rewriting the slices; extracting a shared package (that would edit the browser) |
| Packaging | An esbuild ESM bundle of about 1 MB, run by the Node 24 that `node_runtime.py` resolves | Node 24 is already mandatory; no 86.6 MB executable and no code signing | `bun build --compile`, Node single-executable apps, npm per-platform binaries |

### Process model and lifecycle

**There are two launcher topologies, and in both the TUI is a client of `127.0.0.1:<port>`.**

In the **foreground topology**, `python run.py --tui` starts exactly as browser mode does today ([run.py](../run.py)): it frees ports 7925/7926 through the process ledger, resolves conda or Python, and clears and waits for the readiness marker. The difference is how it starts the backend: with a hidden console (`CREATE_NO_WINDOW`), stdin from the null device, and stdout and stderr sent to `<state>/logs/backend.log`. Today the backend inherits run.py's console, so any print would corrupt the TUI's frame. run.py then runs `node app/ui_layer/terminal/dist/craftbot-tui.mjs --port 7926 --owner` in the foreground on the same console, and does not start the static frontend server or open a browser.

In the **service topology**, used by managed installs whose metadata mode is `tui`, `craftbot.py start` keeps launching the backend detached exactly as it does now. A new `craftbot.py tui` subcommand runs the client in the foreground against the running service. Quitting the TUI detaches and leaves scheduled and proactive work running. opencode, Codex and Claude Code all converged on this pattern ([opencode default.ts](https://github.com/anomalyco/opencode/blob/dev/packages/cli/src/commands/handlers/default.ts); [codex app-server-daemon](https://github.com/openai/codex/blob/main/codex-rs/app-server-daemon/README.md)).

The TUI paints its first frame immediately and accepts typing before the backend is ready, as Hermes does ([Hermes TUI docs](https://hermes-agent.nousresearch.com/docs/user-guide/tui)). It retries the token endpoint for the browser's 90-second budget, then shows the same "backend isn't responding" message the browser shows ([App.tsx](../app/ui_layer/browser/frontend/src/App.tsx)).

When an owner TUI quits, it sends the existing `/exit` command. That emits INTERFACE_SHUTDOWN and lets `AgentBase.run()` persist sessions and stop Agent Apps, MCP and integrations ([exit.py](../app/ui_layer/commands/builtin/exit.py); [agent_base.py](../app/agent_base.py)). run.py waits a bounded time for the backend to exit before its hard-kill cleanup. That ordering matters on Windows, where `terminate()` is TerminateProcess and gives no chance to shut down cleanly.

Two alternatives were rejected. Hermes' design, where the TUI spawns Python, would mean porting conda, port-freeing and readiness logic into Node. Having Python spawn the TUI and talk over pipes would mean implementing a second protocol in Python.

### Transport and protocol

**Reuse `/ws` unchanged and authenticate exactly as the browser does.** The TUI calls `GET /api/session-token` with no Origin header, which the server already allows for non-browser callers. It then opens `ws://localhost:7926/ws` with the subprotocols `craftbot` and `craftbot-auth.<token>` and an explicit `Origin: http://localhost:7926`, which the Node `ws` package lets a client set ([ws_auth.py](../app/ui_layer/adapters/ws_auth.py)). This adds no new exposure: the token scheme protects against web pages, not against local processes, and any local process can already do the same.

The TUI copies the browser client's reliability behavior: capped exponential reconnect (500 ms growing ×1.5 to 30 s), a 60-second outbox time-to-live, a liveness ping after 5 s of quiet, and a "backend busy" flag after 3 s without a reply ([SocketClient.ts](../app/ui_layer/browser/frontend/src/store/socket/SocketClient.ts)).

The only protocol change is a handshake. After connecting, the TUI sends `{"type":"client_hello","client":"terminal","protocol":1,"capabilities":[...]}`. The backend stores those capabilities on that socket's `ClientChannel`, and any new message type or field is delivered only to channels that declared it. The browser never sends `client_hello`, so it can never receive anything new.

There is still no token streaming. Replies arrive whole, which suits writing each one into scrollback once. ACP stays a possible future editor adapter, not the UI protocol, and MCP stays a tool protocol. Codex reached the same conclusion when it deprecated `codex mcp-server` because MCP "could not accommodate" streaming, server-initiated approvals and durable threads ([Daniel Vaughan](https://codex.danielvaughan.com/2026/08/28/codex-mcp-server-deprecated-app-server-migration-guide/)).

### Renderer: inline conversation, full-screen screens, plain mode

**There are three render paths over one store.**

**1. Inline conversation (main screen).** Each finished message and each settled activity chunk is rendered by the TUI's own Markdown-to-ANSI renderer and written once with Ink's `useStdout().write` ([Ink README](https://github.com/vadimdemedes/ink)). Prose stays as logical lines that the terminal soft-wraps and reflows, and that the user can select and search natively. That is the direct fix for the hard-wrap copy complaints above. The live region below it holds the working row, the running chunk's last rows, the pinned question, the composer and the status line. It is capped at 40% of the terminal's rows (minimum 8, maximum 18 lines), so it never reaches the viewport height that triggers Ink's full clear on Windows. Older history leaves the React tree, so memory stays flat however long the session runs.

**2. Screens (alternate screen).** When a screen opens, the chat's Ink root calls `suspendTerminal()`. A second Ink root renders the screen with `alternateScreen: true` against the same Redux store. On close, the alternate screen is discarded, the chat root resumes and repaints, and messages that arrived in the meantime are written into scrollback. Screens re-render only on input or data change, so a full repaint per frame on ConPTY costs little.

**3. Plain mode.** Triggered by `--plain`, `INK_SCREEN_READER`, a non-TTY or `TERM=dumb`. It never enters the alternate screen and renders screens as numbered menus with labeled lines, which is what Claude Code's screen-reader mode does ([Claude Code docs: accessibility](https://code.claude.com/docs/en/accessibility)).

Ink render options: `exitOnCtrlC: false`, `patchConsole: true`, `incrementalRendering: true`, `maxFps: 30`, `kittyKeyboard: {mode: 'auto'}`, `concurrent: false`.

**Why not fullscreen everywhere?** The chat is where people copy and search, and the copy revolts above show what losing native selection costs. **Why not inline everywhere?** Settings, memory, workspace and Agent App screens are taller than any viewport, which in Ink means a full clear on every frame on Windows.

The two-root handoff has not been proven, so Phase 1 opens with a spike on Windows Terminal, conhost and the VS Code terminal. If the spike fails, the contingency is Claude Code's model: one fullscreen root, a virtualized transcript, `[` to dump the conversation into scrollback, and the transcript printed on exit. That gives up native copy in the chat.

### Ink version and fork policy

**Pin `ink@8.0.x` and `react@19.3.x` exactly, and develop and run on Node 24 LTS.** No fork. CraftBot owns only what every reference agent ended up owning anyway:

- **A grapheme-aware text buffer.** Gemini's is about 132 KB of code ([text-buffer.ts](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/ui/components/shared/text-buffer.ts)).
- **A keymap registry.**
- **A Markdown renderer**, using marked 18 only as a lexer and lowlight for code. Not marked-terminal, which is stuck below marked 16 ([npm: marked-terminal](https://www.npmjs.com/package/marked-terminal)).
- **A virtualized list** built on `useBoxMetrics` plus `contentOffsetY`, the path Qwen proved.
- **The terminal capability probe** and the **clipboard** layer.

Blocking upstream bugs get a local patch file and an upstream issue. A fork becomes justified only if CraftBot needs a renderer-level change such as cell diffing. Two upstream facts shape this policy. Ink majors land every 4 to 6 months with input-handling breaks (6.0 in May 2025, 7.0 in April 2026, 8.0 in October 2026) ([npm: ink](https://www.npmjs.com/package/ink)). And Ink does not accept fully AI-generated pull requests ([Ink README](https://github.com/vadimdemedes/ink)), so any upstream fix needs a human author.

### State reuse without touching the browser

**The TUI's Redux Toolkit store is built from the browser's own slices, imported read-only from `app/ui_layer/browser/frontend/src/store/slices/`.** It also imports `messageRegistry`, `resources/catalog.ts`, `types/index.ts` and the action-name mapping in `actionNames.ts`. The slices are free of DOM code except through four modules they import: `i18n/config`, `socket/socketInstance`, `uiState`, and the middleware's `requestAnimationFrame` batching ([agentSlice.ts](../app/ui_layer/browser/frontend/src/store/slices/agentSlice.ts); [socketMiddleware.ts](../app/ui_layer/browser/frontend/src/store/socket/socketMiddleware.ts)). At bundle time, esbuild swaps those four for terminal bindings:

- Node i18next reading the same locale JSON.
- A `ws`-based socket client.
- A JSON state file under the state root.
- A 33 ms timer in place of `requestAnimationFrame`.

The browser uses React 18 and the TUI uses React 19.3; that does not matter, because slices do not depend on React. TUI-only state lives in its own slice: the screen stack, focus, the scrollback watermark and the detected terminal capabilities. A CI check fails any terminal change that touches the browser frontend directory. If a slice will not import cleanly, it is copied into the TUI with a header naming its origin, never edited in place.

### Packaging and distribution

**Ship an esbuild ESM bundle at `app/ui_layer/terminal/dist/craftbot-tui.mjs`.** It runs on the Node runtime that `app/node_runtime.py` already resolves for Agent Apps: `CRAFTBOT_NODE`, a PATH Node of version 24 or later, nvm, or the sidecar Node that install.py downloads into `runtime/node` ([node_runtime.py](../app/node_runtime.py)).

The local build test during this research found two required fixes. First, alias `react-devtools-core` to an empty module, because Ink's reconciler imports it statically ([unpkg: ink@8.0.0 build/reconciler.js](https://unpkg.com/ink@8.0.0/build/reconciler.js)). Second, add a `createRequire` banner for CommonJS dependencies. With both, a minified Ink 8 bundle measured about 681 KB and ran on Node 24.

Dev checkouts rebuild the bundle in run.py whenever sources are newer, the same rule run.py already applies to `vite build`. Managed installs ship the built bundle, as they ship `dist/`.

Two alternatives were rejected:

- **`bun build --compile`.** It works, but the local build produced an 86.6 MB executable that needs Authenticode signing to get past SmartScreen ([Bun docs](https://bun.com/docs/bundler/executables)).
- **Node single-executable apps.** They need a CommonJS launcher because yoga-layout uses top-level await ([Node docs: SEA](https://nodejs.org/api/single-executable-applications.html)).

Runtime dependencies contain no native addons. node-pty appears only as a dev dependency for tests.

### Windows specifics

**Probe the terminal before Ink starts, because Ink 8's `useInput` drops replies it does not recognize** ([Ink v8.0.0 release](https://github.com/vadimdemedes/ink/releases/tag/v8.0.0)). The probe uses Gemini's sentinel pattern ([terminalCapabilityManager.ts](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/ui/utils/terminalCapabilityManager.ts)). It sends:

- `CSI ? u` for the kitty keyboard protocol.
- `CSI ? 2026 $ p` for synchronized output.
- `CSI ? 2027 $ p` for grapheme clustering.
- OSC 11 for the background color.
- XTVERSION for the terminal's name and version.
- DA1 last, as the end-of-replies marker.

Results are cached per `TERM_PROGRAM` and version.

**Windows Terminal (`WT_SESSION` present).** Use synchronized output, Shift+Enter through the kitty protocol, and the OSC 9;4 progress indicator in the tab and taskbar while any session is busy.

**conhost.** Show a one-time notice recommending Windows Terminal. Make Ctrl+J and `\`+Enter the newline keys. Cap screens at 15 frames per second, since there is no synchronized output.

**Ctrl+C.** In raw mode it arrives as a key. The first press clears the input or closes a dialog; a second press within 800 ms quits.

**Backspace.** The Backspace-arrives-as-`^H` quirk that Claude Code works around on Windows ([Claude Code docs: terminal config](https://code.claude.com/docs/en/terminal-config)) goes into the PTY test suite.

**Clipboard.** Copy uses `Set-Clipboard` through PowerShell, and OSC 52 over SSH.

**Closing the console window.** Node receives SIGHUP. An owner TUI uses part of the roughly ten-second grace period to send `/exit`.

**Backend process.** The hidden console means the backend never sees console Ctrl+C events and never shares the TUI's console input mode.

## (b) UX design: an inline conversation, full-screen workspaces, one keymap

The chat looks like this at 90 columns. Everything above the rule is ordinary scrollback; everything below it is the live region.

```
 CraftBot V1.4.5 · terminal · Main
 You · 14:02
 Find a table for two at 7 tonight and put it in my calendar.
 ▸ 6 actions · 41.2s
 Aria · 14:03
 Booked Sorae for 19:00 and added it to your Personal calendar.
 You · 14:05
 Also text Mia the time.
 ──────────────────────────────────────────────────────────────────────── live region
 ◐ Working · 12.4s                                                       esc stop
   ✓ Search contacts   mia                                                   0.8s
   ◐ Send message      whatsapp                                              3.1s
 ┌ Aria is asking · 1 of 1 ─────────────────────────────────────────────────────────┐
 │ Which Mia should I text?                                                          │
 │ 1 Mia Tan (recommended)   2 Mia Ruiz              tab to choose, or type an answer│
 └───────────────────────────────────────────────────────────────────────────────────┘
 › Ask Aria anything · / commands · @ attach
 Main ◐ · Trip plan ● · effort high · ctx 41% · cache 88% · 1 app · ? help
```

### Screen inventory

| Screen | Opens with | Surface | Layout and behavior | Browser counterpart |
|---|---|---|---|---|
| Splash and connect | launch | inline | One spinner line. After 90 s, an error panel with a retry key and a hint about `craftbot.py stop` | App splash |
| Onboarding | `needsHardOnboarding` in `init` | alt | Step list on the left, form on the right. Provider is a list select, not a wheel. The API key field is masked. Subscription sign-in opens the system browser and the user pastes the code back. The Ollama flow shows check, install, start, pull and test with progress lines. Optional steps are skipped with `s` | OnboardingPage |
| Chat (Main and every chat) | default | inline | Finished transcript above, live region below. Switching session prints a divider plus that session's last 20 messages | Chat |
| Transcript | Ctrl+O | alt | Virtualized full detail: expanded chunks, reasoning, details disclosures. `/` searches. `y` copies a message as Markdown, `r` replies, `[` dumps the conversation to scrollback, `v` opens it in `$EDITOR`. Older pages load through `chat_history` | Expanded chunks, Copy and Reply |
| Sessions | Ctrl+X s, `/sessions` | alt | Main pinned with its "things that happen on their own arrive here" note, then all chats with no Show more, busy and unread glyphs, a filter, and rename, clear, delete and create-skill actions | "Chat & Task" sidebar group |
| Command palette | Ctrl+P | alt overlay | Fuzzy search over screens, commands, skills, sessions, apps and individual settings | none (new) |
| Help | `?` on an empty composer | alt overlay | Generated from the keymap registry for the current context | none (new) |
| Effort | `/effort`, Ctrl+X r | live region overlay | Choices from `reasoning_options_get`, a context bar (amber at 70%, red at 90%), cache hit %, cache expiry countdown. Sends `session_reasoning_set` | ReasoningPicker (same behavior; the browser component itself is untouched) |
| Dashboard | Ctrl+X d | alt | Fixed two-column layout at 120 columns or wider: status and uptime, task stats, a token sparkline, hourly bars, system resources, MCP, skills and integrations counts, model, apps, recent activity. `[` and `]` change the period | Dashboard |
| Memory | Ctrl+X m | alt | Search, list, detail, and a neighbour tree. Kind toggles. Add, edit and delete items. Indexed files as a checkbox tree | Memory page |
| Workspace | Ctrl+X w | alt | Two-pane file manager. `v` marks files, plus copy, cut, paste, rename and delete with confirm. Upload copies from a local path, download saves to a path. Text preview. Open with the OS app (`open_file`) | Workspace page |
| Settings | Ctrl+X `,`, `/settings` | alt | Nine tabs in a left list, form on the right. A "Changed elsewhere · Load latest" hint when another client changes a value. Long text (SKILL.md, MCP JSON, USER.md, SOUL.md, AGENT.md) opens in `$EDITOR` | Settings |
| Credentials | Settings tab | alt | Masked list. Reveal hides itself after 30 s. Copy to clipboard | Credentials |
| Mini Browser | Ctrl+X b, `/browser` | alt | Tabs table (owner, title, URL, state). Stop the agent, close a tab (confirm if the agent is using it), copy a link, install Chromium with a progress log | SessionBrowserPanel |
| Agent Apps, Add Agent App, App build, App view, App settings | Ctrl+X a, `/apps` | alt | Section c | Agent App group and pages |

### Keymap

The research says to adopt the de facto agent-TUI grammar verbatim: `/` commands, Esc, Ctrl+O, Ctrl+T, Ctrl+G, Ctrl+R and `?` ([Claude Code docs: interactive mode](https://code.claude.com/docs/en/interactive-mode); [Gemini keyboard shortcuts](https://geminicli.com/docs/reference/keyboard-shortcuts)). For data screens, use the list-and-drill grammar that lazygit, k9s, taskwarrior-tui and hledger-ui share ([k9s commands](https://k9scli.io/topics/commands/); [hledger-ui](https://hledger.org/hledger-ui.html)).

All keys are data in one registry. The `?` overlay, footer hints and palette read from that registry, so a rebind shows up everywhere, as taskwarrior-tui does ([taskwarrior-tui keybindings](https://kdheepak.com/taskwarrior-tui/keybindings/)). Bare digits and Alt+digit are avoided wherever text input has focus. Alt+digit switches tabs in Windows Terminal, and digit capture has broken Chinese IME candidate selection in Claude Code (report #57759, among the open IME reports in the [claudeissues mirror](https://claudeissues.com/issue/70955-bug-ime-atok-candidate-window-overlaps-input-area-on-windows-terminal)).

| Context | Keys | Action |
|---|---|---|
| Global | Ctrl+P | Command palette |
| Global | Ctrl+X then a letter | Leader key (2 s timeout): `s` sessions, `a` apps, `m` memory, `w` workspace, `d` dashboard, `b` browser, `,` settings, `n` new chat, `e` AI Enhance, `r` effort |
| Global | Ctrl+C | Clear the input or close a dialog; a second press within 800 ms quits |
| Global | Ctrl+L, `?` | Redraw; help (`?` only on an empty composer) |
| Composer | Enter | Send. Sending while a run is busy is allowed: the backend defers the message as a durable trigger, exactly as for the browser |
| Composer | Shift+Enter, Ctrl+J, `\` then Enter | Newline (Ctrl+J and `\` work in every terminal) |
| Composer | Esc | Close a popup; otherwise stop the run (`session_stop`), showing "stopping" until idle |
| Composer | Up and Down on an empty composer, Ctrl+R | Recall the last 50 inputs; search history |
| Composer | Tab, Ctrl+G | Accept a completion or focus the pinned question; edit the draft in `$EDITOR` via `suspendTerminal` |
| Composer | Ctrl+O, Ctrl+T, Ctrl+N | Transcript; to-do panel; new chat |
| Composer | `/`, `@` | Commands and skills autocomplete; attach a local file (path completion) |
| Question box | digits, Enter, `x`, Esc | Choose; submit; dismiss (this interrupts the task, as the browser's X does); give focus back to the composer while the question stays pinned |
| Screens | j/k or arrows, Enter or l, Esc or h, `q` | Move; open or drill in; go back one level; close the screen and return to the chat |
| Screens | `/`, `a`, `e`, `d`, `r`, g/G, Tab, `[` `]` | Filter; add; edit; delete with confirm; refresh; top or bottom; next pane; previous or next tab |
| Transcript | `/` n N, `y`, `r`, `[`, `v` | Search; copy as Markdown; reply; dump to scrollback; open in `$EDITOR` |

### Composer

**The composer is the biggest single build item, sized like Gemini's.** Its text buffer distinguishes logical lines from visual lines. Cursor moves are grapheme-aware, widths come from `string-width` (ambiguous characters narrow), and word motion uses `Intl.Segmenter`, which also segments Japanese and Chinese. After every render, Ink's `useCursor` puts the real cursor at the caret so IME preedit and candidate windows follow the text ([Ink README](https://github.com/vadimdemedes/ink)).

**Paste.** Bracketed paste arrives through `usePaste`. A paste over 800 characters or three lines collapses into a `[Pasted text #1 · 120 lines]` chip that can be expanded and edited in place. Users of both Claude Code and opencode have asked loudly for that ([#3412](https://github.com/anthropics/claude-code/issues/3412); [opencode #8501](https://github.com/anomalyco/opencode/issues/8501)). Invisible Unicode (tag characters, bidi controls, zero-width spaces) is stripped on send, with a notice, as Claude Code does ([Claude Code docs: interactive mode](https://code.claude.com/docs/en/interactive-mode)).

**Attachments.** `@path` with path completion attaches a file and shows a chip with name and size. A pasted path that points at an existing file turns into an attachment offer, which covers drag-and-drop into Windows Terminal. Files up to 50 MB are inlined as base64, larger ones are pre-uploaded to `/api/chat-attachments/upload`, and the browser's limits of 10 files and 200 MB carry over.

**Slash autocomplete.** It merges `command_list` and the enabled skills, grouped "Commands" and "Skills" as in the browser. Matching is alias-aware and anchored to word starts.

**Other composer behavior.** AI Enhance replaces the draft, with the browser's 30-second timeout. Drafts persist per session. A reply target, chosen from the transcript, appears as a quoted line above the input. Single newlines in agent Markdown render as line breaks, to match the browser's `remark-breaks`.

### Agent activity, questions, to-dos, sub-agents and scheduled runs

**Activity follows the browser's model exactly.** Consecutive tool calls and reasoning between two messages form a chunk. While a chunk runs, the live region shows one "Working" row with an elapsed timer and the chunk's last three action rows. Each row has a status glyph, a human name from `actionNames.ts`, a one-line preview of the main input, and a timer while running. When the chunk settles, it is written to scrollback as a single line: `▸ 6 actions · 41.2s`, or `✗ 1 failed` if something errored. Chunks that contain only `send_message` actions print nothing, and the browser's anti-flicker rules for the Working row carry over unchanged, including the 5-second grace period after a run goes idle ([Chat.tsx](../app/ui_layer/browser/frontend/src/components/Chat/Chat.tsx)). Full detail lives in the Ctrl+O transcript.

**Visibility is configurable per category**, because users want both more and less detail and one global verbose switch fails both groups ([codex #18396](https://github.com/openai/codex/issues/18396); [#8477](https://github.com/anthropics/claude-code/issues/8477)). Reasoning, tool rows and sub-agent rows each have their own setting: hidden, collapsed or shown.

**Questions.** An agent question is pinned in a box above the composer, oldest first, with a "1 of N" badge. The first option is marked "(recommended)". The user can choose an option or simply type: a normal message answers the shown question, as in the browser. Pressing Esc collapses the box but leaves it pinned, so a question can never steal typed input, a failure Claude Code shipped ([#75360](https://github.com/anthropics/claude-code/issues/75360)). Limit prompts (Continue or Stop) render the same way, using their existing option values.

**To-dos.** Ctrl+T toggles a checklist of up to five rows plus "+N more". The TUI parses it from the latest `update_todos` action input, which the browser only summarizes as "3/5 done", so no backend change is needed. The status line also shows `todo 3/5`.

**Sub-agents.** These are the TUI's one addition beyond the browser. Their `sub_*` event streams already reach every client, but nothing on the wire links a stream to its parent. A capability-gated `subagent_link {subId, parentSessionId, name}` message lets the TUI nest a "Sub-agent walk_verify · 14 actions" row under the parent's chunk, with drill-in from the transcript ([subagent/manager.py](../app/subagent/manager.py)).

**Scheduled and proactive runs.** These report into Main, as the browser's Main tooltip promises. The status line always shows Main's busy or unread glyph, whichever session is open. When something happens in a session that is not open (a question, a finished run), the TUI rings the bell or sends an OSC 9 notification ([Claude Code docs: terminal config](https://code.claude.com/docs/en/terminal-config)). Schedules themselves live in Settings > Proactive: a task table (name, frequency, next run, enabled), the add and edit form, the heartbeat toggle and the planners.

### Mini Browser and Generative UI

**These are the two places where the terminal edition changes what the agent itself is told.** That is why the change happens once at boot, never per turn, so the system prompt stays cache-stable.

**Mini Browser.** It keeps working as the agent's tool, headless by default ([mini_browser/config.py](../app/mini_browser/config.py)). The user sees a "Browsing · 2 tabs · checkout.example.com" row while it works, and the Browser screen. The current capability prompt tells the agent that "the user can watch your tabs live and take control of them" in the chat's browser panel ([agent_base.py](../app/agent_base.py)). That is false in a terminal, so the terminal edition swaps in a static variant: the user cannot see the browser, and a CAPTCHA or sign-in is a question to ask in chat. How the user takes control of a tab is an open decision. A headed Chromium window for that one tab is recommended over a Sixel live view.

**Generative UI.** `render_ui` produces sandboxed HTML pages that rely on the browser host's postMessage bridge and Chart.js, three.js and Leaflet bundles inlined by a Vite plugin ([render_ui.py](../app/data/action/render_ui.py); [GenerativeUI.tsx](../app/ui_layer/browser/frontend/src/components/GenerativeUI/GenerativeUI.tsx)). No terminal can run those pages. The terminal edition therefore removes `render_ui` from the action space at boot. Its static prompt asks for Markdown tables narrower than 100 columns. Artifacts created earlier in the browser edition show as a one-line card: `▣ Interactive output · Weather dashboard · rev 3 · open it in the browser edition`.

### Status line, notifications, theme, languages and accessibility

**Status line.** It carries the active session, glyphs for other busy or unread sessions, effort, context %, cache %, running apps, the connection state (the browser's "busy" banner becomes a status segment) and `? help`. The context and cache readout is the feature users revolted over when Codex removed it ([codex #23794](https://github.com/openai/codex/issues/23794)).

**Toasts** stack at most two lines above the status line. Like the browser's, they can be replaced in place by key and can stay until dismissed.

**Terminal title.** It shows `CraftBot · Main ◐ · 1 needs you`.

**Colors.** The palette derives from the browser's tokens: neutral grays, with brand orange #FF4F18 kept for the prompt marker and the focused row. Light or dark comes from the OSC 11 probe. Color depth downsamples from truecolor to 256 to 16 colors through `supports-color`. `NO_COLOR` is honored, and an ANSI-16 theme uses the terminal's own palette ([clig.dev](https://clig.dev/)). Meaning always travels in text and glyphs as well as color.

**Languages.** All seven UI languages reuse the browser's fourteen i18next namespaces read-only. Terminal-only strings (key hints, terminal notices) live in a new `tui` namespace under `app/ui_layer/terminal/locales/`, with a key-parity check, as Hermes runs in its `npm run check` ([hermes-agent ui-tui package.json](https://github.com/NousResearch/hermes-agent/blob/main/ui-tui/package.json)). The language comes from `general.ui_language` through `settings_get` and switches live on `settings_update`.

**Glyphs.** Status glyphs are restricted to box drawing, block elements, braille and geometric shapes (● ○ ◐ ▸ ✓ ✗). A setting switches borders to ASCII for CJK fonts that draw box-drawing characters double-width.

**Personality** is limited to the ASCII logo banner, printed once per launch.

### What is consciously dropped or handed off

| Browser feature | Terminal treatment |
|---|---|
| Generative UI outputs (`render_ui` iframes) | Removed from the terminal edition's action space at boot; earlier artifacts show as a one-line card |
| Mini Browser live screencast, agent cursor, take control | Text status and the Browser screen; take control is an open decision |
| Memory force-directed graph | Search, list, detail and neighbour tree |
| Dashboard drag-and-resize grid and named layouts | One fixed layout |
| Voice input (Web Speech API) | Dropped |
| Image, PDF and avatar previews | Path and size, opened with the OS default app through the existing `open_file` |
| WhatsApp QR image | Drawn as a Unicode half-block QR in the connect flow |
| OAuth sign-ins (integrations, model subscriptions) | System browser, then paste the code back |
| driver.js tour, mascots, typewriter titles | A dismissible first-run card listing the eight keys that matter; nothing animated |
| Drag reorder, resize seams, drag-and-drop upload | Keyboard move up and down, width tiers, attach by path |
| Theme color pickers, layout silhouettes, SVGL logos | Hex fields, named options, plain text names |
| Hidden Screen page (GUI footage) | Dropped (it is unreachable from the browser's navigation too) |

## (c) Agent Apps in the terminal: every view bound to a declared op

**An existing app's web UI cannot come along, but its data and verbs can.** The scan of the 12 installed apps found that every one of their 5,376 op parameters has a description, every op uses the `http` executor, and 2 to 103 read ops per app need no parameters. Those read ops are ready-made sources for read views ([read-only scan of installed apps' operations.json](../agent_file_system/workspace/agent_app)). Two facts set the shape of the design.

The first is that **the agent already sees each app as ops plus schema text**, never as pixels. It reads the `operations_block` and `schema_block` built from `GET /api/_a2app/describe` ([agent_view.py](../app/agent_app/agent_view.py)). A terminal view built from the same sources shows the user exactly what the agent operates.

The second is a warning from generated admin UIs. Django's admin docs say the admin is "not intended for building your entire front end around" and that a "process-centric interface" needs its own views ([Django admin docs](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/)). react-admin says flatly not to use its guessers in production ([react-admin ListGuesser](https://marmelab.com/react-admin/ListGuesser.html)). That matches the owner's rule that consumer agent apps must be apps, not databases.

### Two layers, and no app code in the TUI

**Layer 1 is generated, needs no per-app work, and is the standard renderer for any app without declared views.** It is built from four parts:

- **Home.** The first of `home.summary`, `app.status`, `today.get` or `app.guide` that exists. By convention 3, 6, 1 and 9 apps respectively declare these.
- **Areas and the op palette.** Areas are op-name prefixes, grouped the same way `operations_block` groups them. The `:` key opens a palette of every op as `area.verb  label  [destructive]`.
- **Op forms** generated from typed parameters.
- **Read views** for read ops that need no parameters, plus a read-only Records browser over describe's entities and a Triggers and Requests view.

Results render by structure:

- **An array of objects becomes a table.** Name and title fields come first, ids are hidden, and columns carry priorities that drop as the terminal narrows. This is the Kubernetes `additionalPrinterColumns` priority model that k9s uses ([Kubernetes CRD docs](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/)).
- **An object of scalars becomes a key-value grid.**
- **An array of date and value pairs becomes a sparkline.**
- **Anything else** gets a raw JSON toggle on `J`.

The Records browser is read-only on purpose. Raw collection writes skip each app's business rules, so writes go only through ops.

**Layer 2 is a declared `views.json`.** It is a catalog-based, semantic view manifest, the pattern A2UI and json-render converged on: a flat list of typed components, data bound by JSON Pointer, and actions that name operations rather than carry code ([A2UI v0.9](https://a2ui.org/specification/v0.9-a2ui/); [json-render](https://github.com/vercel-labs/json-render)). CraftBot should own this spec rather than depend on json-render. `@json-render/ink` still peers on `ink ^6.0.0` ([@json-render/ink](https://github.com/vercel-labs/json-render/tree/main/packages/ink)), and it knows nothing about ops.

HTML-based protocols are ruled out as the shared definition. Their only terminal story is a text fallback, which is exactly what Codex CLI shows for MCP Apps ([Daniel Vaughan](https://codex.danielvaughan.com/2026/07/31/mcp-2026-07-28-final-specification-stateless-core-tasks-apps-codex-cli-migration/)).

There is deliberately no Layer 3. Apps never ship JavaScript that runs inside the TUI process, which removes a whole class of security and versioning problems.

```json
{
  "viewsVersion": 1,
  "home": "month",
  "screens": [
    {
      "id": "month", "title": "This month",
      "source": { "op": "summary.month" },
      "refreshOn": ["expenses", "budgets"],
      "blocks": [
        { "type": "metrics", "items": [
          { "label": "Spent", "value": "/total", "format": "money:/currency" },
          { "label": "Budget left", "value": "/budget/left", "format": "money:/currency" },
          { "label": "Used", "value": "/budget/used_pct", "format": "percent" } ] },
        { "type": "bars", "series": "/daily", "x": "date", "y": "total" },
        { "type": "table", "title": "Biggest", "rows": "/biggest", "rowKey": "id",
          "columns": [
            { "field": "title", "priority": 0 },
            { "field": "amount", "format": "money:/currency", "priority": 0 },
            { "field": "date", "format": "date", "priority": 1 } ],
          "rowActions": [
            { "key": "d", "op": "expenses.delete", "params": { "expense_id": "$row.id" } } ] }
      ],
      "actions": [ { "key": "a", "op": "expenses.add" } ]
    }
  ]
}
```

The catalog is small and semantic: `metrics`, `keyvalue`, `table`, `list`, `bars`, `line`, `sparkline`, `candles`, `gauge`, `timeline`, `tree`, `text`, `opform` and `tabs`. Each component decides its own terminal presentation. Lines and sparklines use braille, falling back to blocks. Bars use block characters. Candles get a custom braille renderer, because no maintained Ink candlestick component exists. Numbers are always printed next to every mark. A screen rendered from the example above looks like this:

```
 Expenses tracker   running · :3111 · as owner                    your AI agent ● idle
 [This month]  Expenses  Budgets  Insights  Recurring  │  Ops  Records  Requests
 ─────────────────────────────────────────────────────────────────────────────────
 Spent ¥48,210      Budget left ¥21,790      Used 69%  ██████▉░░░
 Daily  ▁▂▅▃▇▂▁▃▅▆▂▁▃▄▂▁▂
 Biggest
   Groceries          ¥12,400   Oct 19
   Train pass          ¥9,800   Oct 01
   Dinner              ¥6,300   Oct 12
 ─────────────────────────────────────────────────────────────────────────────────
 a add expense   d delete   / filter   : all ops   c ask your AI agent   ? help
```

### Forms, destructive confirmation, live refresh and identity

**Op forms map parameter types and formats to widgets:**

- `string` becomes a text field, or a multiline field when its format is `multiline`.
- `number` becomes a validated numeric field.
- `boolean` becomes a toggle, and `enum` becomes a select.
- Date formats parse the same relative dates the CLI's `data` command already coerces.
- `ref:<entity>` opens a record picker fed by a read view.
- `json` opens `$EDITOR` and validates the result before submit.
- `secret` is masked and never echoed.

All errors show together on submit, as schemaui does ([schemaui](https://docs.rs/schemaui/latest/schemaui/)).

**Destructive confirmation.** Any op flagged `destructive` opens a confirm box before it runs. The box shows the op's label, the key parameters, and either the op's `confirm` sentence or its description. Cancel is the default, `y` confirms, and ops marked `confirm.typed` make the user type the record's label. Research OS's guarded `demo.reset`, which takes phrase, fingerprint and `confirm` parameters, stays an ordinary form behind the same box.

**Live refresh.** The TUI subscribes to PocketBase realtime over SSE from Node for every collection a screen depends on, in one subscribe request. It debounces 300 ms, then re-fetches that screen's read ops. This is the same realtime mechanism the kit's `useCollection` uses ([kit pb/hooks.ts](../agent-app/kit/src/pb/hooks.ts)).

**Identity.** The TUI reuses `agent-app/tools/src/lib/project.ts` and `lib/schema.ts` inside its bundle: the same agent token, the same cached superuser session, the same shadow-port redirect. The terminal and the agent's CLI therefore can never disagree ([project.ts](../agent-app/tools/src/lib/project.ts)). The TUI sends its own agent id (`craftbot-terminal`) and shows only the `message` of error envelopes, never the hints written for the AI. Triggers fired by a person in the terminal are recorded as `fired_by: terminal`, a new value next to `ui`, `hook` and `cli`. That keeps a person distinguishable from the agent. Multi-user apps run as the owner in v1, labeled "as owner" in the header.

### Creation, build view, launch and the per-app chat

**The Apps screen** lists every app with a status glyph (creating, launching, running, stopping, stopped, error). Keys: Enter opens, `l` launches, `s` stops, `d` deletes with confirm (only while stopped), `t` sets the theme and `p` opens app settings. Launching starts PocketBase and nothing else, because no browser is involved.

**The Add Agent App screen** has three tabs:

- **Marketplace:** search, tag filters, "Installed ×N" badges, setup questions as a form.
- **Create:** the wizard.
- **Import:** a GitHub URL or local path, or a ZIP path uploaded to `/api/agent-app/import`, with progress lines from `agent_app_import_progress`.

The wizard keeps its three backend steps ([wizard.py](../app/agent_app/wizard.py)). CONFIGURE asks for name, description, icon (a lucide name), access mode and reference files by path, uploaded to `/api/agent-app/stage`. Terminal-surface apps get terminal layout presets (`dashboard`, `list-detail`, `workflow`) in place of the eight web silhouettes. INTERVIEW renders each `{question, why, multiSelect, options}` as a select or multi-select with free text, plus "Question N of M" and skip. CREATING moves straight to the build view.

**The build view** is the most terminal-friendly page in the product. It shows a progress bar and current step from `agent_app_todos`, "built so far" counts of collections, routes and screens, and a paced feed of `agent_app_build_event` items with kind glyphs. The browser's code animation becomes the last few lines of the file being written, taken from the event's `snippet` ([construction_events.py](../app/agent_app/construction_events.py)).

**The app view** splits into the app's screens and a chat pane bound to `project.sessionId`. The pane sits on the right at 120 columns or wider and on the bottom below that, and `c` toggles it. Its placeholder says "Ask your AI agent about this app"; app UI copy never says CraftBot. Shift+C pops the conversation out into the inline chat for that session. Theme mapping uses the app's stored pack swatches. The accent drives focus, selection and headings, chosen from the pack's light or dark mode to match the probed terminal background and contrast-checked against it. The terminal's own background is never painted.

### Spec, template, creator skill and verifier changes

| Artifact | Change |
|---|---|
| [operations.schema.json](../agent-app/spec/operations.schema.json) | Add op `readOnly` (formalizing what netsentry already uses ad hoc), `label`, `returns` (record, list, summary, series or job, plus key fields) and optional `confirm`. Add param `label` and `format` (date, datetime, money, percent, ref:<entity>, json, multiline, secret). Lists stay `string` with `format: json` |
| [validate.ts](../agent-app/tools/src/commands/validate.ts) | `validateOps` checks param shapes and rejects unknown keys, so newsletter's `array` and netsentry's `idempotent` now fail the gate. GET ops must be `readOnly`. New `views` step. The types and vite build steps become surface-aware |
| `agent-app/spec/views.schema.json` (new) | The schema above. Gate rules: sources must be `readOnly` ops; actions must name declared ops; `$row` and pointer bindings must resolve against op-smoke results; no rendered line may overflow at 80 and 120 columns |
| `manifest.json` (blueprint and installed apps) | New `surfaces`: `["web"]`, `["terminal"]` or both. Terminal-only pipelines skip the frontend install and build |
| `agent-app/view/` (new package) | The catalog renderer in Ink, shared by the TUI and a new `agent-app view <dir> [screen] --width N` command that prints a screen as text. The agent gets a text snapshot of exactly what the user sees |
| [verify.ts](../agent-app/tools/src/commands/verify.ts) and [walk_verify.py](../app/subagent/definitions/walk_verify.py) | For terminal surfaces: render every screen against the dev instance and walk the requirements through `agent-app view` plus `agent-app run`, with no Chromium |
| [blueprint](../agent-app/blueprint) | Ships `views.json` with a Home screen bound to a standard `home.summary` read op. The terminal variant has no `frontend/` and a static `pb_public/index.html` saying "This app runs in your terminal. Ask your AI agent to add a web view." |
| Kit realtime and triggers | Add `fired_by: terminal` |
| [agent-app-creator SKILL.md](../skills/agent-app-creator/SKILL.md), STANDARDS, VERIFY | A terminal-surface branch. "Every feature is an op" becomes a rule, CRUD included. views.json design rules: a dense home dashboard first, priorities on every column, labels written for people |
| agent-app-modify and agent-app-manager skills | Maintain `views.json` with every change. The manager reads `agent-app view` output before acting |
| [GLOBAL_AGENT_APP.md](../agent_file_system/GLOBAL_AGENT_APP.md) and its template copy | Terminal rules: no emoji, plain glyphs, compact layout, "your AI agent" in copy |
| [wizard.py](../app/agent_app/wizard.py), [manager.py](../app/agent_app/manager.py), [runner.py](../app/agent_app/runner.py) | Accept `surfaces`, use terminal layout presets and an interview prompt variant, and run pipelines that honor surfaces. The browser never sends `surfaces`, so its path is unchanged |

## (d) Backend: an edition seam, not a BrowserAdapter teardown

**The required backend change is small because the terminal speaks the browser's protocol.** Moving chat and activity persistence out of the adapter is not recommended. `BrowserChatComponent.append_message` writes into SQLite on one worker thread and then broadcasts ([browser_adapter.py](../app/ui_layer/adapters/browser_adapter.py)). Separating the two would change ordering guarantees the browser relies on, and the TUI gains nothing from it.

Each change below is verified by a golden WebSocket transcript: scripted scenarios recorded before Phase 0 and compared byte for byte afterwards. The same transcripts later become the TUI's fake backend.

| # | Change | Files | Browser impact | Proof |
|---|---|---|---|---|
| 1 | Edition seam. `CRAFTBOT_FRONTEND` (browser or terminal) is read once in `AgentBase.__init__`, so `_interface_mode` never starts as `"cli"` and never changes during the process | [agent_base.py](../app/agent_base.py), [app/main.py](../app/main.py) | Role prompt text identical | Snapshot test of the browser prompt; the terminal prompt is identical across 50 turns |
| 2 | Static terminal capability prompt: file sharing by path, the Mini Browser variant, reply-format guidance | agent_base.py `_get_interface_capabilities_prompt` | None | Snapshot test |
| 3 | `render_ui` removed from the action space at boot in the terminal edition | action set registration ([render_ui.py](../app/data/action/render_ui.py) stays) | None | Test of the action list per edition |
| 4 | Web UI not served in the terminal edition (`/assets` and the SPA catch-all off); token, APIs and bridge stay | [browser_adapter.py](../app/ui_layer/adapters/browser_adapter.py) static routes | None | Route test |
| 5 | `client_hello` and a per-channel capability set; capability-gated `subagent_link` | browser_adapter.py dispatch, [ws_channel.py](../app/ui_layer/adapters/ws_channel.py), [subagent/manager.py](../app/subagent/manager.py) | None (the browser never says hello) | Golden transcript |
| 6 | `AgentAppHost`: manager construction, cleanup, watchdog, auto-launch, singleton, todo hook, construction hooks and bridge route registration move from `BrowserAdapter.__init__` into `app/agent_app/host.py`, called by `AgentBase.run()`. The adapter only registers its broadcast callbacks | browser_adapter.py, new host.py | None intended | Golden transcript, a bootstrap test (one manager, auto-launch called once, routes present), an Agent App launch test |
| 7 | `--tui` foreground topology in run.py (hidden console, log file, TUI spawn, graceful `/exit`); `craftbot.py tui`; install mode `tui` | [run.py](../run.py), [craftbot.py](../craftbot.py), [installer/metadata.py](../installer/metadata.py) | None | Launcher tests |
| 8 | Agent App `surfaces` in the wizard and pipelines (Phase 4) | wizard.py, manager.py, runner.py | None | Unit tests |

Change 6 is the one that matches the brief's example. Do it in Phase 0 for three reasons. Agent Apps should not depend on a class named Browser. The headless end-to-end test harness, which boots with no interface ([helpers.py](../tests/e2e/_harness/helpers.py)), gains Agent Apps. And a future edition without a web server becomes possible. Keep it strictly a relocation of the bootstrap, so the golden transcript can prove nothing moved in behavior.

Renaming `BrowserAdapter` and `BrowserInterface` to neutral names is left out on purpose. It has no behavioral value and a large diff surface (open decision 12).

## (e) Removal: the line-based CLI leaves 27 files

| File | Change |
|---|---|
| [app/cli/\_\_init\_\_.py](../app/cli/__init__.py), [interface.py](../app/cli/interface.py), [formatter.py](../app/cli/formatter.py), [onboarding.py](../app/cli/onboarding.py) | Delete all four. The ASCII logo and palette from formatter.py move into the TUI banner as data first. onboarding.py is already dead code that nothing imports |
| [app/ui_layer/adapters/cli_adapter.py](../app/ui_layer/adapters/cli_adapter.py) | Delete |
| [app/ui_layer/adapters/\_\_init\_\_.py](../app/ui_layer/adapters/__init__.py) | Remove the `CLIAdapter` export (lines 4-7) |
| [app/agent_base.py](../app/agent_base.py) | Remove the `"cli"` default for `_interface_mode` (lines 380-382). Replace the `interface_mode` parameter and the `CLIInterface` branch in `run()` (lines 4383-4440). Delete the CLI-only "[OK] Ready!" print (4410-4412) and the CLI step format in `boot()` (4208-4210), together with the `browser_ui` parameter that only chose between the two formats |
| [app/main.py](../app/main.py) | Remove `--cli` and `--browser` parsing (lines 177-181) and the interface-mode selection (291-295) |
| [main.py](../main.py) (repo root) | Remove the "(CLI Mode)" banner and its "Type '/exit'" lines (126-135) |
| [run.py](../run.py) | Remove `--cli` from the docstring (lines 1-19), `cli_mode` and the `browser_mode = not cli_mode` branching (1499-1520), and the foreground CLI launcher `launch_agent()` (1300-1380). Port freeing (1576-1598) now runs for both editions. Add `--tui` |
| [craftbot.py](../craftbot.py) | Replace every `--cli` passthrough and check (lines 590, 670, 687, 749, 755) and the mode map (1613, 1951) with `browser` or `tui`. A stored `cli` mode is discarded and re-asked on repair, with no mapping |
| [installer/metadata.py](../installer/metadata.py) | The mode values become `browser` and `tui` (lines 60-68) |
| [app/ui_layer/commands/builtin/menu.py](../app/ui_layer/commands/builtin/menu.py) | Remove the `adapter_id == "cli"` branch (lines 33-38) |
| [app/ui_layer/controller/ui_controller.py](../app/ui_layer/controller/ui_controller.py) | Fix the docstring example that names the CLI adapter (line 69) |
| [app/mini_browser/bridge.py](../app/mini_browser/bridge.py) | Fix the docstring's "CLI mode" (line 6) |
| [install.py](../install.py) | Replace the CLI mention (line 16) |
| [README.md](../README.md) | Replace "Browser interface and CLI support" (line 52) and the `python run.py --cli` section with its "no Node.js needed" line (146-148) with the terminal edition |
| README.cn, .de, .es, .fr, .ja, .ko, .pt-BR, .zh-TW | Line 160 in each of the 8 translations, same change |
| [tests/test_mini_browser_agent_integration.py](../tests/test_mini_browser_agent_integration.py) | Line 1009 sets `"cli"`; change it to `"terminal"` and assert the terminal Mini Browser prompt |
| [tests/e2e/_harness/helpers.py](../tests/e2e/_harness/helpers.py) | Drop the removed `browser_ui=` argument from the `boot()` call |
| `app/tui/__pycache__/` | Delete this stale leftover of the Textual TUI removed in 2f6f6e99 |

Nothing in requirements needs to change: colorama is only a transitive pin. No test imports `app.cli` or `CLIAdapter`.

## (f) Plan: six phases, each closed by a test on Windows

The new package lives at `app/ui_layer/terminal/`, alongside the browser frontend:

- `package.json`: ink 8.0.x, react 19.3.x, @reduxjs/toolkit 2, react-redux 9, i18next 23, react-i18next 14, ws, string-width 8, marked 18, lowlight 3, supports-color, supports-hyperlinks.
- `build.mjs`: esbuild, the module swaps, the devtools alias and the `createRequire` banner.
- `tsconfig.json`: strict, with read-only paths into the browser frontend.
- `src/main.tsx`
- `src/platform/`: the four swapped modules.
- `src/transport/`: SocketClient and the hello message.
- `src/store/`
- `src/caps/`: terminal probe, clipboard, notifications, theme.
- `src/keymap/`
- `src/input/`: TextBuffer, Composer, paste, history.
- `src/render/`: Markdown, tables, code, the transcript writer, width.
- `src/chat/`
- `src/screens/`
- `src/ui/`: VirtualList, Form, Select, Confirm, Table, Toasts, charts.
- `locales/<lang>/tui.json`
- `test/`

A typecheck gate (`tsc --noEmit`) runs from the first commit, because the browser frontend's only static gate is tsc and its `npm run lint` does not work.

Four verification rules apply to every phase:

- **Python changes load only after a CraftBot restart**, so every backend acceptance run begins with one.
- **Mutating tests run against a scratch `CRAFTBOT_HOME`, never against the owner's real agent state or live apps.**
- **Each phase re-runs the golden WebSocket transcript and the browser's four Playwright suites**, from PowerShell with an uppercase `C:` path.
- **Every log review checks `[CACHE METRICS]` and `[SESSION CACHE]`**, so no phase lowers the cache hit rate.

| Phase and milestone | Build | Tests and verification |
|---|---|---|
| **P0 Backend seam and CLI deletion.** `--cli` is gone, browser frames are byte-identical, and `python run.py --tui` boots a terminal-edition backend that logs to a file and launches the bundle | Changes 1 to 7 from section d; the full removal list; golden transcript recorder | New `tests/test_ws_golden_transcript.py`, `tests/test_edition_prompt.py` and `tests/test_agent_app_host.py`. The existing `test_ws_auth`, `test_ws_channel`, `test_ws_lanes`, `test_resource_changes`, `test_ui_event_delivery` and `test_browser_ui_buffers` pass. The browser walkthrough after a restart and the Playwright suites pass |
| **P1 Walking skeleton.** On Windows Terminal and conhost, a user can onboard, chat in Main and a new chat, watch activity, stop with Esc, answer a pinned question, switch sessions, and type Japanese with the IME window at the caret | Three spikes first: the two-root alt-screen handoff, slice import with module swaps, IME caret placement. Then transport, store, terminal probe, keymap, TextBuffer and Composer, transcript writer, live region, question box, status line, Onboarding and Sessions screens | vitest 5 unit tests with fast-check properties: random CJK, emoji and RTL strings at random widths must never exceed `columns`. A Gemini-style `@xterm/headless` 6 screen harness with text snapshots at 80 and 120 columns ([gemini-cli test-utils/render.tsx](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/test-utils/render.tsx)). A fake backend that replays the P0 golden transcripts. A node-pty suite on ConPTY for Ctrl+C, Esc, paste and resize, run with `CI=false` ([npm: node-pty](https://www.npmjs.com/package/node-pty)) |
| **P2 Agent feature parity.** Every screen in section b except Agent Apps works in all 7 languages, plus plain mode, notifications and the sub-agent tree | Transcript, palette, help, effort, todos, attachments, enhance, Dashboard, Memory, Workspace, Settings (9 tabs), Integrations flows (system-browser OAuth, token, half-block QR), Credentials, Mini Browser screen, theme, `tui` locales; backend `subagent_link` | Per-screen snapshots for 7 locales at 3 widths. The i18n key-parity script. PTY flows against a real backend in a scratch home: settings round trip, workspace upload and download, integration connect with the browser-open step stubbed. Golden transcript re-run. Acceptance checklist taken row by row from the browser inventory |
| **P3 Agent Apps host with generated views.** Every installed app's shape opens in the terminal with Home, ops palette, forms, read views, records, triggers, chat pane, live refresh and destructive confirm. Create, import, marketplace, build view, launch, stop, delete and settings all work | `src/screens/apps/*`; reuse of `agent-app/tools/src/lib/project.ts` and `schema.ts`; SSE realtime client; result renderer | Fixture apps only (the blueprint plus an expenses-like fixture): snapshot of every generated view, an SSE refresh test, a confirm-box test, and a sweep of every read op and screen on an empty, unseeded database |
| **P4 Agent App spec for the terminal.** The agent builds a terminal-surface app end to end with no Chromium: scaffold, ops plus views.json, gate, terminal verify, terminal walk-verify, promote. `agent-app view` output equals the TUI screen | operations and views schemas, validate.ts rules, `agent-app/view/`, the `view` command, verify and walk_verify terminal paths, blueprint variant, wizard and pipeline `surfaces`, skill and GLOBAL_AGENT_APP.md updates | validate.ts unit tests for each new rule, including that the 12 installed apps' current drift now fails as specified. Golden `view` outputs. A terminal walk-verify run on a fixture requirements file. A check that the browser host shows a terminal-only app's static notice page unchanged |
| **P5 Hardening and release.** A 10,000-message session holds 30 fps with flat memory; resize storms, tmux, SSH and screen-reader mode pass; the managed install ships the bundle; the owner accepts | Performance work, packaging in the installer, READMEs in 9 languages, install metadata, first-run card | A PTY matrix on windows-latest and ubuntu-latest, a performance benchmark script, a manual matrix (Windows Terminal, conhost, VS Code terminal, Japanese MS-IME, ATOK, Microsoft Pinyin, Korean IME) |

A later P6 is optional, and each item is the owner's call: a fullscreen chat renderer behind `/tui fullscreen` built on the existing VirtualList, mouse support through a raw SGR parser, Sixel and kitty images for app charts and Mini Browser frames, and a terminal attaching to a browser-edition backend.

### Risks

| Risk | Mitigation |
|---|---|
| The two-root handoff misbehaves on ConPTY or conhost | Phase 1 spike on day one; the contingency is Claude Code's single fullscreen root with dump-to-scrollback and the transcript printed on exit |
| Ink 8 fully clears frames on Windows | Live region capped at 40% of rows; screens render only on change; Windows Terminal recommended at first run |
| IME regressions; Claude Code still has open candidate-window and digit-capture bugs ([claudeissues #70955](https://claudeissues.com/issue/70955-bug-ime-atok-candidate-window-overlaps-input-area-on-windows-terminal)) | `useCursor` on every frame, no digit bindings while text has focus, a manual IME matrix per release |
| Ink majors every 4 to 6 months, and upstream refuses AI-generated pull requests | Exact pins, quarterly upgrades behind the PTY suite, local patches with human-written upstream issues |
| A browser slice change breaks the TUI build | The shared typecheck gate; copy the slice instead of editing it |
| ink-testing-library 4.0.0 is untested with Ink 8 ([npm](https://www.npmjs.com/package/ink-testing-library)) | The xterm-headless harness is the primary component test tool |
| Dropping `render_ui` makes the agent less expressive in the terminal | Prompt guidance toward narrow Markdown tables; open decision 4 |
| Mini Browser CAPTCHAs and sign-ins stall without a visual surface | Prompt variant that routes the problem to chat; open decision 5 |
| Generated views read as databases for the 12 existing apps | views.json backfill (open decision 7) |
| CJK fonts draw box-drawing characters double width | ASCII border setting; width tests under Japanese, Chinese and Korean fonts |
| `run.py --tui` would kill a running service backend while freeing ports | Detect the service's PID file and refuse with a message pointing to `craftbot.py tui` |

### Open decisions for the owner

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Names | `--tui` / `--terminal`; `craftbot.py tui`; install mode `tui`; env var `CRAFTBOT_FRONTEND` | `--tui`, `craftbot.py tui`, `tui`, `CRAFTBOT_FRONTEND` |
| 2 | Coexistence with a running backend, and cross-edition attach | Refuse, attach, or attach across editions | Refuse in the foreground topology, attach in the service topology, no cross-edition attach in v1 |
| 3 | Default renderer for the chat | Inline, fullscreen, or auto | Inline; fullscreen only as a P6 opt-in |
| 4 | Generative UI in the terminal | Remove `render_ui`, or build a standalone page served for "open in system browser" | Remove |
| 5 | Mini Browser take control | Headed Chromium window for that tab, Sixel live view, or drop | Headed window |
| 6 | Surfaces for apps created in the terminal edition | Terminal only, or web plus terminal | Terminal only, with the static notice page for the browser edition |
| 7 | `views.json` | Mandatory for new apps? Backfill the 12 existing apps? | Mandatory; backfill app by app through agent missions, with user data untouched |
| 8 | Multi-user apps in the terminal | Act as owner, or require a PocketBase login | Owner, labeled, in v1 |
| 9 | walk_verify for web apps while running the terminal edition | Keep headless Chromium, or disable | Keep (it is invisible to the user) |
| 10 | Hard-coded English in backend payloads ("Unknown command", "[DEBUG ERROR]", command help) | Leave, or add `tui()` keys (this also changes browser text) | Leave; treat it as a separate browser-visible change |
| 11 | AGENT.md lifecycle text for terminal-surface apps | Minimal sentence edits now, or later | Needs the owner's approval; minimal edits on the current version only |
| 12 | Rename BrowserAdapter and BrowserInterface | Now or never | Not in this project |
| 13 | Personality | ASCII banner once, a companion, or nothing | Banner once, quiet spinner, a toggle to hide it |

## Conclusion

The terminal edition is cheaper than the brief assumes, because CraftBot already built the expensive half without noticing. Its browser adapter is a real multi-client server, so the terminal does not need a backend rewrite, only a seam that tells the agent, once at boot, which kind of screen the user is looking at. The expensive half is the opposite of what a feature list suggests. The composer, the scrollback discipline and Windows console behavior decide whether people keep the product, and the record of every competitor shows these are where years of issues accumulate. Budget the first phases around integrity: caret-true IME, copy that yields source text, no full clears in the chat. Treat screens and settings as mechanical work once the form and list kit exists.

The Agent App half is where the redesign changes CraftBot itself, not just its front end. Today an app is a web page that the agent operates through a side door of ops. With `views.json` and `agent-app view`, an app becomes an op graph with a declared presentation, so what the user sees and what the agent operates are the same object, and the agent gets a text snapshot of the real UI instead of a headless browser's guess. That also gives the build gate a way to prove the owner's "every feature through CLI ops" rule for the first time, and leaves the same manifest available to drive other surfaces later.
