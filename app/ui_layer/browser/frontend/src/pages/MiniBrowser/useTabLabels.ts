import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import type { MiniBrowserTab } from '../../types'

/** Host of an http(s) URL, without "www."; '' for anything else. */
export function displayHost(url: string): string {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return ''
    return parsed.hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

export function isBlankUrl(url: string): boolean {
  return !url || url === 'about:blank'
}

export function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url)
}

/**
 * Localized labels for tabs: who owns a tab ("You", "Main chat", the chat's
 * title, "Sub-agent"…) and what to call it in the strip.
 */
export function useTabLabels() {
  const { t } = useTranslation(['minibrowser', 'common'])

  const ownerName = useCallback((tab: MiniBrowserTab): string => {
    switch (tab.ownerKind) {
      case 'user':
        return t('minibrowser:tabs.owner.you')
      case 'main':
        return t('minibrowser:tabs.owner.main')
      case 'mini_browser':
        return t('minibrowser:tabs.owner.miniBrowser')
      case 'subagent':
        return tab.ownerLabel || t('minibrowser:tabs.owner.subagent')
      case 'session':
      default:
        return tab.ownerLabel || t('minibrowser:tabs.owner.session')
    }
  }, [t])

  const tabTitle = useCallback((tab: MiniBrowserTab): string => {
    const title = tab.title.trim()
    if (title) return title
    if (isBlankUrl(tab.url)) return t('minibrowser:tabs.untitled')
    return displayHost(tab.url) || tab.url
  }, [t])

  return { ownerName, tabTitle }
}
