import type { Layout } from 'react-grid-layout'
import { COLS, WIDGET_MIN_CELLS, unitsToCells } from './constants'
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
 * The four constraint fields a widget's grid item carries, for one breakpoint.
 *
 * The floor is shared and square (WIDGET_MIN_CELLS); the ceiling comes from the
 * widget's own `sizing.max` and need not be square — several widgets cap at
 * their minimum height, i.e. resize width-only. A bound wider than the grid is
 * unsatisfiable and RGL will fight itself trying to honor both it and the
 * column count, so both are capped at the column count.
 */
export function boundsFor(bp: Breakpoint, widgetId: string) {
  const cols = COLS[bp]
  const { max } = WIDGET_REGISTRY[widgetId].sizing
  const minW = Math.min(WIDGET_MIN_CELLS, cols)
  return {
    minW,
    minH: WIDGET_MIN_CELLS,
    maxW: Math.max(minW, Math.min(unitsToCells(max.w), cols)),
    maxH: Math.max(WIDGET_MIN_CELLS, unitsToCells(max.h)),
  }
}

type ItemBounds = ReturnType<typeof boundsFor>

/** A grid item at its registry starting size, clamped into the bounds. */
export function seedItem(widgetId: string, bounds: ItemBounds): Layout {
  const { default: start } = WIDGET_REGISTRY[widgetId].sizing
  return {
    i: widgetId,
    x: 0,
    y: Infinity,
    w: clamp(unitsToCells(start.w), bounds.minW, bounds.maxW),
    h: clamp(unitsToCells(start.h), bounds.minH, bounds.maxH),
    ...bounds,
  }
}

function normalizeItem(item: Layout, bp: Breakpoint): Layout | null {
  if (!item || typeof item !== 'object' || typeof item.i !== 'string') return null
  if (!WIDGET_REGISTRY[item.i]) return null // widget no longer exists in the registry

  const bounds = boundsFor(bp, item.i)
  const seed = seedItem(item.i, bounds)

  const w = clamp(num(item.w, seed.w), bounds.minW, bounds.maxW)
  const h = clamp(num(item.h, seed.h), bounds.minH, bounds.maxH)
  const x = clamp(num(item.x, 0), 0, COLS[bp] - w)
  // `y: Infinity` means "append at the bottom" and comes back from JSON as
  // null. Restore that intent rather than silently pinning the item to row 0.
  const y = num(item.y, Infinity)

  return { ...item, x, y, w, h, ...bounds }
}

function normalizeBreakpoint(items: unknown, widgetIds: string[], bp: Breakpoint): Layout[] {
  const out: Layout[] = []
  const seen = new Set<string>()

  for (const item of Array.isArray(items) ? (items as Layout[]) : []) {
    const next = normalizeItem(item, bp)
    if (!next || seen.has(next.i)) continue
    seen.add(next.i)
    out.push(next)
  }

  // A widget on the layout but absent from this breakpoint would otherwise get
  // RGL's 1x1 fallback — below every widget's minimum. Seed it instead.
  for (const id of widgetIds) {
    if (seen.has(id)) continue
    out.push(seedItem(id, boundsFor(bp, id)))
  }

  return out
}

/**
 * Re-applies the current sizing constraints to a stored layout.
 *
 * Stored grid items are snapshots: `minW`/`minH`/`maxW`/`maxH` are copied out
 * of the registry once, at seed time (defaultLayout.ts / useDashboardLayouts'
 * emptyItemFor), and then round-tripped forever through react-grid-layout's
 * `onLayoutChange`. Editing a widget's `sizing` would therefore never reach
 * anyone who already has a stored layout. Running this on every read keeps the
 * registry the single source of truth, with no migration to remember to write —
 * a versioned one-shot would fix today's drift and reintroduce the same bug on
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
