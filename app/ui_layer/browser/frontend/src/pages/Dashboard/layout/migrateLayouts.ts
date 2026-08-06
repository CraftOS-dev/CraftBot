import type { Layout } from 'react-grid-layout'
import { COLS } from './constants'
import type { Breakpoint, NamedLayout } from './types'

export const STORAGE_VERSION = 2

// What v1 grid units meant: 12 columns at lg, and rows of a fixed 32px, i.e. a
// 44px vertical pitch once the 12px margin is counted.
const V1_COLS: Record<Breakpoint, number> = { lg: 12, md: 8, sm: 4 }
const V1_ROW_PITCH = 44

// What they mean in v2: cells are square, so one row is a full column tall.
// On a typical ~1680px-wide dashboard an lg column is ~155px, giving a ~167px
// pitch. It only has to be in the right ballpark — a stored size is converted
// to roughly the same number of *pixels* the user dragged it to, and
// normalizeLayout then clamps whatever lands outside the new square bounds.
const V2_NOMINAL_ROW_PITCH = 167

const BREAKPOINT_KEYS: Breakpoint[] = ['lg', 'md', 'sm']

function scale(value: unknown, factor: number, min: number): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return Math.max(min, Math.round(value * factor))
}

function migrateItem(item: Layout, colFactor: number, rowFactor: number): Layout {
  const next: Layout = { ...item }

  const w = scale(item.w, colFactor, 1)
  const h = scale(item.h, rowFactor, 1)
  const x = scale(item.x, colFactor, 0)
  const y = scale(item.y, rowFactor, 0)

  if (w !== undefined) next.w = w
  if (h !== undefined) next.h = h
  if (x !== undefined) next.x = x
  // `y: Infinity` ("append at the bottom") isn't finite, so scale() leaves it
  // alone and normalizeLayout restores the intent.
  if (y !== undefined) next.y = y

  // The old per-item constraint snapshots describe the v1 grid; drop them so
  // normalizeLayout re-applies the current ones rather than merging the two.
  delete next.minW
  delete next.minH
  delete next.maxW
  delete next.maxH

  return next
}

/**
 * Converts layouts stored under storage version 1 into v2 grid units.
 *
 * v2 changed what a unit *means*: lg went from 12 columns to 10, and rows went
 * from a fixed 32px to whatever a column is wide, so cells are square (see
 * SIZE_BOUNDS). Reading v1 numbers as v2 without this would leave every widget
 * roughly four times too tall. This is the storage-shape change `version` was
 * reserved for; ordinary constraint drift is still handled per-read by
 * normalizeLayouts, not here.
 *
 * Sizes come out approximate on purpose: the goal is that a saved dashboard
 * still looks like the one the user arranged, not that it survives to the
 * pixel. Must not throw — it runs inside a useState initializer.
 */
export function migrateV1(layouts: NamedLayout[]): NamedLayout[] {
  if (!Array.isArray(layouts)) return []

  const rowFactor = V1_ROW_PITCH / V2_NOMINAL_ROW_PITCH

  return layouts.map(layout => {
    if (!layout || typeof layout !== 'object' || !layout.layouts) return layout

    const migrated = { ...layout.layouts }
    for (const bp of BREAKPOINT_KEYS) {
      const items = layout.layouts[bp]
      if (!Array.isArray(items)) continue
      const colFactor = COLS[bp] / V1_COLS[bp]
      migrated[bp] = items.map(item => migrateItem(item, colFactor, rowFactor))
    }

    return { ...layout, layouts: migrated }
  })
}
