/**
 * devBuildMode — the Staged Reveal Engine (DEV ONLY, system-managed).
 *
 * Loaded exclusively by main.tsx under `import.meta.env.DEV`, i.e. the Vite
 * dev server CraftBot runs while this app is being created. Never part of a
 * production build. Do not edit.
 *
 * THE IDEA: the agent writes code in bursts (often whole files), so UI would
 * otherwise appear in big jumps. This engine turns every DOM arrival —
 * first mount, HMR patch, or full page reload — into a choreographed,
 * element-by-element assembly the user can watch:
 *
 *   1. While staging is active (`data-cb-staging` on <body>), elements not
 *      yet marked `data-cb-revealed` are invisible.
 *   2. A persistent ledger (sessionStorage, per dev-server origin) records
 *      the structural fingerprint of everything already revealed. Elements
 *      in the ledger show instantly — a reload or re-render never replays
 *      the whole app. Only genuinely NEW elements queue for reveal.
 *   3. A choreographer drains the queue at a human pace: layout containers
 *      first (fade in as blocks), then leaves (buttons, inputs, headings)
 *      with a staggered fade-and-rise. Pace adapts to queue size so a
 *      whole-frontend dump plays out in tens of seconds, not one jump.
 *   4. Reveals are narrated to the CraftBot host via postMessage
 *      ('craftbot-dev-reveal') so the construction dock can say what is
 *      being placed.
 *
 * FAIL-OPEN: hiding content is the only dangerous move, so every failure
 * path removes staging and shows everything: any exception in the engine,
 * or a watchdog that sees hidden elements without reveal progress. Worst
 * case is a plain visible app — never a blank screen, never a broken build.
 */

const REVEAL_ATTR = 'data-cb-revealed'
const STAGING_ATTR = 'data-cb-staging'
const ANIM_LEAF = 'cb-reveal-leaf'
const ANIM_BLOCK = 'cb-reveal-block'
const LEDGER_KEY = 'craftbot-reveal-ledger'
const LEDGER_MAX = 8000
const SNAPSHOT_KEY = 'craftbot-last-good-dom'
const WATCHDOG_MS = 3000
const STALL_LIMIT_MS = 12000

// ── host messaging ──────────────────────────────────────────────────────────

import { LK_CLASSES } from '../components/ui/layout'

function post(type: string, data: Record<string, unknown>) {
  try {
    window.parent.postMessage({ type, ...data }, '*')
  } catch {
    /* not embedded */
  }
}

// ── fail-open kill switch ───────────────────────────────────────────────────

let dead = false

function failOpen(reason: string) {
  if (dead) return
  dead = true
  try {
    document.body.removeAttribute(STAGING_ATTR)
    document
      .querySelectorAll(`#root *:not([${REVEAL_ATTR}])`)
      .forEach(el => el.setAttribute(REVEAL_ATTR, '1'))
  } catch {
    /* the CSS rule is scoped to body[data-cb-staging]; attribute removal
       above already made everything visible */
  }
  console.warn(`[RevealEngine] fail-open: ${reason}`)
}

function guarded<T extends (...args: any[]) => void>(fn: T): T {
  return ((...args: any[]) => {
    if (dead) return
    try {
      fn(...args)
    } catch (e) {
      failOpen(String(e))
    }
  }) as T
}

// ── ledger (what has already been revealed, across reloads) ─────────────────

const ledger = new Set<string>()
let ledgerDirty = false

function loadLedger() {
  try {
    const raw = sessionStorage.getItem(LEDGER_KEY)
    if (raw) JSON.parse(raw).forEach((fp: string) => ledger.add(fp))
  } catch {
    /* fresh start is fine */
  }
}

function persistLedgerSoon() {
  if (ledgerDirty) return
  ledgerDirty = true
  setTimeout(() => {
    ledgerDirty = false
    try {
      sessionStorage.setItem(
        LEDGER_KEY,
        JSON.stringify(Array.from(ledger).slice(-LEDGER_MAX)),
      )
    } catch {
      /* quota — reloads will re-animate, cosmetic only */
    }
  }, 500)
}

/** Structural fingerprint: tag + child-index path from #root. Stable across
 * re-renders of the same structure; new structure = new fingerprint. */
function fingerprintOf(el: Element, root: Element): string {
  const parts: string[] = []
  let node: Element | null = el
  while (node && node !== root) {
    const parent: Element | null = node.parentElement
    if (!parent) break
    let idx = 0
    for (let c = node.previousElementSibling; c; c = c.previousElementSibling) idx++
    parts.push(`${node.tagName}:${idx}`)
    node = parent
  }
  return parts.reverse().join('/')
}

// ── choreographer ───────────────────────────────────────────────────────────

interface QueueItem {
  el: HTMLElement
  fp: string
  depth: number
  order: number
  isBlock: boolean
}

const queue: QueueItem[] = []
const queued = new Set<string>()
let draining = false
let lastProgressAt = Date.now()

function isBlock(el: HTMLElement): boolean {
  return el.childElementCount > 0
}

function markRevealed(el: HTMLElement, fp: string) {
  el.setAttribute(REVEAL_ATTR, '1')
  ledger.add(fp)
  persistLedgerSoon()
}

// Narration: name what just got placed, throttled, interesting things first.
let lastNarration = 0

function narrate(el: HTMLElement, block: boolean) {
  const now = Date.now()
  if (now - lastNarration < 400) return
  const tag = el.tagName.toLowerCase()
  const text = (el.textContent || '').trim().slice(0, 24)
  let label = ''
  if (tag === 'button') label = text ? `Placing button “${text}”` : 'Placing a button'
  else if (tag === 'input' || tag === 'select' || tag === 'textarea')
    label = 'Adding an input field'
  else if (/^h[1-4]$/.test(tag)) label = text ? `Adding heading “${text}”` : 'Adding a heading'
  else if (tag === 'table') label = 'Building a table'
  else if (tag === 'img' || tag === 'svg') label = 'Placing a graphic'
  else if (block && el.childElementCount >= 2) label = 'Assembling a layout section'
  if (!label) return
  lastNarration = now
  post('craftbot-dev-reveal', { label })
}

function revealDelay(): number {
  // Adaptive pacing: small updates feel snappy, big dumps still finish.
  const n = queue.length
  if (n > 150) return 35
  if (n > 60) return 70
  return 120
}

const drainTick = guarded(() => {
  // Blocks (outermost first) before leaves; DOM order within each class.
  queue.sort((a, b) =>
    a.isBlock !== b.isBlock
      ? a.isBlock ? -1 : 1
      : a.isBlock && a.depth !== b.depth
        ? a.depth - b.depth
        : a.order - b.order,
  )
  let item: QueueItem | undefined
  while ((item = queue.shift())) {
    queued.delete(item.fp)
    if (!item.el.isConnected) continue
    if (item.el.hasAttribute(REVEAL_ATTR)) continue
    break
  }
  if (!item || !item.el.isConnected) {
    draining = queue.length > 0
    if (draining) setTimeout(drainTick, revealDelay())
    return
  }
  markRevealed(item.el, item.fp)
  item.el.classList.add(item.isBlock ? ANIM_BLOCK : ANIM_LEAF)
  item.el.addEventListener(
    'animationend',
    () => item!.el.classList.remove(ANIM_BLOCK, ANIM_LEAF),
    { once: true },
  )
  narrate(item.el, item.isBlock)
  lastProgressAt = Date.now()
  if (queue.length > 0) {
    setTimeout(drainTick, item.isBlock ? Math.max(revealDelay(), 200) : revealDelay())
  } else {
    draining = false
  }
})

// ── scanning (initial mount, HMR commits, reload) ───────────────────────────

let scanScheduled = false

const scan = guarded(() => {
  scanScheduled = false
  const root = document.getElementById('root')
  if (!root) return
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT)
  let order = 0
  let node = walker.nextNode()
  while (node) {
    const el = node as HTMLElement
    order++
    if (!el.hasAttribute(REVEAL_ATTR)) {
      const fp = fingerprintOf(el, root)
      if (ledger.has(fp)) {
        // Seen before (reload / re-render) — show instantly, no re-animation.
        el.setAttribute(REVEAL_ATTR, '1')
      } else if (!queued.has(fp)) {
        queued.add(fp)
        let depth = 0
        for (let p = el.parentElement; p && p !== root; p = p.parentElement) depth++
        queue.push({ el, fp, depth, order, isBlock: isBlock(el) })
      }
    }
    node = walker.nextNode()
  }
  if (queue.length > 0 && !draining) {
    draining = true
    setTimeout(drainTick, 60)
  }
})

function scheduleScan() {
  if (scanScheduled || dead) return
  scanScheduled = true
  requestAnimationFrame(scan)
}

// ── staging css + watchdog ──────────────────────────────────────────────────

function installStaging() {
  const style = document.createElement('style')
  style.id = 'cb-reveal-style'
  style.textContent = `
body[${STAGING_ATTR}] #root *:not([${REVEAL_ATTR}]) { opacity: 0 !important; }
@keyframes cbRevealLeaf {
  from { opacity: 0; transform: translateY(7px) scale(0.985); }
  to   { opacity: 1; transform: none; }
}
@keyframes cbRevealBlock {
  from { opacity: 0; }
  to   { opacity: 1; }
}
.${ANIM_LEAF} { animation: cbRevealLeaf 420ms cubic-bezier(0.22, 1, 0.36, 1) both; }
.${ANIM_BLOCK} { animation: cbRevealBlock 460ms ease-out both; }
`
  document.head.appendChild(style)
  document.body.setAttribute(STAGING_ATTR, '1')

  // Watchdog: hidden content MUST always be making progress toward visible.
  setInterval(
    guarded(() => {
      const hidden = document.querySelector(`#root *:not([${REVEAL_ATTR}])`)
      if (!hidden) {
        lastProgressAt = Date.now()
        saveSnapshot() // settled = working state; keep the fallback fresh
        return
      }
      if (queue.length === 0) {
        // Hidden elements nobody is going to reveal — pick them up.
        scheduleScan()
      }
      if (Date.now() - lastProgressAt > STALL_LIMIT_MS) {
        failOpen('reveal queue stalled')
      }
    }),
    WATCHDOG_MS,
  )
}

// ── graceful API fallback (backend usually isn't running yet) ───────────────

function backendOrigin(): string | null {
  try {
    const base = (window as any).__CRAFTBOT_BACKEND_URL__
    return base ? new URL(base, window.location.href).origin : null
  } catch {
    return null
  }
}

function emptyBodyFor(url: string, method: string): string {
  if (method === 'GET') {
    return /\/api\/state\b/.test(url) ? '{}' : '[]'
  }
  return '{"status":"ok","devFallback":true}'
}

function installFetchFallback() {
  const origin = backendOrigin()
  if (!origin) return
  const realFetch = window.fetch.bind(window)
  window.fetch = function (input: RequestInfo | URL, init?: RequestInit) {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    const method = ((init && init.method) || 'GET').toUpperCase()
    let targetsBackend = false
    try {
      targetsBackend =
        new URL(url, window.location.href).origin === origin ||
        url.startsWith('/api')
    } catch {
      targetsBackend = false
    }
    const result = realFetch(input as RequestInfo, init)
    if (!targetsBackend) return result
    return result.catch(
      () =>
        new Response(emptyBodyFor(url, method), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
  }
}

// ── last-good-state fallback ────────────────────────────────────────────────
// Mid-build the agent regularly leaves the module graph momentarily broken
// (half-written file, syntax error). The user must NEVER see a build error
// or a blank page: while the app is healthy we keep a DOM snapshot, and if
// the app fails to boot we show that snapshot (static pixels of the last
// working state) until Vite full-reloads on the next successful write.

let snapshotRestored = false

const saveSnapshot = guarded(() => {
  // Never snapshot the fallback itself (engine restore or the root error
  // boundary showing the previous snapshot).
  if (snapshotRestored || (window as any).__CB_APP_CRASHED__) return
  const root = document.getElementById('root')
  if (!root || root.childElementCount === 0) return
  if (root.querySelector(`*:not([${REVEAL_ATTR}])`)) return // mid-reveal
  try {
    sessionStorage.setItem(SNAPSHOT_KEY, root.innerHTML)
  } catch {
    /* quota — cosmetic */
  }
})

function restoreSnapshot(): boolean {
  try {
    const html = sessionStorage.getItem(SNAPSHOT_KEY)
    const root = document.getElementById('root')
    if (!html || !root) return false
    snapshotRestored = true
    root.innerHTML = html
    document.body.removeAttribute(STAGING_ATTR)
    return true
  } catch {
    return false
  }
}

/**
 * Boot the app through the engine so a broken module graph degrades to the
 * last working state instead of a blank page. Recovery is Vite's own
 * full-reload: the next write that fixes the graph reloads the page and the
 * real app boots again.
 */
export function bootApp(boot: () => unknown) {
  Promise.resolve()
    .then(boot)
    .catch(() => {
      restoreSnapshot()
      // Report "still assembling", never the error itself.
      post('craftbot-dev-hmr', { status: 'updating' })
    })
}

// ── HMR status relay (host shows rebuild shimmer / error veil) ──────────────

function installHmrRelay() {
  const hot = import.meta.hot
  if (!hot) return
  hot.on('vite:beforeUpdate', () => post('craftbot-dev-hmr', { status: 'updating' }))
  hot.on('vite:afterUpdate', () => {
    post('craftbot-dev-hmr', { status: 'ok' })
    scheduleScan()
    if ((window as any).__CB_APP_CRASHED__) {
      // The root boundary is showing the last-good snapshot after a runtime
      // crash; a successful update means new code just arrived — reboot
      // clean (the reveal ledger makes the reload visually instant).
      location.reload()
    }
  })
  hot.on('vite:error', (payload: any) => {
    const message = payload?.err?.message || 'build error'
    post('craftbot-dev-hmr', { status: 'error', message: String(message).slice(0, 300) })
  })
  hot.on('vite:beforeFullReload', () => {
    // The DOM about to unload is the last known-working state — keep it so
    // the reload can fall back to it if the new module graph is broken.
    saveSnapshot()
    post('craftbot-dev-hmr', { status: 'updating' })
  })
  post('craftbot-dev-hmr', { status: 'ok' })
}

// ── design telemetry ────────────────────────────────────────────────────────
// Measures the REAL rendered layout and reports it to the host, which feeds
// CraftBot's design gate: validation refuses pages that overflow, clip text,
// render empty sections, or leave the viewport mostly void. Also captures a
// periodic screenshot (html2canvas, already a template dependency) so the
// agent can review its own UI with describe_image.

// scrollWidth/clientWidth are integer-rounded by the browser; a 1px delta
// is measurement noise, anything beyond it is real overflow. This is a
// rounding bound, not a policy threshold.
const PX_ROUNDING = 1

function computeDesignMetrics() {
  const doc = document.documentElement
  const vw = window.innerWidth || 1
  const vh = window.innerHeight || 1
  const overflowX = doc.scrollWidth - doc.clientWidth > PX_ROUNDING
  let clippedText = 0
  document.querySelectorAll('#root *').forEach(el => {
    if (!(el instanceof HTMLElement)) return
    if (el.childElementCount === 0 && (el.textContent || '').trim().length > 0) {
      if (el.scrollWidth - el.clientWidth > PX_ROUNDING) clippedText++
    }
  })
  // Empty section = renders literally nothing (no child elements, no text) —
  // an absence fact, not a size judgment.
  let emptySections = 0
  document.querySelectorAll('.' + LK_CLASSES.sectionBody).forEach(el => {
    if (el.children.length === 0 && (el.textContent || '').trim() === '') {
      emptySections++
    }
  })
  const viewportFill = Math.min(1, doc.scrollHeight / vh)
  return {
    overflowX,
    clippedText,
    emptySections,
    // Reported for the agent's information; NOT gated by the platform.
    viewportFill: Math.round(viewportFill * 100) / 100,
    skeletons: document.querySelectorAll('.' + LK_CLASSES.skeleton).length,
    // Visual richness proxy (absence check): any visual element counts.
    iconCount: document.querySelectorAll(
      '#root svg, #root img, #root canvas, #root video, #root picture',
    ).length,
    vw,
    vh,
  }
}

let lastMetricsAt = 0

const reportMetrics = guarded(() => {
  const now = Date.now()
  if (now - lastMetricsAt < 2000) return
  lastMetricsAt = now
  post('craftbot-dev-metrics', { metrics: computeDesignMetrics() })
})

let screenshotBusy = false
let lastScreenshotAt = 0

async function captureScreenshotSoon() {
  const now = Date.now()
  if (screenshotBusy || now - lastScreenshotAt < 20000 || dead) return
  screenshotBusy = true
  try {
    const mod: any = await import('html2canvas')
    const html2canvas = mod.default || mod
    const canvas = await html2canvas(document.body, {
      logging: false,
      scale: Math.min(1, 1280 / (window.innerWidth || 1280)),
      windowWidth: window.innerWidth,
      windowHeight: window.innerHeight,
      height: window.innerHeight,
    })
    lastScreenshotAt = Date.now()
    post('craftbot-dev-screenshot', { dataUrl: canvas.toDataURL('image/png') })
  } catch {
    /* screenshot is best-effort */
  } finally {
    screenshotBusy = false
  }
}

function installDesignTelemetry() {
  setInterval(
    guarded(() => {
      const hidden = document.querySelector(`#root *:not([${REVEAL_ATTR}])`)
      if (hidden) return // layout still assembling — measure when settled
      saveSnapshot()
      reportMetrics()
      void captureScreenshotSoon()
    }),
    5000,
  )
}

// ── boot ────────────────────────────────────────────────────────────────────

try {
  loadLedger()
  installStaging()
  installFetchFallback()
  installHmrRelay()
  installDesignTelemetry()

  const root = document.getElementById('root')
  if (root) {
    new MutationObserver(() => scheduleScan()).observe(root, {
      childList: true,
      subtree: true,
    })
    scheduleScan()
  } else {
    failOpen('no #root')
  }
  window.addEventListener('pagehide', () => {
    saveSnapshot()
    try {
      sessionStorage.setItem(LEDGER_KEY, JSON.stringify(Array.from(ledger).slice(-LEDGER_MAX)))
    } catch {
      /* cosmetic */
    }
  })
} catch (e) {
  failOpen(String(e))
}
