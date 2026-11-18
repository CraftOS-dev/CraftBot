/**
 * Terminal replacement for the browser frontend's `i18n/config.ts`.
 *
 * Same i18next instance contract (default export, `setUiLanguage`,
 * `LANGUAGE_STORAGE_KEY`, `NAMESPACES`) so the shared store's slices work
 * unchanged. Catalogs are the browser's own locale files, read-only, plus the
 * terminal's `tui` namespace (terminal-only strings such as key hints); the
 * build bundles both through the `virtual:locales` module (build.mjs).
 */
import i18n, { type Resource } from 'i18next'
import { initReactI18next } from 'react-i18next'
import catalogs from 'virtual:locales'
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_CODES,
  isSupportedLanguage,
  resolveSupportedLanguage,
} from '../../../browser/frontend/src/i18n/languages'

export const LANGUAGE_STORAGE_KEY = 'craftbot-language'

const resources: Resource = {}
for (const [lng, namespaces] of Object.entries(catalogs)) {
  resources[lng] = { ...namespaces }
}

export const NAMESPACES = Array.from(
  new Set(Object.values(resources).flatMap(ns => Object.keys(ns))),
)

function detectInitialLanguage(): string {
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (isSupportedLanguage(stored)) return stored as string
  const envTag = (process.env.LC_ALL || process.env.LC_MESSAGES || process.env.LANG || '').split('.')[0]
  return resolveSupportedLanguage(envTag.replace('_', '-')) ?? DEFAULT_LANGUAGE
}

void i18n.use(initReactI18next).init({
  resources,
  lng: detectInitialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: SUPPORTED_CODES as string[],
  load: 'currentOnly',
  defaultNS: 'common',
  ns: NAMESPACES,
  interpolation: { escapeValue: false },
  returnNull: false,
  initImmediate: false,
})

i18n.on('languageChanged', lng => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, lng)
})

/** Apply a UI language chosen by the user (or loaded from settings). */
export function setUiLanguage(code: string): void {
  if (!isSupportedLanguage(code) || code === i18n.language) return
  void i18n.changeLanguage(code)
}

export default i18n
