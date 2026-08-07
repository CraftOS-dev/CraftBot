import type { Breakpoint } from './types'

export const STORAGE_KEY_LAYOUTS = 'craftbot.dashboard.layouts'
export const STORAGE_KEY_ACTIVE_ID = 'craftbot.dashboard.activeLayoutId'

/**
 * Storage schema version. There is exactly one valid schema — this one.
 * Stored layouts under any other version are discarded on read and the
 * dashboard reseeds from the default; there is no migration code.
 */
export const STORAGE_VERSION = 3

/**
 * One grid cell IS one original dashboard card.
 *
 * The pre-revamp dashboard's panels measured ~315x249px: width from its
 * container queries (5 columns full-width, reflowing 4 / 2 as the dashboard
 * narrows — the thresholds below are that dashboard's own), height from
 * content, ~250px regardless of window size. The grid reproduces both: a
 * cell's width is its column (a fifth of the dashboard at full width), and a
 * row is a fixed ROW_HEIGHT — deliberately NOT tied to column width, exactly
 * like the original, so cards keep their height at any window size. Resizing
 * moves in whole-card steps.
 */
// The original's container queries switched at 1300/850/550px of *content*
// width; these are compared against the measured grid host, which still
// includes CONTAINER_PADDING (12px each side), hence the +24 — the reflow
// then happens at exactly the same window sizes the original reflowed at.
export const BREAKPOINTS: Record<Breakpoint, number> = { lg: 1324, md: 874, sm: 574 }
export const COLS: Record<Breakpoint, number> = { lg: 5, md: 4, sm: 2 }
export const ROW_HEIGHT = 250
export const MARGIN: [number, number] = [12, 12]
export const CONTAINER_PADDING: [number, number] = [12, 12]

/**
 * The min tile is a single card. It's also the *unit* widget sizes are written
 * in: `widgets/registry.ts` states every size in cards — `{ w: 2, h: 1 }` is
 * "two cards wide, one tall". Ceilings are per-widget and need not be square.
 */
export const WIDGET_MIN_CELLS = 1

export function unitsToCells(units: number): number {
  return Math.max(WIDGET_MIN_CELLS, Math.round(units * WIDGET_MIN_CELLS))
}

/**
 * Which breakpoint a container width falls into. Mirrors react-grid-layout's
 * own rule (largest breakpoint whose threshold the width clears, smallest as
 * the floor) so callers always agree with the column count RGL picked from
 * the same number.
 */
export function breakpointFromWidth(width: number): Breakpoint {
  const sorted = (Object.keys(BREAKPOINTS) as Breakpoint[])
    .sort((a, b) => BREAKPOINTS[a] - BREAKPOINTS[b])

  let match = sorted[0]
  for (const bp of sorted) {
    if (width > BREAKPOINTS[bp]) match = bp
  }
  return match
}
