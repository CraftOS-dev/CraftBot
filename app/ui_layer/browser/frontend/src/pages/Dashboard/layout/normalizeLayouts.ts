import type { Layout } from 'react-grid-layout'
import { COLS } from './constants'
import type { Breakpoint, BreakpointLayouts, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

const BREAKPOINT_KEYS: Breakpoint[] = ['lg', 'md', 'sm']

function num(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function normalizeItem(item: Layout, cols: number): Layout | null {
  if (!item || typeof item !== 'object' || typeof item.i !== 'string') return null

  const def = WIDGET_REGISTRY[item.i]?.defaultLayout
  if (!def) return null // widget no longer exists in the registry

  // A minimum wider than the breakpoint's grid is unsatisfiable, and RGL will
  // fight itself trying to honor both it and the column count. Cap it.
  const minW = Math.min(def.minW ?? 1, cols)
  const minH = def.minH ?? 1

  const w = Math.min(Math.max(num(item.w, def.w), minW), cols)
  const h = Math.max(num(item.h, def.h), minH)
  const x = Math.min(Math.max(num(item.x, 0), 0), cols - w)
  // `y: Infinity` means "append at the bottom" and comes back from JSON as
  // null. Restore that intent rather than silently pinning the item to row 0.
  const y = num(item.y, Infinity)

  return { ...item, x, y, w, h, minW, minH }
}

function normalizeBreakpoint(items: unknown, widgetIds: string[], cols: number): Layout[] {
  const out: Layout[] = []
  const seen = new Set<string>()

  for (const item of Array.isArray(items) ? (items as Layout[]) : []) {
    const next = normalizeItem(item, cols)
    if (!next || seen.has(next.i)) continue
    seen.add(next.i)
    out.push(next)
  }

  // A widget on the layout but absent from this breakpoint would otherwise get
  // RGL's 1x1 fallback — below every registry minimum. Seed it instead.
  for (const id of widgetIds) {
    if (seen.has(id)) continue
    const def = WIDGET_REGISTRY[id].defaultLayout
    out.push({
      i: id,
      x: 0,
      y: Infinity,
      w: Math.min(def.w, cols),
      h: def.h,
      minW: Math.min(def.minW ?? 1, cols),
      minH: def.minH ?? 1,
    })
  }

  return out
}

/**
 * Re-applies the registry's current sizing constraints to a stored layout.
 *
 * Stored grid items are snapshots: `minW`/`minH` are copied out of the registry
 * once, at seed time (defaultLayout.ts / useDashboardLayouts' emptyItemFor), and
 * then round-tripped forever through react-grid-layout's `onLayoutChange`.
 * Editing registry.ts therefore never reaches anyone who already has a stored
 * layout. Running this on every read keeps the registry the single source of
 * truth for constraints, with no migration to remember to write — a versioned
 * one-shot would fix today's drift and reintroduce the same bug on the next
 * edit. `version` stays reserved for a genuine change of storage *shape*.
 *
 * Pure and idempotent: normalize(normalize(x)) deep-equals normalize(x).
 *
 * Sizes are only ever clamped UP to the new minimum — a widget the user
 * deliberately made larger is left alone.
 */
export function normalizeLayout(layout: NamedLayout): NamedLayout {
  const widgetIds = (Array.isArray(layout.widgetIds) ? layout.widgetIds : [])
    .filter(id => typeof id === 'string' && !!WIDGET_REGISTRY[id])

  const stored = (layout.layouts ?? {}) as Partial<BreakpointLayouts>

  const layouts = BREAKPOINT_KEYS.reduce((acc, bp) => {
    acc[bp] = normalizeBreakpoint(stored[bp], widgetIds, COLS[bp])
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
