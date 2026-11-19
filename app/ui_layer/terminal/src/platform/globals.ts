/**
 * The few browser globals the shared store touches, provided for Node.
 *
 * The terminal client reuses the browser frontend's Redux slices unchanged.
 * Those modules reference `window`, `document`, `localStorage`,
 * `sessionStorage`, `requestAnimationFrame` and `WebSocket` in a handful of
 * places (timers, visibility, persistence, the socket). This module installs
 * terminal equivalents before anything from the store is imported, so the
 * browser code runs as written and the browser frontend is never edited.
 */
import { join } from 'node:path'
import WebSocketImpl from 'ws'
import { FileStorage } from './storage'

const noop = () => {}

export const preferenceStorage = new FileStorage(null)
export let persistentStorage: FileStorage = preferenceStorage

/** Install the shims. `stateDir` holds the remembered UI state file. */
export function installBrowserGlobals(stateDir: string, port: number): void {
  const g = globalThis as Record<string, unknown>
  persistentStorage = new FileStorage(join(stateDir, 'terminal_ui_state.json'))

  // `window` is the global object in a browser; timers live on it.
  g.window = globalThis
  ;(globalThis as unknown as { addEventListener: () => void }).addEventListener = noop
  ;(globalThis as unknown as { removeEventListener: () => void }).removeEventListener = noop
  ;(globalThis as unknown as { dispatchEvent: () => boolean }).dispatchEvent = () => true

  // A terminal is always "visible"; nothing fires visibility events.
  g.document = {
    visibilityState: 'visible',
    hidden: false,
    addEventListener: noop,
    removeEventListener: noop,
    documentElement: { lang: 'en', setAttribute: noop, style: {} },
  }

  g.localStorage = persistentStorage
  g.sessionStorage = new FileStorage(null)

  // Batch inbound socket messages like a frame would (about 30 per second,
  // the renderer's own cap), instead of once per message.
  g.requestAnimationFrame = (callback: (time: number) => void) =>
    setTimeout(() => callback(performance.now()), 33) as unknown as number
  g.cancelAnimationFrame = (handle: number) => clearTimeout(handle as unknown as NodeJS.Timeout)

  // The browser's WebSocket sends its page origin; the backend's handshake
  // requires one (ws_auth.py). Send the backend's own origin, as its own UI does.
  const origin = `http://localhost:${port}`
  class OriginWebSocket extends WebSocketImpl {
    constructor(url: string, protocols?: string | string[]) {
      super(url, protocols, { headers: { Origin: origin }, perMessageDeflate: false })
    }
  }
  g.WebSocket = OriginWebSocket

  if (typeof g.navigator === 'undefined') {
    g.navigator = { language: process.env.LANG ?? 'en', onLine: true, userAgent: 'craftbot-terminal' }
  }
}
