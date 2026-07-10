/**
 * Persistent iframe pool for Living UIs.
 *
 * Iframes live in a fixed container on document.body so they are never
 * unmounted by React Router navigation. LivingUIPage positions a pool
 * iframe over its placeholder div via ResizeObserver.
 */

const MAX_POOL_SIZE = 5

const pool = new Map<string, HTMLIFrameElement>()
// Track access order for LRU eviction
const accessOrder: string[] = []

let container: HTMLDivElement | null = null

// Notified when an iframe is evicted from the pool (LRU overflow), so the
// host UI can tell the user the app will reload (losing in-page state) the
// next time they open it — instead of it silently resetting.
type EvictionListener = (projectId: string) => void
let evictionListener: EvictionListener | null = null

export function setEvictionListener(listener: EvictionListener | null) {
  evictionListener = listener
}

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

// Resolve the target origin for postMessage from the iframe's own src, so
// messages can't be read by an unexpected document (e.g. after a redirect).
// Falls back to '*' only when the src is transiently unparseable (blank
// during a refresh cycle).
function iframeTargetOrigin(iframe: HTMLIFrameElement): string {
  try {
    const origin = new URL(iframe.src, window.location.href).origin
    return origin && origin !== 'null' ? origin : '*'
  } catch {
    return '*'
  }
}

function touchAccess(id: string) {
  const idx = accessOrder.indexOf(id)
  if (idx !== -1) accessOrder.splice(idx, 1)
  accessOrder.push(id)

  // Evict oldest if over limit
  while (accessOrder.length > MAX_POOL_SIZE) {
    const evictId = accessOrder.shift()!
    removeIframe(evictId)
    try {
      evictionListener?.(evictId)
    } catch {}
  }
}

export function getOrCreateIframe(id: string, src: string): HTMLIFrameElement {
  let iframe = pool.get(id)
  if (!iframe) {
    iframe = document.createElement('iframe')
    iframe.src = src
    // Living UIs are cross-origin (localhost:<port>); without explicit
    // delegation the browser auto-denies permission-gated APIs inside the
    // iframe (geolocation etc.) without ever prompting the user. Note:
    // the Notifications API cannot be delegated at all (browsers hard-deny
    // it in cross-origin iframes) — apps use in-app toasts instead.
    // Deliberately excluded: usb, serial, bluetooth, payment.
    iframe.allow =
      'geolocation; camera; microphone; clipboard-read; clipboard-write; ' +
      'fullscreen; autoplay; picture-in-picture; display-capture; ' +
      'web-share; screen-wake-lock'
    // Remember the requested src separately: refreshIframe() transiently
    // blanks iframe.src, so it can't be trusted for change detection.
    iframe.dataset.craftbotSrc = src
    iframe.style.cssText =
      'position:fixed;border:none;visibility:hidden;pointer-events:none;z-index:10;'
    iframe.title = `Living UI ${id}`
    getContainer().appendChild(iframe)
    pool.set(id, iframe)
  } else if (iframe.dataset.craftbotSrc !== src) {
    // Same pool slot, new target (e.g. dev preview → production URL).
    iframe.dataset.craftbotSrc = src
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

export function refreshIframe(id: string) {
  const iframe = pool.get(id)
  if (iframe) {
    const src = iframe.src
    iframe.src = ''
    iframe.src = src
  }
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

export function broadcastThemeToIframes(theme: string, cssVars: Record<string, string>) {
  const message = { type: 'craftbot-theme', theme, cssVars }
  pool.forEach(iframe => {
    try {
      iframe.contentWindow?.postMessage(message, iframeTargetOrigin(iframe))
    } catch (e) {}
  })
}

export function postMessageToIframe(id: string, data: unknown) {
  const iframe = pool.get(id)
  if (!iframe) return
  try {
    iframe.contentWindow?.postMessage(data, iframeTargetOrigin(iframe))
  } catch (e) {}
}
