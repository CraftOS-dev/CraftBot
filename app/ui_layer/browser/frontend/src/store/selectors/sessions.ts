import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { SessionInfo } from '../../types'

export const selectSessions = (state: RootState): SessionInfo[] =>
  state.sessions.sessions

export const selectMainSession = createSelector(
  selectSessions,
  (sessions): SessionInfo | undefined => sessions.find(s => s.type === 'main'),
)

// Plain chat sessions, newest first (createdAt is an ISO string, so a
// lexicographic descending sort is chronological).
export const selectChatSessions = createSelector(
  selectSessions,
  (sessions): SessionInfo[] =>
    sessions
      .filter(s => s.type === 'chat')
      .slice()
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0)),
)

export const selectSessionById = (state: RootState, sessionId: string): SessionInfo | undefined =>
  state.sessions.sessions.find(s => s.id === sessionId)
