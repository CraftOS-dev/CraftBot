/**
 * Mounts the client and swaps between its two roots.
 *
 * Exactly one Ink root is alive at a time, and all state lives in the Redux
 * store, so swapping loses nothing:
 *   - the chat root renders inline on the main screen (scrollback above it);
 *   - the screen root renders on the alternate screen while any screen is
 *     open, and returning to the chat restores the main screen untouched.
 * A swap clears the old root's frame before unmounting it, so no stale live
 * region is left behind in scrollback.
 */
import { Provider } from 'react-redux'
import { render, type Instance } from 'ink'
import { store } from '../state/store'
import { ChatRoot } from '../chat/ChatRoot'
import { ScreenRoot } from '../screens/ScreenRoot'
import { config } from '../config'
import { getSocketClient } from '../../../browser/frontend/src/store/socket/socketInstance'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import { setUiLanguage } from '../platform/i18n'
import i18n from '../platform/i18n'
import { closeAllScreens, linkSubagent, openScreen, pushToast, setHello } from '../state/tuiSlice'
import { persistentStorage } from '../platform/globals'
import { notify, setBusyProgress, setTitle, terminalCaps } from '../caps/terminal'
import { sessionTitle } from '../chat/transcriptWriter'
import { isQuitting } from './actions'
import { Splash } from './Splash'

/** Extra frames this client reads beyond the browser's (backend client_hello). */
const CAPABILITIES = ['subagent_link']
const CLIENT_PROTOCOL = 1

type Mode = 'splash' | 'chat' | 'screens'

let instance: Instance | null = null
let mode: Mode | null = null
let resolveExit: (() => void) | null = null

function mount(next: Mode): void {
  if (mode === next) return
  if (instance) {
    instance.clear()
    instance.cleanup()
    instance = null
    // Keep the terminal in raw mode across the swap, so keys typed in the
    // instant between the two roots are not line-buffered and lost.
    if (process.stdin.isTTY) process.stdin.setRawMode(true)
  }
  mode = next
  const tree = (
    <Provider store={store}>
      {next === 'screens' ? <ScreenRoot /> : next === 'chat' ? <ChatRoot /> : <Splash />}
    </Provider>
  )
  instance = render(tree, {
    exitOnCtrlC: false,
    patchConsole: false,
    incrementalRendering: true,
    maxFps: 30,
    kittyKeyboard: { mode: 'auto' },
    alternateScreen: next === 'screens' && !config().plain,
  })
  void instance.waitUntilExit().then(() => {
    // An exit() from inside a root (quit) ends the whole client.
    if (isQuitting()) shutdown()
  })
}

function shutdown(): void {
  persistentStorage.flush()
  setBusyProgress(false)
  if (instance) {
    try {
      instance.cleanup()
    } catch {
      // Already torn down.
    }
    instance = null
  }
  resolveExit?.()
}

/** Pick the root the state calls for. */
function sync(): void {
  if (isQuitting()) return
  const state = store.getState()
  const ready = state.tui.hello !== null && state.connection.connected
  const wanted: Mode = !ready && mode !== 'chat' && mode !== 'screens' ? 'splash' : state.tui.screens.length > 0 ? 'screens' : 'chat'
  if (wanted !== mode) mount(wanted)
}

export async function startClient(): Promise<void> {
  const client = getSocketClient()

  // Say hello on every (re)connect: what this client is and what it reads.
  client.onOpen(() => {
    client.send('client_hello', { client: 'terminal', protocol: CLIENT_PROTOCOL, capabilities: CAPABILITIES })
  })

  onInboundMessage(msg => {
    switch (msg.type) {
      case 'client_hello': {
        const d = (msg.data ?? {}) as { protocol?: number; edition?: string; version?: string }
        store.dispatch(setHello({ protocol: d.protocol ?? 0, edition: d.edition ?? '', version: d.version ?? '' }))
        if (d.edition && d.edition !== 'terminal') {
          store.dispatch(pushToast(i18n.t('tui:connect.wrongEdition', { edition: d.edition }), 'error', null, 'edition'))
        }
        break
      }
      case 'subagent_link': {
        const d = (msg.data ?? {}) as { subId?: string; parentId?: string | null; agentType?: string; state?: string }
        if (d.subId) {
          store.dispatch(linkSubagent({ subId: d.subId, parentId: d.parentId ?? null, agentType: d.agentType ?? '', state: d.state ?? 'running' }))
        }
        break
      }
      case 'init': {
        const d = (msg.data ?? {}) as { needsHardOnboarding?: boolean; agentName?: string }
        if (d.needsHardOnboarding) {
          store.dispatch(closeAllScreens())
          store.dispatch(openScreen({ id: 'onboarding' }))
        }
        client.send('settings_get', {})
        break
      }
      case 'settings_get':
      case 'settings_update': {
        // The saved UI language (general.ui_language), as the browser reads it.
        const d = (msg.data ?? {}) as { settings?: { language?: string } }
        if (d.settings?.language) setUiLanguage(d.settings.language)
        break
      }
    }
  })

  // Window title, Windows Terminal busy progress, and a notification when a
  // session the user is not looking at asks something or finishes.
  let lastTitle = ''
  let lastBusyAny = false
  const wasBusy = new Set<string>()
  const announced = new Set<string>()
  let seen: { messages: unknown; runs: unknown; active: string } | null = null
  store.subscribe(() => {
    sync()
    const state = store.getState()
    const active = state.tui.activeSessionId
    if (seen && seen.messages === state.messages && seen.runs === state.agent.runStateBySession && seen.active === active) return
    seen = { messages: state.messages, runs: state.agent.runStateBySession, active }
    const busySessions = Object.keys(state.agent.runStateBySession)
    const busyAny = busySessions.length > 0
    if (busyAny !== lastBusyAny) {
      lastBusyAny = busyAny
      setBusyProgress(busyAny)
    }

    let needsYou = 0
    for (const [sessionId, bucket] of Object.entries(state.messages.bySession)) {
      for (const m of bucket.items) {
        if (!m.isQuestion || m.optionSelected) continue
        if (sessionId !== active) needsYou++
        if (sessionId !== active && !announced.has(m.messageId) && state.connection.connected) {
          announced.add(m.messageId)
          // Questions already waiting at startup are not news.
          if (state.tui.hello && Date.now() - m.timestamp * 1000 < 60_000) {
            notify('CraftBot', i18n.t('tui:notify.question', { session: sessionTitle(state, sessionId) }))
          }
        }
      }
    }
    for (const sessionId of [...wasBusy]) {
      if (busySessions.includes(sessionId)) continue
      wasBusy.delete(sessionId)
      if (sessionId !== active && !sessionId.startsWith('sub_')) {
        notify('CraftBot', i18n.t('tui:notify.done', { session: sessionTitle(state, sessionId) }))
      }
    }
    for (const sessionId of busySessions) wasBusy.add(sessionId)

    const title = `CraftBot${busyAny ? ` ${String.fromCodePoint(0x25d0)}` : ''}${needsYou ? ` · ${i18n.t('tui:notify.needsYou', { count: needsYou })}` : ''}`
    if (title !== lastTitle) {
      lastTitle = title
      setTitle(title)
    }
  })

  // The legacy Windows console lacks synchronized output, bracketed paste and
  // Shift+Enter: say once that Windows Terminal works better.
  const LEGACY_NOTICE_KEY = 'craftbot-terminal-legacy-console-notice'
  if (terminalCaps().legacyConsole && !localStorage.getItem(LEGACY_NOTICE_KEY)) {
    localStorage.setItem(LEGACY_NOTICE_KEY, '1')
    store.dispatch(pushToast(i18n.t('tui:connect.legacyConsole'), 'info', 15_000, 'legacy-console'))
  }

  const done = new Promise<void>(resolve => {
    resolveExit = resolve
  })
  sync()
  // Leave the splash for the chat as soon as the backend greets us.
  await done
}
