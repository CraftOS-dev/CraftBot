import { useCallback, useEffect, useRef, type RefObject } from 'react'
import { getSocketClient } from '../../store/socket/socketInstance'
import type { MiniBrowserInputEvent, MiniBrowserViewport } from '../../types'

// The browser panel's one doorway to the socket. Everything else in the
// panel goes through these helpers, so the two sending rules live in one
// place:
//
//   - Live traffic (input, resize, subscriptions, queries) is connected-only.
//     The shared client queues sends while offline and replays them on
//     reconnect; a replayed click or keystroke would land on whatever page is
//     showing by then, and dozens of dropped wheel events would surface as
//     "N actions weren't sent". Live traffic is simply dropped instead.
//   - User actions (navigate, tabs, start, take control…) use the normal
//     queued send like every other user action in the app.
//
// Every chat session has a browser of its own: requests about a session's
// browser name it (`sessionId`). Frames and the agent's pointer are read
// straight off the socket (see LiveView): they arrive many times a second and
// must not re-render React.

type Payload = Record<string, unknown>

/** Send live traffic; dropped while disconnected. Returns whether it was sent. */
export function sendLive(type: string, data: Payload = {}): boolean {
  const client = getSocketClient()
  if (!client.isConnected) return false
  client.send(type, data)
  return true
}

/** Send a user action (queued while disconnected, like the rest of the app). */
export function sendAction(type: string, data: Payload = {}): void {
  getSocketClient().send(type, data)
}

/** Forward one input event to a tab of a session's browser. Dropped while
 *  disconnected. */
export function sendInput(sessionId: string, tabId: string, event: MiniBrowserInputEvent): boolean {
  return sendLive('mini_browser_input', { sessionId, tabId, event })
}

export function isSocketConnected(): boolean {
  return getSocketClient().isConnected
}

/** Listen to a high-frequency message outside Redux. Returns an unsubscribe. */
export function onLiveMessage(
  type: 'mini_browser_frame' | 'mini_browser_pointer',
  handler: (data: unknown) => void,
): () => void {
  return getSocketClient().onMessage(type, handler)
}

const RESIZE_DEBOUNCE_MS = 150
// A collapsed or hidden stage isn't worth resizing the remote page for.
const MIN_STAGE_PX = 50

/**
 * Keeps this window registered as a viewer of a session's browser while its
 * panel is mounted, the socket is connected and the document is visible, and
 * keeps that browser's viewport matched to the stage so frames fill it 1:1.
 *
 * Subscribing is opening the panel: the backend replies with the current
 * state and the last frame, and starts the session's browser. After every
 * (re)subscribe the stage size is sent again, since the backend may have
 * restarted or another window may have resized the viewport meanwhile. The
 * stage size is sent once it settles (the panel's open animation and a
 * drag of its divider resize the stage on every frame).
 */
export function useMiniBrowserViewer(
  sessionId: string,
  stageRef: RefObject<HTMLElement>,
  connected: boolean,
  reportedViewport: MiniBrowserViewport | null,
): void {
  const lastSentRef = useRef('')
  const reportedRef = useRef(reportedViewport)
  reportedRef.current = reportedViewport

  const pushSize = useCallback((force: boolean) => {
    const el = stageRef.current
    if (!el) return
    const width = Math.round(el.clientWidth)
    const height = Math.round(el.clientHeight)
    if (width < MIN_STAGE_PX || height < MIN_STAGE_PX) return
    const key = `${width}x${height}`
    if (!force && key === lastSentRef.current) return
    if (sendLive('mini_browser_resize', { sessionId, width, height })) lastSentRef.current = key
  }, [sessionId, stageRef])

  useEffect(() => {
    if (!connected) return
    let subscribed = false
    const subscribe = () => {
      if (subscribed || document.visibilityState === 'hidden') return
      // The size first, so the browser starts at the panel's size.
      pushSize(true)
      if (!sendLive('mini_browser_subscribe', { sessionId })) return
      subscribed = true
    }
    const unsubscribe = () => {
      if (!subscribed) return
      subscribed = false
      sendLive('mini_browser_unsubscribe', { sessionId })
    }
    // A hidden window stops the stream (the backend screencasts only while
    // someone watches) and resumes it when shown again.
    const onVisibility = () => (document.visibilityState === 'hidden' ? unsubscribe() : subscribe())
    subscribe()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      unsubscribe()
    }
  }, [connected, pushSize, sessionId])

  useEffect(() => {
    const el = stageRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let timer: number | undefined
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => pushSize(false), RESIZE_DEBOUNCE_MS)
    })
    observer.observe(el)
    // Two CraftBot windows on the same chat share its viewport; the window
    // the user is looking at wins it back when focused (only if it differs).
    const onFocus = () => {
      const reported = reportedRef.current
      const width = Math.round(el.clientWidth)
      const height = Math.round(el.clientHeight)
      if (reported && reported.width === width && reported.height === height) return
      pushSize(true)
    }
    window.addEventListener('focus', onFocus)
    return () => {
      observer.disconnect()
      window.clearTimeout(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [stageRef, pushSize])
}
