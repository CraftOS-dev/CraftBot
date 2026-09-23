/**
 * Persistent iframe pool for Agent Apps.
 *
 * Iframes live in a fixed container on document.body so they are never
 * unmounted by React Router navigation. AgentAppPage positions a pool
 * iframe over its placeholder div via ResizeObserver.
 */

import i18n from '../../i18n/config'

const MAX_POOL_SIZE = 5

const pool = new Map<string, HTMLIFrameElement>()
// Track access order for LRU eviction
const accessOrder: string[] = []

let container: HTMLDivElement | null = null

function getContainer(): HTMLDivElement {
  if (!container) {
    container = document.createElement('div')
    container.id = 'agentapp-iframe-pool'
    container.style.cssText =
      'position:fixed;top:0;left:0;width:0;height:0;overflow:visible;z-index:0;pointer-events:none;'
    document.body.appendChild(container)
  }
  return container
}

function touchAccess(id: string) {
  const idx = accessOrder.indexOf(id)
  if (idx !== -1) accessOrder.splice(idx, 1)
  accessOrder.push(id)

  // Evict oldest if over limit
  while (accessOrder.length > MAX_POOL_SIZE) {
    const evictId = accessOrder.shift()!
    removeIframe(evictId)
  }
}

/**
 * The URL to FRAME an app at. Apps report http://127.0.0.1:<port>, but the
 * CraftBot UI usually runs on localhost — and localhost vs 127.0.0.1 are
 * different SITES. Framed cross-site, the app's SameSite session cookie is
 * neither set nor sent, so every write the app makes (and its WebSocket) is
 * refused by the A2App guard. Framing it under the UI's own name keeps it
 * same-site (cookies ignore ports). Only 127.0.0.1 → localhost is rewritten:
 * localhost resolves to 127.0.0.1 too, while apps never bind [::1].
 */
export function frameUrl(url: string): string {
  if (typeof window === 'undefined' || window.location.hostname !== 'localhost') return url
  try {
    const u = new URL(url)
    if (u.hostname !== '127.0.0.1') return url
    u.hostname = 'localhost'
    return u.toString()
  } catch {
    return url
  }
}

export function getOrCreateIframe(id: string, src: string): HTMLIFrameElement {
  let iframe = pool.get(id)
  if (!iframe) {
    iframe = document.createElement('iframe')
    iframe.src = src
    // The requested src is remembered separately: reading iframe.src back
    // returns the browser-normalized absolute URL, so comparing against it
    // would mismatch every render and reload-loop the app.
    iframe.dataset.requestedSrc = src
    iframe.style.cssText =
      'position:fixed;border:none;visibility:hidden;pointer-events:none;z-index:10;'
    iframe.title = i18n.t('agentapp:iframe.title', { id })
    getContainer().appendChild(iframe)
    pool.set(id, iframe)
  } else if (iframe.dataset.requestedSrc !== src) {
    // A new deploy (version-stamped src) or a changed URL: navigate the
    // existing frame. The pool used to ignore src changes entirely, which
    // pinned a tab to whatever build was live when its iframe was first
    // created — deploys landed on the server and never on screen.
    iframe.dataset.requestedSrc = src
    iframe.src = src
  }
  touchAccess(id)
  return iframe
}

export function showIframe(id: string, rect: DOMRect) {
  const iframe = pool.get(id)
  if (!iframe) return
  iframe.style.top = rect.top + 'px'
  iframe.style.left = rect.left + 'px'
  iframe.style.width = rect.width + 'px'
  iframe.style.height = rect.height + 'px'
  iframe.style.visibility = 'visible'
  iframe.style.pointerEvents = 'auto'
}

export function hideIframe(id: string) {
  const iframe = pool.get(id)
  if (!iframe) return
  iframe.style.visibility = 'hidden'
  iframe.style.pointerEvents = 'none'
}

export function removeIframe(id: string) {
  const iframe = pool.get(id)
  if (iframe) {
    iframe.remove()
    pool.delete(id)
  }
  const idx = accessOrder.indexOf(id)
  if (idx !== -1) accessOrder.splice(idx, 1)
}

// The host does NOT refresh an app's data view — an app owns its own live
// data (the kit's realtime hooks refetch in place, keeping the open view and
// any modal intact). The host only navigates the frame on a new DEPLOY, via
// getOrCreateIframe's version-stamped src.

export function hasIframe(id: string): boolean {
  return pool.has(id)
}

export function getIframeWindow(id: string): Window | null {
  return pool.get(id)?.contentWindow ?? null
}

/** True if `win` belongs to this project's iframe. */
export function ownsProjectWindow(id: string, win: unknown): boolean {
  if (win == null) return false
  return win === pool.get(id)?.contentWindow
}

export function broadcastThemeToIframes(theme: string, cssVars: Record<string, string>) {
  const message = { type: 'craftbot-theme', theme, cssVars }
  pool.forEach(iframe => {
    try {
      iframe.contentWindow?.postMessage(message, '*')
    } catch (e) {}
  })
}

export function sendThemeToIframe(id: string, theme: string, cssVars: Record<string, string>) {
  const iframe = pool.get(id)
  if (!iframe) return
  try {
    iframe.contentWindow?.postMessage({ type: 'craftbot-theme', theme, cssVars }, '*')
  } catch (e) {}
}

export function postMessageToIframe(id: string, data: unknown) {
  const iframe = pool.get(id)
  if (!iframe) return
  try {
    iframe.contentWindow?.postMessage(data, '*')
  } catch (e) {}
}
