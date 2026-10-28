/**
 * Pure helpers of the dashboard screen: periods, the token split the browser
 * widgets use, the per-step token series and the hour axis under the bars.
 */
import type { MetricsTimePeriod, TokenMetrics } from '../../../browser/frontend/src/types'

export const PERIODS: MetricsTimePeriod[] = ['1h', '1d', '1w', '1m', 'total']

/** The previous (`-1`) or next (`1`) period, wrapping around at the ends. */
export function stepPeriod(period: MetricsTimePeriod, direction: -1 | 1): MetricsTimePeriod {
  const index = PERIODS.indexOf(period)
  const from = index < 0 ? PERIODS.length - 1 : index
  return PERIODS[(from + direction + PERIODS.length) % PERIODS.length]
}

export interface UptimeParts {
  days: number
  hours: number
  minutes: number
}

export function uptimeParts(seconds: number): UptimeParts {
  const s = Number.isFinite(seconds) && seconds > 0 ? seconds : 0
  return {
    days: Math.floor(s / 86400),
    hours: Math.floor((s % 86400) / 3600),
    minutes: Math.floor((s % 3600) / 60),
  }
}

export interface TokenSplit {
  /** New prompt tokens (the API's input minus cache reads). */
  input: number
  output: number
  cached: number
  /** input + output + cached: the base of the three shares. */
  base: number
  /** New tokens only (input + output), as the browser's total badge. */
  total: number
}

/**
 * The browser's TokenUsage widget split: `token.input` is the whole prompt,
 * cache reads included, so new input is input minus cached, and the three
 * shares use input + output + cached as their base (never `token.total`,
 * which double-counts cache reads).
 */
export function splitTokens(token: Partial<TokenMetrics> | undefined): TokenSplit {
  const rawInput = token?.input ?? 0
  const output = token?.output ?? 0
  const cached = token?.cached ?? 0
  const input = Math.max(0, rawInput - cached)
  return { input, output, cached, base: input + output + cached, total: input + output }
}

/** Share of `part` in `base` as a whole percent (0 when there is no base). */
export function percent(part: number, base: number): number {
  return base > 0 ? Math.min(100, Math.round((part / base) * 100)) : 0
}

/**
 * New tokens per fixed time bucket, built from the live metric pushes (the
 * backend keeps no token history over time). `buckets` ends at the bucket
 * holding the latest sample; samples are cumulative totals, so each bucket
 * gets the growth since the previous sample. A total that went down (the
 * backend restarted) starts a new baseline instead of counting as usage.
 */
export interface TokenSeries {
  bucketMs: number
  /** Start time (ms) of buckets[0]. */
  start: number
  lastTotal: number | null
  buckets: number[]
}

export function startSeries(bucketMs: number, now: number): TokenSeries {
  return { bucketMs, start: Math.floor(now / bucketMs) * bucketMs, lastTotal: null, buckets: [0] }
}

export function recordTokens(series: TokenSeries, total: number, now: number, maxBuckets: number): TokenSeries {
  const index = Math.max(0, Math.floor((now - series.start) / series.bucketMs))
  const buckets = series.buckets.slice()
  while (buckets.length <= index) buckets.push(0)
  if (series.lastTotal !== null && total > series.lastTotal) buckets[index] += total - series.lastTotal
  const drop = Math.max(0, buckets.length - Math.max(1, maxBuckets))
  return {
    bucketMs: series.bucketMs,
    start: series.start + drop * series.bucketMs,
    lastTotal: total,
    buckets: drop ? buckets.slice(drop) : buckets,
  }
}

/**
 * The hour labels under a 24-value bar chart drawn by charts.bars with the
 * same `width`: a label at hours 0, 6, 12 and 18 where it fits.
 */
export function hourAxis(width: number, hours = 24, label: (hour: number) => string = h => String(h)): string {
  if (width <= 0 || hours <= 0) return ''
  const values = Math.min(hours, width)
  const column = Math.max(1, Math.floor(width / values))
  const cells = new Array<string>(width).fill(' ')
  for (let hour = 0; hour < hours; hour += 6) {
    const index = Math.floor((hour * values) / hours)
    const start = index * column
    const text = label(hour)
    if (start + text.length > width) break
    // Keep one space between labels.
    if (start > 0 && cells[start - 1] !== ' ') continue
    for (let i = 0; i < text.length; i++) cells[start + i] = text[i]
  }
  return cells.join('')
}
