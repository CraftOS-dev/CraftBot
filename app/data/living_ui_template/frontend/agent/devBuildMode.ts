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

// shadcn <Skeleton> renders `animate-pulse` (frontend/components/ui/skeleton.tsx).
const LK_CLASSES = {
  skeleton: 'animate-pulse',
} as const

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

/** Structural fingerprint: tag + first-class + child-index path from #root.
 * Stable across re-renders of the same component (classes are static in
 * this codebase); new structure = new fingerprint. The class token is
 * load-bearing: without it, a real component that replaces a wireframe
 * skeleton at the same DOM position collides with the skeleton's
 * fingerprint and is treated as "already revealed" — no reveal animation
 * and no dock showcase for the entire replaced subtree. */
function fingerprintOf(el: Element, root: Element): string {
  const parts: string[] = []
  let node: Element | null = el
  while (node && node !== root) {
    const parent: Element | null = node.parentElement
    if (!parent) break
    let idx = 0
    for (let c = node.previousElementSibling; c; c = c.previousElementSibling) idx++
    const cls = node.classList.length > 0 ? `.${node.classList[0]}` : ''
    parts.push(`${node.tagName}${cls}:${idx}`)
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
    else scheduleShowcase()
    return
  }
  markRevealed(item.el, item.fp)
  item.el.classList.add(item.isBlock ? ANIM_BLOCK : ANIM_LEAF)
  item.el.addEventListener(
    'animationend',
    () => item!.el.classList.remove(ANIM_BLOCK, ANIM_LEAF),
    { once: true },
  )
  if (item.isBlock) burstRoots.push(item.el)
  narrate(item.el, item.isBlock)
  lastProgressAt = Date.now()
  if (queue.length > 0) {
    setTimeout(drainTick, item.isBlock ? Math.max(revealDelay(), 200) : revealDelay())
  } else {
    draining = false
    scheduleShowcase()
  }
})

// ── component showcase ──────────────────────────────────────────────────────
// After a reveal burst settles, rasterize the newly arrived components and
// send them to the host dock, which plays them one after another in place
// of the code snippet — the user watches their app's actual parts appear.
// All numbers below are geometry/pacing bounds for the dock's small
// landscape stage, not policy: they define what can be LEGIBLY rendered.

const SHOWCASE_LEDGER_KEY = 'craftbot-showcase-ledger'
// Let the reveal animations (≤460ms) finish before rasterizing.
const SHOWCASE_SETTLE_MS = 500
// Beyond ~3:1 either way the render is an illegible strip (e.g. a whole
// nav bar) — recurse into its children (its buttons etc.) instead.
const SHOWCASE_MAX_ASPECT = 3.2
// Below this an element is a fragment (bare icon, divider), not a
// component. Sits BELOW standard control height — 36px buttons/inputs
// are legitimate showcase items — and above bare-icon size (~24px).
const SHOWCASE_MIN_EDGE_PX = 28
// Above this fraction of the viewport it IS the page — which the live
// preview already shows; recurse into children instead.
const SHOWCASE_MAX_VIEWPORT_FRACTION = 0.65
// Bounded recursion/work per burst; extras are simply not shown.
const SHOWCASE_MAX_DEPTH = 4
const SHOWCASE_MAX_PER_BURST = 5
// Rasterization edge cap — the dock displays smaller than this anyway.
const SHOWCASE_MAX_EDGE_PX = 560
// Small components are RE-RENDERED (not upscaled) at up to this scale so
// the dock can zoom them to fill its stage without blur.
const SHOWCASE_MAX_CAPTURE_SCALE = 3

const burstRoots: HTMLElement[] = []
const showcaseLedger = new Set<string>()
let showcaseTimer: number | undefined
let showcaseBusy = false

function loadShowcaseLedger() {
  try {
    const raw = sessionStorage.getItem(SHOWCASE_LEDGER_KEY)
    if (raw) JSON.parse(raw).forEach((fp: string) => showcaseLedger.add(fp))
  } catch {
    /* fresh start is fine */
  }
}

function persistShowcaseLedger() {
  try {
    sessionStorage.setItem(
      SHOWCASE_LEDGER_KEY,
      JSON.stringify(Array.from(showcaseLedger).slice(-LEDGER_MAX)),
    )
  } catch {
    /* quota — re-showcasing after reload is cosmetic */
  }
}

function showcaseSuitability(el: HTMLElement): 'fit' | 'too-big' | 'unfit' {
  const rect = el.getBoundingClientRect()
  if (rect.width < SHOWCASE_MIN_EDGE_PX || rect.height < SHOWCASE_MIN_EDGE_PX) {
    return 'unfit'
  }
  const vw = window.innerWidth || 1
  const vh = window.innerHeight || 1
  if (rect.width * rect.height > vw * vh * SHOWCASE_MAX_VIEWPORT_FRACTION) {
    return 'too-big'
  }
  const aspect = rect.width / Math.max(rect.height, 1)
  if (aspect > SHOWCASE_MAX_ASPECT || aspect < 1 / SHOWCASE_MAX_ASPECT) {
    // An illegible strip (nav bar, tall rail) — show what's inside instead.
    return 'too-big'
  }
  return 'fit'
}

/** Collect showable elements: a fit element is taken whole; an oversized or
 * strip-shaped one is descended into (its cards, buttons, forms). */
function collectShowcaseCandidates(
  el: HTMLElement,
  depth: number,
  out: HTMLElement[],
) {
  if (out.length >= SHOWCASE_MAX_PER_BURST || depth > SHOWCASE_MAX_DEPTH) return
  // Skeletons are placeholders (wireframe / loading), never a built component.
  if (el.classList.contains(LK_CLASSES.skeleton)) return
  const fit = showcaseSuitability(el)
  if (fit === 'fit') {
    if (!el.querySelector('.' + LK_CLASSES.skeleton)) out.push(el)
    return
  }
  if (fit === 'too-big') {
    for (const child of Array.from(el.children)) {
      if (child instanceof HTMLElement) {
        collectShowcaseCandidates(child, depth + 1, out)
      }
    }
  }
}

function showcaseLabelFor(el: HTMLElement): string {
  const heading = el.querySelector('h1, h2, h3, h4')
  const text = (heading?.textContent || '').trim()
  if (text) return text.slice(0, 40)
  if (el.querySelector('form, input, select, textarea')) return 'Form'
  if (el.querySelector('table')) return 'Table'
  if (el.tagName === 'BUTTON') return (el.textContent || '').trim().slice(0, 40)
  return ''
}

/** Rasterize elements and send them to the dock. Shared by the burst
 * showcase (#root arrivals) and the surface tour (portal contents). */
async function rasterizeAndPost(
  els: HTMLElement[],
  root: Element | null,
  labelFallback = '',
) {
  if (showcaseBusy || dead) return
  showcaseBusy = true
  try {
    const mod: any = await import('html2canvas')
    const html2canvas = mod.default || mod
    const bodyBg = getComputedStyle(document.body).backgroundColor
    for (const el of els.slice(0, SHOWCASE_MAX_PER_BURST)) {
      if (dead || !el.isConnected) continue
      if (root) {
        const fp = fingerprintOf(el, root)
        if (showcaseLedger.has(fp)) continue
        showcaseLedger.add(fp)
      }
      const rect = el.getBoundingClientRect()
      const canvas = await html2canvas(el, {
        logging: false,
        backgroundColor: bodyBg,
        // Downscale big elements to the cap; RE-RENDER small ones larger
        // (crisp — html2canvas redraws the DOM, it doesn't upscale pixels)
        // so the dock can zoom them to fill its stage.
        scale: Math.min(
          SHOWCASE_MAX_EDGE_PX / Math.max(rect.width, rect.height, 1),
          SHOWCASE_MAX_CAPTURE_SCALE,
        ),
      })
      post('craftbot-dev-component', {
        dataUrl: canvas.toDataURL('image/png'),
        width: canvas.width,
        height: canvas.height,
        // The element's ON-SCREEN size: the dock displays at this size (or
        // smaller), so the high-res capture renders crisp, never blown up.
        cssWidth: Math.round(rect.width),
        cssHeight: Math.round(rect.height),
        label: showcaseLabelFor(el) || labelFallback,
      })
    }
    persistShowcaseLedger()
  } finally {
    showcaseBusy = false
  }
}

const processShowcase = guarded(() => {
  void (async () => {
    if (showcaseBusy || dead) return
    const root = document.getElementById('root')
    if (!root) return
    const burst = burstRoots.splice(0)
    // Topmost new blocks only — children of another burst root are already
    // inside their parent's picture.
    const set = new Set(burst)
    const tops = burst.filter(el => {
      if (!el.isConnected) return false
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (set.has(p)) return false
      }
      return true
    })
    const candidates: HTMLElement[] = []
    for (const el of tops) collectShowcaseCandidates(el, 0, candidates)

    const fresh = candidates.filter(el => !showcaseLedger.has(fingerprintOf(el, root)))
    if (fresh.length > 0) await rasterizeAndPost(fresh, root)
    scheduleTour() // new content may include newly registered hidden surfaces
  })().catch(() => {
    showcaseBusy = false /* showcase is best-effort, never break the engine */
  })
})

function scheduleShowcase() {
  if (dead) return
  if (showcaseTimer) clearTimeout(showcaseTimer)
  showcaseTimer = window.setTimeout(processShowcase, SHOWCASE_SETTLE_MS)
}

// ── surface tour ────────────────────────────────────────────────────────────
// Hidden surfaces (modals, drawers, menus, inactive tabs) never appear in
// the resting page. The overlay presets register dev-only open/close handles
// (components/ui/devtour.ts); the tour briefly opens each newly registered
// one — the REAL component renders in its REAL context, the dock narrates
// and captures it — then closes and moves on. Fail-open everywhere: any
// error hides the surface and stops; the tour is cosmetic, never load-
// bearing. Ledger in sessionStorage: each surface tours once, not per HMR.

const TOUR_LEDGER_KEY = 'craftbot-tour-ledger'
// Let the surface's mount animation and content render before capturing.
const TOUR_MOUNT_MS = 650
// How long an opened surface stays up once its content is visible.
const TOUR_HOLD_MS = 2600
// Breath between two toured surfaces.
const TOUR_GAP_MS = 450
// Never tour while the user is actively interacting with the preview.
const TOUR_USER_IDLE_MS = 4000
// Bounded wait for reveals inside a toured surface (fail-open: proceed).
const TOUR_SETTLE_TIMEOUT_MS = 6000
const TOUR_SETTLE_POLL_MS = 200
// Debounce after a burst/registration before the tour steps in.
const TOUR_START_DELAY_MS = 900

interface DevSurface {
  kind: string
  label: () => string
  show: () => void
  hide: () => void
  node: () => HTMLElement | null
}

const surfaces: DevSurface[] = []
const tourLedger = new Set<string>()
let touring = false
let tourTimer: number | undefined
let lastUserInputAt = 0

function loadTourLedger() {
  try {
    const raw = sessionStorage.getItem(TOUR_LEDGER_KEY)
    if (raw) JSON.parse(raw).forEach((k: string) => tourLedger.add(k))
  } catch {
    /* fresh start is fine */
  }
}

function persistTourLedger() {
  try {
    sessionStorage.setItem(
      TOUR_LEDGER_KEY,
      JSON.stringify(Array.from(tourLedger).slice(-LEDGER_MAX)),
    )
  } catch {
    /* quota — re-touring after reload is cosmetic */
  }
}

function surfaceKey(s: DevSurface): string {
  return `${s.kind}:${s.label()}`
}

function installSurfaceRegistry() {
  ;(window as any).__CB_DEV_SURFACES__ = {
    register(handle: DevSurface) {
      surfaces.push(handle)
      scheduleTour()
      return () => {
        const i = surfaces.indexOf(handle)
        if (i !== -1) surfaces.splice(i, 1)
      }
    },
  }
  const markInput = () => {
    lastUserInputAt = Date.now()
  }
  window.addEventListener('pointerdown', markInput, true)
  window.addEventListener('keydown', markInput, true)
  window.addEventListener('wheel', markInput, { capture: true, passive: true })
}

function sleep(ms: number) {
  return new Promise<void>(resolve => setTimeout(resolve, ms))
}

async function waitForRevealSettle(timeoutMs: number) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const hidden = document.querySelector(`#root *:not([${REVEAL_ATTR}])`)
    if (!hidden && queue.length === 0 && !showcaseBusy) return
    await sleep(TOUR_SETTLE_POLL_MS)
  }
}

function scheduleTour() {
  if (dead || touring) return
  if (tourTimer) clearTimeout(tourTimer)
  tourTimer = window.setTimeout(() => void runTour(), TOUR_START_DELAY_MS)
}

async function runTour() {
  if (touring || dead) return
  // The user is driving — stay out of the way and try again later.
  if (Date.now() - lastUserInputAt < TOUR_USER_IDLE_MS) {
    scheduleTour()
    return
  }
  let next: DevSurface | undefined
  try {
    next = surfaces.find(s => !tourLedger.has(surfaceKey(s)))
  } catch {
    return
  }
  if (!next) return
  touring = true
  let shown = false
  try {
    tourLedger.add(surfaceKey(next))
    persistTourLedger()
    post('craftbot-dev-reveal', { label: `Showing: ${next.label()}` })
    next.show()
    shown = true
    await sleep(TOUR_MOUNT_MS)
    // Inline surfaces (tabs, menus) mount inside #root — let the reveal
    // choreography (and its burst showcase) play out first.
    await waitForRevealSettle(TOUR_SETTLE_TIMEOUT_MS)
    // Portal surfaces (modals, drawers) live OUTSIDE #root where the
    // reveal engine can't see them — capture them directly.
    const el = next.node()
    if (el && el.isConnected) {
      const candidates: HTMLElement[] = []
      collectShowcaseCandidates(el, 0, candidates)
      await rasterizeAndPost(
        candidates.length > 0 ? candidates : [el],
        document.getElementById('root'),
        next.label(),
      )
    }
    await sleep(TOUR_HOLD_MS)
  } catch {
    /* fail-open: close and continue below */
  }
  try {
    if (shown) next.hide()
  } catch {
    /* never block */
  }
  touring = false
  await sleep(TOUR_GAP_MS)
  scheduleTour() // more untoured surfaces may remain
}

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

function emptyBodyFor(url: string, method: string): string {
  if (method === 'GET') {
    return /\/api\/state\b/.test(url) ? '{}' : '[]'
  }
  return '{"status":"ok","devFallback":true}'
}

function installFetchFallback() {
  const realFetch = window.fetch.bind(window)
  window.fetch = function (input: RequestInfo | URL, init?: RequestInit) {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    const method = ((init && init.method) || 'GET').toUpperCase()
    // API calls are same-origin (/api proxied to PocketBase), so a path
    // check identifies backend traffic for both relative and absolute URLs.
    let targetsBackend = false
    try {
      targetsBackend = new URL(url, window.location.href).pathname.startsWith(
        '/api',
      )
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
  // boundary showing the previous snapshot), nor a mid-tour state (a
  // toured tab/menu is not the resting page).
  if (snapshotRestored || touring || (window as any).__CB_APP_CRASHED__) return
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

// ── periodic snapshot keeper ────────────────────────────────────────────────
// Refreshes the last-good-state DOM snapshot while the app is healthy so a
// mid-write broken module graph can fall back to the last working pixels.

function installSnapshotKeeper() {
  setInterval(
    guarded(() => {
      if (touring) return // a toured surface is open — not the resting page
      const hidden = document.querySelector(`#root *:not([${REVEAL_ATTR}])`)
      if (hidden) return // layout still assembling — snapshot when settled
      saveSnapshot()
    }),
    5000,
  )
}

// ── boot ────────────────────────────────────────────────────────────────────

try {
  loadLedger()
  loadShowcaseLedger()
  loadTourLedger()
  installSurfaceRegistry()
  installStaging()
  installFetchFallback()
  installHmrRelay()
  installSnapshotKeeper()

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
