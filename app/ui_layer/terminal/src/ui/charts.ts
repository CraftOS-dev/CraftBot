/**
 * Text charts for terminal screens. Pure functions that return plain strings
 * (no color, no ANSI), so callers color them with ink.* and measure them
 * with text/width.ts like any other text.
 *
 *   sparkline([3, 0, 8, 5], 20)   one row, one cell per value:  "▃▁█▆"
 *   bars(hourly, 48, 4)           `height` rows, top row first, for <Text> per row
 *   meter(0.42, 10)               "████░░░░░░"
 *   compactNumber(1532532)        "1.5M"
 *
 * Rules for callers:
 * - Always print the numbers next to the marks (a value, a max, a percent):
 *   a shape alone carries no meaning for screen readers, NO_COLOR or a
 *   quick read.
 * - Values below zero, NaN and Infinity count as 0. Scales start at 0, so a
 *   flat series of equal values is a full bar, not an empty one; pass `max`
 *   to share one scale between several charts.
 * - A zero is drawn as the lowest mark and any value above zero as at least
 *   the next one, so "nothing" and "a little" never look the same.
 * - Marks come from the active glyph set (theme.ts): block eighths on modern
 *   terminals, coarser blocks on the classic console, ASCII with `ascii`.
 */
import { glyphSetFor, glyphs, type GlyphSet } from '../theme/theme'

export interface ChartOptions {
  /** Top of the scale; defaults to the largest value. */
  max?: number
  /** Force ASCII marks (defaults to the active glyph set). */
  ascii?: boolean
}

function marks(opts?: ChartOptions): GlyphSet {
  return opts?.ascii ? glyphSetFor('ascii') : glyphs()
}

function clean(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 0
}

function scaleTop(values: number[], opts?: ChartOptions): number {
  const max = opts?.max !== undefined ? clean(opts.max) : Math.max(0, ...values)
  return max > 0 ? max : 0
}

/** Merge adjacent values (summed) until there are at most `count`. */
function merge(values: number[], count: number): number[] {
  if (values.length <= count) return values
  const out = new Array<number>(count).fill(0)
  values.forEach((v, i) => {
    out[Math.min(count - 1, Math.floor((i * count) / values.length))] += v
  })
  return out
}

/**
 * One row of block marks, one cell per value. With more values than `width`
 * the newest (rightmost) `width` are shown; with fewer, the string is shorter
 * than `width` (no padding).
 */
export function sparkline(values: number[], width: number, opts?: ChartOptions): string {
  if (width <= 0 || values.length === 0) return ''
  const shown = values.slice(-width).map(clean)
  const top = scaleTop(shown, opts)
  const spark = marks(opts).spark
  return shown
    .map(v => {
      if (v <= 0 || top <= 0) return spark[0]
      const level = Math.ceil(Math.min(1, v / top) * (spark.length - 1))
      return spark[Math.max(1, level)]
    })
    .join('')
}

/**
 * Vertical bars: an array of `height` strings, top row first, each exactly
 * `width` cells wide. Every value gets an equal column (with a one-cell gap
 * once columns are three cells or wider); with more values than `width`,
 * adjacent values are summed to fit. The top cell of a bar uses eighth
 * blocks, so `height` 4 resolves 32 levels.
 */
export function bars(values: number[], width: number, height: number, opts?: ChartOptions): string[] {
  if (width <= 0 || height <= 0) return []
  const blank = ' '.repeat(width)
  if (values.length === 0) return new Array<string>(height).fill(blank)
  const merged = merge(values.map(clean), width)
  const column = Math.max(1, Math.floor(width / merged.length))
  const barWidth = column >= 3 ? column - 1 : column
  const top = scaleTop(merged, opts)
  const g = marks(opts)
  const levels = height * 8
  const filled = merged.map(v => {
    if (v <= 0 || top <= 0) return 0
    return Math.max(1, Math.round(Math.min(1, v / top) * levels))
  })
  const rows: string[] = []
  for (let row = 0; row < height; row++) {
    // Eighths below this row's floor are already drawn by the rows beneath.
    const floor = (height - row - 1) * 8
    let line = ''
    for (const eighths of filled) {
      const inRow = Math.max(0, Math.min(8, eighths - floor))
      let cell: string
      if (inRow >= 8) cell = g.meterFull
      else if (inRow <= 0) cell = ' '
      else cell = g.eighths[inRow]
      line += cell.repeat(barWidth) + ' '.repeat(column - barWidth)
    }
    rows.push((line + blank).slice(0, width))
  }
  return rows
}

/**
 * A horizontal fill bar `width` cells wide for a fraction from 0 to 1.
 * Anything above 0 fills at least one cell and anything below 1 leaves at
 * least one cell empty, so "almost empty" and "almost full" stay visible.
 */
export function meter(fraction: number, width: number, opts?: ChartOptions): string {
  if (width <= 0) return ''
  const f = Number.isFinite(fraction) ? Math.min(1, Math.max(0, fraction)) : 0
  let cells = Math.round(f * width)
  if (f > 0 && cells === 0) cells = 1
  if (f < 1 && cells === width && width > 1) cells = width - 1
  const g = marks(opts)
  return g.meterFull.repeat(cells) + g.meterEmpty.repeat(width - cells)
}

/** Short counts for labels beside the marks: 999, 1.5k, 12k, 1.5M, 2.1B. */
export function compactNumber(value: number): string {
  const n = Number.isFinite(value) ? value : 0
  const sign = n < 0 ? '-' : ''
  let v = Math.abs(n)
  if (v < 1000) return sign + String(Math.round(v))
  for (const unit of ['k', 'M', 'B']) {
    v /= 1000
    const rounded = v >= 100 ? Math.round(v) : Math.round(v * 10) / 10
    // 999,960 is "1M", not "1000k".
    if (rounded < 1000 || unit === 'B') return `${sign}${rounded}${unit}`
  }
  return sign + String(Math.round(v))
}
