import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { ActionItem } from '../../types'

const EMPTY_ACTIVITY: ActionItem[] = []

// Activity (action + reasoning items) of one session in createdAt order.
export const selectSessionActivity = (state: RootState, sessionId: string): ActionItem[] =>
  state.activity.bySession[sessionId] ?? EMPTY_ACTIVITY

// All activity items across every session, in createdAt order. Used by
// global consumers (mascot narration, dashboard status).
export const selectAllActivity = createSelector(
  (state: RootState) => state.activity.bySession,
  (bySession): ActionItem[] =>
    Object.values(bySession)
      .flat()
      .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0)),
)
