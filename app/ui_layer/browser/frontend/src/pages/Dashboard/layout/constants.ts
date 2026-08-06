import type { Breakpoint } from './types'

export const STORAGE_KEY_LAYOUTS = 'craftbot.dashboard.layouts'
export const STORAGE_KEY_ACTIVE_ID = 'craftbot.dashboard.activeLayoutId'

export const BREAKPOINTS: Record<Breakpoint, number> = { lg: 1200, md: 900, sm: 600 }
export const COLS: Record<Breakpoint, number> = { lg: 10, md: 8, sm: 4 }
export const MARGIN: [number, number] = [12, 12]
export const CONTAINER_PADDING: [number, number] = [12, 12]

// There is no ROW_HEIGHT constant on purpose: grid cells are square, so the row
// height is whatever the column width happens to be at the current container
// width. DashboardGrid measures and derives it — see `columnWidth` below.

/**
 * The resize floor every widget shares, in grid cells — square, and since cells
 * are square pixels, a widget at its minimum is a square on screen at any window
 * size. `lg` is 10 columns precisely so this comes out whole: 5 minimum widgets
 * per row. Narrower breakpoints keep the same floor and give up per-row density
 * rather than shrinking the tile below what its content can use.
 *
 * It's also the *unit* widget sizes are written in. `widgets/registry.ts` states
 * every size as a multiple of this tile — `{ w: 1.5, h: 1 }` is "half again as
 * wide as the minimum, exactly as tall" — because that's how the sizes are
 * specified in review, and one conversion here beats twelve mental ones there.
 * Ceilings are per-widget and, unlike the floor, need not be square.
 */
export const WIDGET_MIN_CELLS = 2

export function unitsToCells(units: number): number {
  return Math.max(WIDGET_MIN_CELLS, Math.round(units * WIDGET_MIN_CELLS))
}

/** Width of one grid column — and therefore the height of one grid row. */
export function columnWidth(width: number, cols: number): number {
  return (width - 2 * CONTAINER_PADDING[0] - (cols - 1) * MARGIN[0]) / cols
}

/**
 * Which breakpoint a container width falls into. Mirrors react-grid-layout's
 * own rule (largest breakpoint whose threshold the width clears, smallest as
 * the floor) so our derived row height always agrees with the column count RGL
 * picked from the same number.
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
