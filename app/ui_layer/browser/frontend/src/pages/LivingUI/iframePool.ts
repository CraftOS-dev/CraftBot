/**
 * Persistent iframe pool for Living UIs.
 *
 * Iframes live in a fixed container on document.body so they are never
 * unmounted by React Router navigation. LivingUIPage positions a pool
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
    container.id = 'livingui-iframe-pool'
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

export function getOrCreateIframe(id: string, src: string): HTMLIFrameElement {
  let iframe = pool.get(id)
  if (!iframe) {
    iframe = document.createElement('iframe')
    iframe.src = src
    iframe.style.cssText =
      'position:fixed;border:none;visibility:hidden;pointer-events:none;z-index:10;'
    iframe.title = i18n.t('livingui:iframe.title', { id })
    getContainer().appendChild(iframe)
    pool.set(id, iframe)
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
  // Keep an in-flight swap buffer glued to the same geometry (still beneath
  // in DOM order, still inert) so the app inside lays out at the real size.
  const buffer = pendingSwap.get(id)
  if (buffer) {
    buffer.style.top = rect.top + 'px'
    buffer.style.left = rect.left + 'px'
    buffer.style.width = rect.width + 'px'
    buffer.style.height = rect.height + 'px'
    buffer.style.visibility = 'visible'
  }
}

export function hideIframe(id: string) {
  const iframe = pool.get(id)
  if (!iframe) return
  iframe.style.visibility = 'hidden'
  iframe.style.pointerEvents = 'none'
  const buffer = pendingSwap.get(id)
  if (buffer) buffer.style.visibility = 'hidden'
}

export function removeIframe(id: string) {
  const iframe = pool.get(id)
  if (iframe) {
    iframe.remove()
    pool.delete(id)
  }
  const buffer = pendingSwap.get(id)
  if (buffer) {
    buffer.remove()
    pendingSwap.delete(id)
  }
  const idx = accessOrder.indexOf(id)
  if (idx !== -1) accessOrder.splice(idx, 1)
}

// Seamless refresh: double-buffered. The visible document keeps showing its
// (stale) content while a replacement loads the same src BENEATH it — an
// identical style clone inserted EARLIER in DOM order, so document order
// alone stacks it underneath (no magic z-index). It stays fully visible the
// whole time: a visibility:hidden cross-origin iframe gets render-throttled
// by the browser, which breaks apps whose layout depends on paint-time
// effects; occluded-but-visible does not. After the replacement's load event
// plus a settle delay for the app's own data fetch, it adopts the front
// frame's style and the old frame is removed. At no point is a blank
// document on screen. The app inside is a black box — this works for any
// frontend/backend and needs no cooperation from the project.
const SWAP_SETTLE_MS = 900 // post-load: let the app fetch and render its data
const SWAP_TIMEOUT_MS = 12000
const pendingSwap = new Map<string, HTMLIFrameElement>()

export function refreshIframe(id: string) {
  const current = pool.get(id)
  if (!current) return

  // A newer refresh supersedes any in-flight buffer (it may hold pre-write data)
  const stale = pendingSwap.get(id)
  if (stale) {
    pendingSwap.delete(id)
    stale.remove()
  }

  const fresh = document.createElement('iframe')
  fresh.src = current.src
  fresh.title = current.title
  fresh.style.cssText = current.style.cssText // same geometry, same stacking
  fresh.style.pointerEvents = 'none'
  getContainer().insertBefore(fresh, current) // earlier sibling paints beneath
  pendingSwap.set(id, fresh)

  const swap = () => {
    if (pendingSwap.get(id) !== fresh) return // superseded or cancelled
    pendingSwap.delete(id)
    const old = pool.get(id)
    if (!old) {
      fresh.remove() // project was removed while the buffer loaded
      return
    }
    fresh.style.cssText = old.style.cssText // adopt live geometry and interactivity
    pool.set(id, fresh)
    old.remove()
  }
  fresh.addEventListener('load', () => setTimeout(swap, SWAP_SETTLE_MS))
  // If load never fires (backend down), drop the buffer and keep the old frame
  setTimeout(() => {
    if (pendingSwap.get(id) === fresh) {
      pendingSwap.delete(id)
      fresh.remove()
    }
  }, SWAP_TIMEOUT_MS)
}

const pendingRefreshTimers = new Map<string, ReturnType<typeof setTimeout>>()

export function scheduleRefreshIframe(id: string, delayMs = 500) {
  const existing = pendingRefreshTimers.get(id)
  if (existing) clearTimeout(existing)
  const timer = setTimeout(() => {
    pendingRefreshTimers.delete(id)
    refreshIframe(id)
  }, delayMs)
  pendingRefreshTimers.set(id, timer)
}

export function hasIframe(id: string): boolean {
  return pool.has(id)
}

export function getIframeWindow(id: string): Window | null {
  return pool.get(id)?.contentWindow ?? null
}

/** True if `win` belongs to this project: the visible frame OR an in-flight
 * swap buffer (which boots hidden and must still get theme replies etc.). */
export function ownsProjectWindow(id: string, win: unknown): boolean {
  if (win == null) return false
  return (
    win === pool.get(id)?.contentWindow || win === pendingSwap.get(id)?.contentWindow
  )
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
  // Mirror to an in-flight swap buffer so e.g. theme changes mid-swap land in
  // the document that is about to become visible.
  for (const iframe of [pool.get(id), pendingSwap.get(id)]) {
    if (!iframe) continue
    try {
      iframe.contentWindow?.postMessage(data, '*')
    } catch (e) {}
  }
}
