import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { ChatMessage } from '../../types'

const EMPTY_MESSAGES: ChatMessage[] = []

// Messages of one session in timestamp order (the slice keeps buckets sorted).
export const selectSessionMessages = (state: RootState, sessionId: string): ChatMessage[] =>
  state.messages.bySession[sessionId]?.items ?? EMPTY_MESSAGES

export const selectSessionHasMoreMessages = (state: RootState, sessionId: string): boolean =>
  state.messages.bySession[sessionId]?.hasMore ?? false

export const selectSessionLoadingOlderMessages = (state: RootState, sessionId: string): boolean =>
  state.messages.bySession[sessionId]?.loadingOlder ?? false

// State of the session's initial history load this connection
// ('unfetched' | 'loading' | 'fetched'). Drives the mount-time
// chat_history fetch.
export const selectSessionHistoryStatus = (state: RootState, sessionId: string) =>
  state.messages.bySession[sessionId]?.historyStatus ?? 'unfetched'

export const selectSessionOldestMessageTimestamp = (
  state: RootState,
  sessionId: string,
): number | undefined =>
  state.messages.bySession[sessionId]?.items[0]?.timestamp

// Unanswered agent questions of one session, oldest first — the pinned
// question queue. Derived entirely from the messages bucket: a question is
// pending until markOptionSelected records an answer (or dismissal), so it
// survives reloads via chat history with no extra state.
export const selectPendingQuestions = createSelector(
  [selectSessionMessages],
  (items): ChatMessage[] => items.filter(m => m.isQuestion && !m.optionSelected),
)

// The newest message across every session, for global consumers (mascot,
// dashboard status) that only look at the latest message. Buckets are kept in
// timestamp order, so each bucket's last item is its newest; `>=` lets a later
// session win ties, matching the last element of a stable sort of all messages.
export const selectLatestMessage = createSelector(
  (state: RootState) => state.messages.bySession,
  (bySession): ChatMessage | undefined => {
    let latest: ChatMessage | undefined
    for (const bucket of Object.values(bySession)) {
      const last = bucket.items[bucket.items.length - 1]
      if (last && (!latest || last.timestamp >= latest.timestamp)) latest = last
    }
    return latest
  },
)

// sessionId → messageId of the newest message. Drives the per-session
// unread dots in the sidebar and markSessionSeen.
export const selectLastMessageIdBySession = createSelector(
  (state: RootState) => state.messages.bySession,
  (bySession): Record<string, string | undefined> => {
    const result: Record<string, string | undefined> = {}
    for (const [sessionId, bucket] of Object.entries(bySession)) {
      result[sessionId] = bucket.items[bucket.items.length - 1]?.messageId
    }
    return result
  },
)
