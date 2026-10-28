/**
 * Persistent iframe pool for Agent Apps.
 *
 * Iframes live in a fixed container on document.body so they are never
 * unmounted by React Router navigation. Visible surfaces hold exclusive leases.
 */

import i18n from '../../i18n/config'

const MAX_POOL_SIZE = 5

const pool = new Map<string, HTMLIFrameElement>()
// Track access order for LRU eviction
const accessOrder: string[] = []
const owners = new Map<string, symbol>()
const listeners = new Set<() => void>()

export function subscribeFrameHost(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function changed() { listeners.forEach(listener => listener()) }

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
    const evictId = accessOrder.find(key => !owners.has(key))
    if (!evictId) break
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
  const url = new URL(src, window.location.href)
  if (!['http:', 'https:'].includes(url.protocol) || url.origin === window.location.origin) {
    throw new Error('Agent Apps require a separate HTTP(S) origin.')
  }
  let iframe = pool.get(id)
  if (!iframe) {
    iframe = document.createElement('iframe')
    // Apps are cross-ORIGIN to the UI (another port), and a cross-origin
    // frame gets no powerful features unless the embedder delegates them.
    // Without this, getUserMedia/getDisplayMedia were refused by permissions
    // policy before the user was ever asked, and clipboard writes failed:
    // Audio Notes saved 26 minutes of nothing. Delegating only lets the app
    // ASK; the browser still prompts the user. Must precede navigation.
    iframe.allow = 'microphone; camera; display-capture; clipboard-read; clipboard-write; fullscreen'
    iframe.src = src
    // The requested src is remembered separately: reading iframe.src back
    // returns the browser-normalized absolute URL, so comparing against it
    // would mismatch every render and reload-loop the app.
    iframe.dataset.requestedSrc = src
    iframe.style.cssText =
      'position:fixed;border:none;visibility:hidden;pointer-events:none;z-index:10;'
    iframe.title = i18n.t('agentapp:iframe.title', { id })
    // Recorded here, not by a surface: a frame can finish loading while no
    // surface holds it (its tab is in the background), and must not then be
    // reported as still loading when it is shown again.
    iframe.addEventListener('load', function () { this.dataset.loadedSrc = this.dataset.requestedSrc })
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

/** Whether the frame finished navigating to the src it was last given. */
export function isIframeLoaded(id: string): boolean {
  const iframe = pool.get(id)
  return !!iframe && iframe.dataset.loadedSrc === iframe.dataset.requestedSrc
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
  owners.delete(id)
  changed()
}

/** Exactly one owner places each project frame; stale cleanup is harmless. */
export function acquireIframe(id: string, src: string) {
  if (owners.has(id)) return null
  if (!pool.has(id) && pool.size >= MAX_POOL_SIZE) {
    const candidate = accessOrder.find(key => !owners.has(key))
    if (!candidate) return null
    removeIframe(candidate)
  }
  const owner = Symbol(id)
  owners.set(id, owner)
  let frame: HTMLIFrameElement
  try { frame = getOrCreateIframe(id, src) }
  catch (error) { owners.delete(id); throw error }
  return {
    frame,
    update(rect: DOMRect, visible: boolean, interactive: boolean) {
      if (owners.get(id) !== owner) return
      if (visible) {
        showIframe(id, rect)
        frame.style.pointerEvents = interactive ? 'auto' : 'none'
      } else hideIframe(id)
      frame.inert = !visible || !interactive
    },
    release() {
      if (owners.get(id) !== owner) return
      hideIframe(id)
      frame.inert = true
      owners.delete(id)
      changed()
    },
  }
}

/** Dispose stopped/deleted frames even when their React surface is absent. */
export function reconcileIframes(projects: { id: string; status: string }[]) {
  const running = new Set(projects.filter(p => p.status === 'running').map(p => p.id))
  for (const id of pool.keys()) if (!running.has(id)) removeIframe(id)
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
      iframe.contentWindow?.postMessage(message, new URL(iframe.src).origin)
    } catch (e) {}
  })
}

export function sendThemeToIframe(id: string, theme: string, cssVars: Record<string, string>) {
  const iframe = pool.get(id)
  if (!iframe) return
  try {
    iframe.contentWindow?.postMessage({ type: 'craftbot-theme', theme, cssVars }, new URL(iframe.src).origin)
  } catch (e) {}
}

export function postMessageToIframe(id: string, data: unknown) {
  const iframe = pool.get(id)
  if (!iframe) return
  try {
    iframe.contentWindow?.postMessage(data, new URL(iframe.src).origin)
  } catch (e) {}
}

export function acceptsFrameMessage(id: string, event: MessageEvent): boolean {
  const frame = pool.get(id)
  return !!frame && ownsProjectWindow(id, event.source) && event.origin === new URL(frame.src).origin
}
