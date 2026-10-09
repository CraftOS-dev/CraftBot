import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../store/hooks'
import { selectMiniBrowserSessionId } from '../../store/selectors/miniBrowser'
import { selectSessions } from '../../store/selectors/sessions'
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

// The backend's English stand-in for a chat without a title. Shown as the
// localized "Chat" instead.
const BACKEND_UNTITLED_CHAT = 'Chat'
// Session ids the backend gives the main chat and sub-agents.
const MAIN_SESSION_ID = 'main'
const SUBAGENT_ID_PREFIX = 'sub_'

/**
 * Localized labels for tabs: who owns a tab ("You", "Main chat", the chat's
 * title, "Sub-agent (Main chat)"…) and what to call it in the strip. Owner
 * names are built here, from the owner's kind and the app's own session
 * titles; the backend's English labels are only a last resort for sessions
 * this window doesn't know.
 */
export function useTabLabels() {
  const { t } = useTranslation(['minibrowser', 'common'])
  const sessions = useAppSelector(selectSessions)
  const miniBrowserSessionId = useAppSelector(selectMiniBrowserSessionId)

  /** A chat session's name, by id. */
  const sessionName = useCallback((id: string | null, backendLabel = ''): string => {
    if (id === MAIN_SESSION_ID) return t('minibrowser:tabs.owner.main')
    if (id && id === miniBrowserSessionId) return t('minibrowser:tabs.owner.miniBrowser')
    if (id?.startsWith(SUBAGENT_ID_PREFIX)) return t('minibrowser:tabs.owner.subagent')
    const session = id ? sessions.find(s => s.id === id) : undefined
    if (session?.type === 'main') return t('minibrowser:tabs.owner.main')
    if (session?.type === 'mini_browser') return t('minibrowser:tabs.owner.miniBrowser')
    const title = session?.title.trim() || (backendLabel.trim() === BACKEND_UNTITLED_CHAT ? '' : backendLabel.trim())
    return title || t('minibrowser:tabs.owner.session')
  }, [miniBrowserSessionId, sessions, t])

  const ownerName = useCallback((tab: MiniBrowserTab): string => {
    switch (tab.ownerKind) {
      case 'user':
        return t('minibrowser:tabs.owner.you')
      case 'main':
        return t('minibrowser:tabs.owner.main')
      case 'mini_browser':
        return t('minibrowser:tabs.owner.miniBrowser')
      case 'subagent':
        return tab.parentOwner
          ? t('minibrowser:tabs.owner.subagentOf', { parent: sessionName(tab.parentOwner) })
          : t('minibrowser:tabs.owner.subagent')
      case 'session':
      default:
        return sessionName(tab.owner, tab.ownerLabel)
    }
  }, [sessionName, t])

  const tabTitle = useCallback((tab: MiniBrowserTab): string => {
    const title = tab.title.trim()
    if (title) return title
    if (isBlankUrl(tab.url)) return t('minibrowser:tabs.untitled')
    return displayHost(tab.url) || tab.url
  }, [t])

  return { ownerName, tabTitle }
}
