import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { SessionInfo } from '../../types'
import { frameworkKey } from '../../features/agentApps/frameworkIdentity'

export const selectSessions = (state: RootState): SessionInfo[] =>
  state.sessions.sessions

export const selectMainSession = createSelector(
  selectSessions,
  (sessions): SessionInfo | undefined => sessions.find(s => s.type === 'main'),
)

// Plain chats follow their latest activity, including after reconnecting.
// Older session records can fall back to their creation timestamp.
export const selectChatSessions = createSelector(
  selectSessions,
  (sessions): SessionInfo[] =>
    sessions
      .filter(s => s.type === 'chat')
      .slice()
      .sort((a, b) => {
        const aUpdated = a.lastActiveAt || a.createdAt
        const bUpdated = b.lastActiveAt || b.createdAt
        return aUpdated < bUpdated ? 1 : aUpdated > bUpdated ? -1 : 0
      }),
)

export const selectSessionById = (state: RootState, sessionId: string): SessionInfo | undefined =>
  state.sessions.sessions.find(s => s.id === sessionId)

export const selectPendingFrameworkApps = createSelector(selectSessions, sessions =>
  sessions.filter(session => session.type === 'agent_app' && session.agentAppFrameworkPending && !session.agentAppFrameworkKey),
)

export const selectFrameworkAppSessionIds = createSelector(selectSessions, sessions => {
  const result: Record<string, string> = {}
  for (const session of sessions) {
    if (session.type !== 'agent_app' || !session.agentAppFrameworkKey) continue
    try {
      const [, path, id] = JSON.parse(session.agentAppFrameworkKey)
      if (typeof path === 'string' && typeof id === 'string') result[frameworkKey(path, id)] = session.id
    } catch { /* A malformed saved identity cannot choose another session. */ }
  }
  return result
})
