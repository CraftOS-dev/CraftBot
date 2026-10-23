import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { SessionInfo } from '../../types'

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
