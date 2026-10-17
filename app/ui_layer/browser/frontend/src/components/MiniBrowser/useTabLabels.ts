import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../store/hooks'
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
// The session id the backend gives the main chat.
const MAIN_SESSION_ID = 'main'

/**
 * Localized labels for the tabs of one session's browser: who uses a tab
 * ("You", "Agent" for the chat's own agent, "Sub-agent") and what to call it
 * in the strip. Owner names are built here, from the owner's kind and the
 * app's own session titles; the backend's English labels are only a last
 * resort for sessions this window doesn't know.
 */
export function useTabLabels(sessionId: string) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const sessions = useAppSelector(selectSessions)

  /** A chat session's name, by id. */
  const sessionName = useCallback((id: string | null, backendLabel = ''): string => {
    if (id === MAIN_SESSION_ID) return t('minibrowser:tabs.owner.main')
    const session = id ? sessions.find(s => s.id === id) : undefined
    if (session?.type === 'main') return t('minibrowser:tabs.owner.main')
    const title = session?.title.trim() || (backendLabel.trim() === BACKEND_UNTITLED_CHAT ? '' : backendLabel.trim())
    return title || t('minibrowser:tabs.owner.session')
  }, [sessions, t])

  const ownerName = useCallback((tab: MiniBrowserTab): string => {
    if (tab.ownerKind === 'user') return t('minibrowser:tabs.owner.you')
    if (tab.ownerKind === 'subagent') return t('minibrowser:tabs.owner.subagent')
    // This chat's own agent (the browser is the chat's).
    if (tab.owner === sessionId) return t('minibrowser:tabs.owner.agent')
    if (tab.ownerKind === 'main') return t('minibrowser:tabs.owner.main')
    return sessionName(tab.owner, tab.ownerLabel)
  }, [sessionId, sessionName, t])

  const tabTitle = useCallback((tab: MiniBrowserTab): string => {
    const title = tab.title.trim()
    if (title) return title
    if (isBlankUrl(tab.url)) return t('minibrowser:tabs.untitled')
    return displayHost(tab.url) || tab.url
  }, [t])

  return { ownerName, tabTitle }
}
