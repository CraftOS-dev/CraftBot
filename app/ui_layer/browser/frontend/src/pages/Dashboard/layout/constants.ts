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
 * The one resize floor and ceiling every widget shares, in grid cells.
 *
 * Both bounds are square *numbers*, and cells are square *pixels*, so a widget
 * at either bound is a square on screen at any window size. `lg` is 10 columns
 * precisely so the ratios come out whole: 5 minimum widgets per row, 2 maximum
 * ones. Narrower breakpoints keep the same floor and give up per-row density
 * instead of shrinking the tile below what its content can use.
 */
export const SIZE_BOUNDS: Record<Breakpoint, { min: number; max: number }> = {
  lg: { min: 2, max: 5 }, // 10 cols → 5 per row at min, 2 per row at max
  md: { min: 2, max: 4 }, //  8 cols → 4 per row at min, 2 per row at max
  sm: { min: 2, max: 4 }, //  4 cols → 2 per row at min, 1 per row at max
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
