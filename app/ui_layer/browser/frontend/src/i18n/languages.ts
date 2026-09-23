// Single source of truth for the set of UI languages CraftBot ships.
// The `label` is the language's own endonym and is deliberately NOT translated
// so a user who lands in the wrong language can always find their way back.

export interface SupportedLanguage {
  /** i18next language code, also stored in settings.json `general.ui_language`. */
  code: string
  /** Self-name of the language, shown verbatim in the selector. */
  label: string
}

export const SUPPORTED_LANGUAGES: readonly SupportedLanguage[] = [
  { code: 'en', label: 'English' },
  { code: 'ja', label: '日本語' },
  { code: 'zh-CN', label: '简体中文' },
  { code: 'zh-TW', label: '繁體中文' },
  { code: 'ko', label: '한국어' },
  { code: 'es', label: 'Español' },
  { code: 'id', label: 'Bahasa Indonesia' },
] as const

export const DEFAULT_LANGUAGE = 'en'

export const SUPPORTED_CODES: readonly string[] = SUPPORTED_LANGUAGES.map(l => l.code)

export function isSupportedLanguage(code: string | null | undefined): boolean {
  return !!code && SUPPORTED_CODES.includes(code)
}

/**
 * Resolve an arbitrary BCP-47 tag (e.g. from navigator.language or a persisted
 * OS locale) to one of our supported UI languages. Returns null when nothing
 * reasonable matches, so callers decide the default.
 */
export function resolveSupportedLanguage(tag: string | null | undefined): string | null {
  if (!tag) return null
  const lower = tag.toLowerCase()

  // Exact match first (case-insensitive).
  const exact = SUPPORTED_CODES.find(c => c.toLowerCase() === lower)
  if (exact) return exact

  const [base, ...rest] = lower.split('-')
  const script = rest.join('-')

  if (base === 'zh') {
    // Script/region decides Simplified vs Traditional.
    if (script.includes('hant') || script.includes('tw') || script.includes('hk') || script.includes('mo')) {
      return 'zh-TW'
    }
    return 'zh-CN'
  }

  // Base-language match for the single-script languages.
  const baseMatch = SUPPORTED_CODES.find(c => c.split('-')[0] === base)
  return baseMatch ?? null
}
