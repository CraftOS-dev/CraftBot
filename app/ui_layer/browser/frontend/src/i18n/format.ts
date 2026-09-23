import i18n from './config'

// Date/number formatting follows the active UI language, not the browser locale.
// Intl handles every language we ship (en, ja, zh-CN, zh-TW, ko, es, id)
// natively, including the Simplified/Traditional Chinese distinction.
function activeLocale(): string {
  return i18n.language || 'en'
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(activeLocale(), options).format(value)
}

export function formatDate(
  value: Date | number,
  options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric' },
): string {
  return new Intl.DateTimeFormat(activeLocale(), options).format(value)
}

export function formatTime(
  value: Date | number,
  options: Intl.DateTimeFormatOptions = { hour: 'numeric', minute: '2-digit' },
): string {
  return new Intl.DateTimeFormat(activeLocale(), options).format(value)
}

export function formatDateTime(
  value: Date | number,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  },
): string {
  return new Intl.DateTimeFormat(activeLocale(), options).format(value)
}

/** Locale-aware string comparison for sorting user-facing lists. */
export function localeCompare(a: string, b: string): number {
  return a.localeCompare(b, activeLocale())
}

/** Join fragments into a natural-language list ("a, b, and c") in the active locale. */
export function formatList(
  items: string[],
  type: 'conjunction' | 'disjunction' = 'conjunction',
): string {
  return new Intl.ListFormat(activeLocale(), { style: 'long', type }).format(items)
}
