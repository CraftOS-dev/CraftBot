import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import type { MiniBrowserError } from '../../types'

// Error codes the UI can meet, translated in minibrowser:errors.<CODE>. The
// backend's own text (English, possibly carrying specifics such as the URL
// or the underlying reason) becomes the "details" line for the codes whose
// message has such specifics. Unknown codes fall back to the backend text.
const TRANSLATED_CODES = [
  'MINI_BROWSER_PLAYWRIGHT_MISSING',
  'MINI_BROWSER_CHROMIUM_MISSING',
  'MINI_BROWSER_PROFILE_IN_USE',
  'MINI_BROWSER_LAUNCH_FAILED',
  'MINI_BROWSER_NOT_RUNNING',
  'MINI_BROWSER_NAVIGATION_FAILED',
  'MINI_BROWSER_BLOCKED_URL',
  'MINI_BROWSER_INVALID_INPUT',
  'MINI_BROWSER_PAGE_UNRESPONSIVE',
  'MINI_BROWSER_TAB_NOT_FOUND',
  'MINI_BROWSER_TIMEOUT',
  'MINI_BROWSER_VAULT_UNREADABLE',
  'MINI_BROWSER_VAULT_INVALID',
  'MINI_BROWSER_VAULT_IO',
  'MINI_BROWSER_INSTALL_FAILED',
  'MINI_BROWSER_INTERNAL',
] as const

type TranslatedCode = (typeof TRANSLATED_CODES)[number]

const CODES_WITH_DETAIL = new Set<string>([
  'MINI_BROWSER_LAUNCH_FAILED',
  'MINI_BROWSER_NAVIGATION_FAILED',
  'MINI_BROWSER_BLOCKED_URL',
  'MINI_BROWSER_INVALID_INPUT',
  'MINI_BROWSER_TIMEOUT',
  'MINI_BROWSER_VAULT_INVALID',
  'MINI_BROWSER_VAULT_IO',
  'MINI_BROWSER_INSTALL_FAILED',
  'MINI_BROWSER_INTERNAL',
])

const isTranslated = (code: string): code is TranslatedCode =>
  (TRANSLATED_CODES as readonly string[]).includes(code)

export interface ErrorText {
  title: string
  message: string
  /** Backend specifics worth showing under the message ('' when none). */
  detail: string
}

/** Turns a backend `{code, title, message}` into localized display text. */
export function useErrorText(): (error: MiniBrowserError) => ErrorText {
  const { t } = useTranslation(['minibrowser', 'common'])
  return useCallback((error: MiniBrowserError): ErrorText => {
    if (isTranslated(error.code)) {
      const detail = CODES_WITH_DETAIL.has(error.code) ? error.message.trim() : ''
      return {
        title: t(`minibrowser:errors.${error.code}.title`),
        message: t(`minibrowser:errors.${error.code}.message`),
        detail,
      }
    }
    return {
      title: error.title || t('common:status.somethingWentWrong'),
      message: error.message,
      detail: '',
    }
  }, [t])
}
