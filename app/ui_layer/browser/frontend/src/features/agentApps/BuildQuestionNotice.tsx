import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { createSelector } from '@reduxjs/toolkit'
import { useToast } from '../../contexts/ToastContext'
import { useAppSelector } from '../../store/hooks'
import type { RootState } from '../../store'
import { frameworkAppKey } from '../../store/slices/agentAppSlice'
import { frameworkSessionIdentity } from './frameworkIdentity'

interface WaitingBuild { sessionId: string; messageId: string; name: string }

/** Builds stopped on a question in their chat: the oldest unanswered one of each. */
const selectWaitingBuilds = createSelector(
  [(state: RootState) => state.sessions.sessions, (state: RootState) => state.messages.bySession],
  (sessions, bySession): WaitingBuild[] => sessions.flatMap(session => {
    if (session.type !== 'agent_app' || !(session.agentAppFrameworkPending || session.agentAppBuild?.building)) return []
    const question = bySession[session.id]?.items.find(m => m.isQuestion && !m.optionSelected)
    return question ? [{ sessionId: session.id, messageId: question.messageId, name: session.title }] : []
  }),
)

/** The conversation on screen: a chat, or a registered app's view and its side chat. */
function viewedSession(state: RootState, pathname: string, search: string): string | undefined {
  const chat = /^\/session\/([^/]+)\/?$/.exec(pathname)
  if (chat) return decodeURIComponent(chat[1])
  if (pathname !== '/framework-app') return undefined
  const params = new URLSearchParams(search)
  const path = params.get('path'), appId = params.get('id')
  if (!path || !appId) return undefined
  return state.agentApp.frameworkSessions[frameworkAppKey(path, appId)]
    ?? state.sessions.sessions.find(session => {
      const identity = frameworkSessionIdentity(session.agentAppFrameworkKey)
      return identity?.path === path && identity.appId === appId
    })?.id
}

/**
 * A build waiting on the person where they are not looking: one started from
 * another chat, or left running while they moved on. Its own view opens its
 * chat on the question; anywhere else this notice says so and opens it.
 * Each question is announced once, and its notice goes when it is answered
 * or its build is opened. Mounted once at the root; renders nothing.
 */
export function BuildQuestionNotice() {
  const { t } = useTranslation(['agentapp', 'common'])
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const { showToast, dismissToastKey } = useToast()
  const waiting = useAppSelector(selectWaitingBuilds)
  const viewing = useAppSelector(state => viewedSession(state, pathname, search))
  const announced = useRef(new Set<string>())
  // Notice key -> the question it announces.
  const showing = useRef(new Map<string, string>())

  useEffect(() => {
    const due = new Map(waiting.filter(build => build.sessionId !== viewing)
      .map(build => [`build-question:${build.sessionId}`, build]))
    for (const [key, messageId] of showing.current) {
      if (due.get(key)?.messageId === messageId) continue
      dismissToastKey(key)
      showing.current.delete(key)
    }
    for (const [key, build] of due) {
      if (announced.current.has(build.messageId)) continue
      announced.current.add(build.messageId)
      showing.current.set(key, build.messageId)
      showToast('info', build.name, undefined, {
        key,
        sticky: true,
        detail: t('agentapp:construction.stage.questions'),
        actions: [{ label: t('common:actions.open'), onClick: () => navigate(`/session/${build.sessionId}`) }],
      })
    }
  }, [waiting, viewing, showToast, dismissToastKey, navigate, t])

  return null
}
