import i18n, { type Resource } from 'i18next'
import { initReactI18next } from 'react-i18next'
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_CODES,
  isSupportedLanguage,
  resolveSupportedLanguage,
} from './languages'

export const LANGUAGE_STORAGE_KEY = 'craftbot-language'

// Every catalog under src/locales/<lng>/<namespace>.json is bundled eagerly.
// Adding a new namespace file is picked up automatically — no registration here.
const catalogs = import.meta.glob('../locales/*/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, Record<string, unknown>>

const resources: Resource = {}
for (const [path, data] of Object.entries(catalogs)) {
  const match = /\/locales\/([^/]+)\/([^/]+)\.json$/.exec(path)
  if (!match) continue
  const [, lng, namespace] = match
  ;(resources[lng] ??= {})[namespace] = data
}

export const NAMESPACES = Array.from(
  new Set(Object.values(resources).flatMap(ns => Object.keys(ns))),
)

/** Language to render on first paint, before the server-persisted value arrives. */
function detectInitialLanguage(): string {
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (isSupportedLanguage(stored)) return stored as string
  return resolveSupportedLanguage(navigator.language) ?? DEFAULT_LANGUAGE
}

i18n.use(initReactI18next).init({
  resources,
  lng: detectInitialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: SUPPORTED_CODES as string[],
  load: 'currentOnly',
  defaultNS: 'common',
  ns: NAMESPACES,
  interpolation: {
    // React already escapes rendered values.
    escapeValue: false,
  },
  returnNull: false,
})

// Keep the document language attribute and the persisted preference in lockstep
// with the active UI language. `lang` also drives CJK font/glyph selection
// (notably Simplified vs Traditional Chinese) in the browser.
function syncDocumentLanguage(lng: string) {
  document.documentElement.lang = lng
}

syncDocumentLanguage(i18n.language)
i18n.on('languageChanged', lng => {
  syncDocumentLanguage(lng)
  localStorage.setItem(LANGUAGE_STORAGE_KEY, lng)
})

/**
 * Apply a UI language chosen by the user. Persists to localStorage (via the
 * languageChanged listener) so the choice survives a reload before the server
 * round-trip completes.
 */
export function setUiLanguage(code: string): void {
  if (!isSupportedLanguage(code) || code === i18n.language) return
  void i18n.changeLanguage(code)
}

export default i18n
