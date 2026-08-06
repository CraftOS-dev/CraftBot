import type { Layout } from 'react-grid-layout'
import { COLS, SIZE_BOUNDS } from './constants'
import type { Breakpoint, BreakpointLayouts, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

const BREAKPOINT_KEYS: Breakpoint[] = ['lg', 'md', 'sm']

function num(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

/**
 * The four constraint fields every grid item carries, for one breakpoint.
 * Square by construction — see SIZE_BOUNDS. A minimum wider than the grid is
 * unsatisfiable and RGL will fight itself trying to honor both it and the
 * column count, so both bounds are capped at the column count.
 */
export function boundsFor(bp: Breakpoint) {
  const cols = COLS[bp]
  const { min, max } = SIZE_BOUNDS[bp]
  return {
    minW: Math.min(min, cols),
    minH: min,
    maxW: Math.min(max, cols),
    maxH: max,
  }
}

type ItemBounds = ReturnType<typeof boundsFor>

/** A grid item at its registry starting size, clamped into the bounds. */
export function seedItem(widgetId: string, bounds: ItemBounds, cols: number): Layout {
  const def = WIDGET_REGISTRY[widgetId].defaultLayout
  return {
    i: widgetId,
    x: 0,
    y: Infinity,
    w: clamp(def.w, bounds.minW, Math.min(bounds.maxW, cols)),
    h: clamp(def.h, bounds.minH, bounds.maxH),
    ...bounds,
  }
}

function normalizeItem(item: Layout, bounds: ItemBounds, cols: number): Layout | null {
  if (!item || typeof item !== 'object' || typeof item.i !== 'string') return null

  const def = WIDGET_REGISTRY[item.i]?.defaultLayout
  if (!def) return null // widget no longer exists in the registry

  const w = clamp(num(item.w, def.w), bounds.minW, Math.min(bounds.maxW, cols))
  const h = clamp(num(item.h, def.h), bounds.minH, bounds.maxH)
  const x = clamp(num(item.x, 0), 0, cols - w)
  // `y: Infinity` means "append at the bottom" and comes back from JSON as
  // null. Restore that intent rather than silently pinning the item to row 0.
  const y = num(item.y, Infinity)

  return { ...item, x, y, w, h, ...bounds }
}

function normalizeBreakpoint(items: unknown, widgetIds: string[], bp: Breakpoint): Layout[] {
  const bounds = boundsFor(bp)
  const cols = COLS[bp]
  const out: Layout[] = []
  const seen = new Set<string>()

  for (const item of Array.isArray(items) ? (items as Layout[]) : []) {
    const next = normalizeItem(item, bounds, cols)
    if (!next || seen.has(next.i)) continue
    seen.add(next.i)
    out.push(next)
  }

  // A widget on the layout but absent from this breakpoint would otherwise get
  // RGL's 1x1 fallback — below every registry minimum. Seed it instead.
  for (const id of widgetIds) {
    if (seen.has(id)) continue
    out.push(seedItem(id, bounds, cols))
  }

  return out
}

/**
 * Re-applies the current sizing constraints to a stored layout.
 *
 * Stored grid items are snapshots: `minW`/`minH`/`maxW`/`maxH` are copied out
 * of the constants once, at seed time (defaultLayout.ts / useDashboardLayouts'
 * emptyItemFor), and then round-tripped forever through react-grid-layout's
 * `onLayoutChange`. Editing SIZE_BOUNDS would therefore never reach anyone who
 * already has a stored layout. Running this on every read keeps the constants
 * the single source of truth, with no migration to remember to write — a
 * versioned one-shot would fix today's drift and reintroduce the same bug on
 * the next edit. `version` stays reserved for a genuine change of storage
 * *shape*, which is what migrateLayouts.ts handles.
 *
 * Pure and idempotent: normalize(normalize(x)) deep-equals normalize(x).
 *
 * Sizes are clamped in both directions — a widget stored outside the current
 * bounds is pulled back to the nearest one rather than left as an odd shape.
 */
export function normalizeLayout(layout: NamedLayout): NamedLayout {
  const widgetIds = (Array.isArray(layout.widgetIds) ? layout.widgetIds : [])
    .filter(id => typeof id === 'string' && !!WIDGET_REGISTRY[id])

  const stored = (layout.layouts ?? {}) as Partial<BreakpointLayouts>

  const layouts = BREAKPOINT_KEYS.reduce((acc, bp) => {
    acc[bp] = normalizeBreakpoint(stored[bp], widgetIds, bp)
    return acc
  }, {} as BreakpointLayouts)

  return { ...layout, widgetIds, layouts }
}

export function normalizeLayouts(layouts: NamedLayout[]): NamedLayout[] {
  // Runs inside a useState initializer — i.e. mid-render — so it must not throw
  // on malformed storage, or the whole page white-screens. Every field above is
  // guarded individually rather than trusting isValidStorage(), which doesn't
  // look inside `layouts` at all. Same hazard defaultLayout.ts documents for
  // KNOWN_ORDER.
  return (Array.isArray(layouts) ? layouts : [])
    .filter(l => !!l && typeof l === 'object' && typeof l.id === 'string')
    .map(normalizeLayout)
}
