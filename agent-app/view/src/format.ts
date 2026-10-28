/** How one value reads in a cell: dates, money, percents and plain text. */
import { get } from './pointer.ts'
import type { Format } from './types.ts'

const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/

export function isScalar(value: unknown): boolean {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}

export function looksLikeDate(value: unknown): boolean {
  return typeof value === 'string' && ISO_DATE.test(value.trim())
}

function formatDate(value: unknown, withTime: boolean, locale: string): string {
  if (typeof value !== 'string' || !value.trim()) return ''
  const day = /^\d{4}-\d{2}-\d{2}$/.test(value.trim())
  const date = new Date(day ? `${value.trim()}T00:00:00` : value.trim().replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return value
  const options: Intl.DateTimeFormatOptions = withTime && !day
    ? { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { year: 'numeric', month: 'short', day: 'numeric' }
  return date.toLocaleString(locale, options)
}

function currencyOf(format: string, source: unknown): string | undefined {
  const spec = format.slice('money:'.length)
  if (!spec) return undefined
  if (spec.startsWith('/')) {
    const code = get(source, spec)
    return typeof code === 'string' ? code : undefined
  }
  return spec
}

/** Text for one value. `source` is the whole op result (for money:/pointer). */
export function formatValue(value: unknown, format: Format | undefined, source: unknown, locale = 'en'): string {
  if (value === undefined || value === null || value === '') return ''
  const f = format ?? 'text'
  if (f === 'date') return formatDate(value, false, locale)
  if (f === 'datetime') return formatDate(value, true, locale)
  if (f === 'boolean') return value === true || value === 'true' ? 'yes' : 'no'
  if (f === 'percent') {
    const n = Number(value)
    return Number.isFinite(n) ? `${Math.round(n * (Math.abs(n) <= 1 && !Number.isInteger(n) ? 100 : 1))}%` : String(value)
  }
  if (f === 'number') {
    const n = Number(value)
    return Number.isFinite(n) ? n.toLocaleString(locale) : String(value)
  }
  if (f === 'money' || f.startsWith('money:')) {
    const n = Number(value)
    if (!Number.isFinite(n)) return String(value)
    const currency = f === 'money' ? undefined : currencyOf(f, source)
    try {
      return currency
        ? n.toLocaleString(locale, { style: 'currency', currency })
        : n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    } catch {
      return n.toLocaleString(locale)
    }
  }
  if (typeof value === 'string') return looksLikeDate(value) ? formatDate(value, value.length > 10, locale) : value.replace(/\s+/g, ' ')
  if (typeof value === 'number') return value.toLocaleString(locale)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value)) return value.every(isScalar) ? value.join(', ') : `${value.length} items`
  return JSON.stringify(value)
}

/** "created_at" -> "Created at", "dueDate" -> "Due date". */
export function humanize(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_.-]+/g, ' ')
    .trim()
    .toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
