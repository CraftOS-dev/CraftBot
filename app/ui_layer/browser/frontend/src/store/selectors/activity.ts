import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'
import type { ActionItem } from '../../types'

const EMPTY_ACTIVITY: ActionItem[] = []

const createdAtOf = (item: ActionItem): number => item.createdAt ?? 0

const byCreatedAt = (a: ActionItem, b: ActionItem) => createdAtOf(a) - createdAtOf(b)

// Buckets are normally in createdAt order (see activitySlice), but addOrUpdate
// appends, so a bucket can be out of order; callers fall back to sorting it.
function isInCreatedAtOrder(bucket: ActionItem[]): boolean {
  for (let i = 1; i < bucket.length; i++) {
    if (createdAtOf(bucket[i - 1]) > createdAtOf(bucket[i])) return false
  }
  return true
}

// Activity (action + reasoning items) of one session in createdAt order.
export const selectSessionActivity = (state: RootState, sessionId: string): ActionItem[] =>
  state.activity.bySession[sessionId] ?? EMPTY_ACTIVITY

// All activity items across every session, in createdAt order. Only the
// mascot narration uses it: its state machine picks the earliest unnarrated
// action over the whole list. Everything else reads the bounded selectors
// below.
export const selectAllActivity = createSelector(
  (state: RootState) => state.activity.bySession,
  (bySession): ActionItem[] =>
    Object.values(bySession)
      .flat()
      .sort(byCreatedAt),
)

// The newest `limit` items across sessions, oldest first — the same result
// as selectAllActivity(state).slice(-limit) without sorting everything. Only
// each bucket's last `limit` items can make the cut (a whole bucket when it
// is out of order), and a stable sort of those in session order keeps ties
// exactly where the full sort put them.
export const selectRecentActivity = createSelector(
  [(state: RootState) => state.activity.bySession, (_state: RootState, limit: number) => limit],
  (bySession, limit): ActionItem[] => {
    if (limit <= 0) return EMPTY_ACTIVITY
    const candidates: ActionItem[] = []
    for (const bucket of Object.values(bySession)) {
      const tail = bucket.length > limit && isInCreatedAtOrder(bucket) ? bucket.slice(-limit) : bucket
      for (const item of tail) candidates.push(item)
    }
    return candidates.sort(byCreatedAt).slice(-limit)
  },
)

// Statuses whose item can still produce output.
const LIVE_STATUSES: ReadonlySet<string> = new Set(['running', 'waiting', 'paused', 'pending'])

// Cross-session summary for global status consumers (dashboard header,
// mascot): everything they read, from one linear pass with no global sort.
export interface ActivityOverview {
  /** Items still in progress (running/waiting/paused/pending), in createdAt
   *  order — the same relative order as in selectAllActivity. */
  live: ActionItem[]
  /** Newest createdAt or completedAt over all items (ms); -Infinity when empty. */
  latestAt: number
  /** Action items with status 'completed'. */
  completedActions: number
  /** Items of any type with status 'cancelled' or 'error'. */
  abortedItems: number
}

function sameOverview(a: ActivityOverview, b: ActivityOverview): boolean {
  if (
    a.latestAt !== b.latestAt ||
    a.completedActions !== b.completedActions ||
    a.abortedItems !== b.abortedItems ||
    a.live.length !== b.live.length
  ) {
    return false
  }
  return a.live.every((item, i) => item === b.live[i])
}

// Keeps the previous object while the summary is unchanged, so an update to a
// finished item (e.g. late output) doesn't re-render global consumers.
export const selectActivityOverview = createSelector(
  (state: RootState) => state.activity.bySession,
  (bySession): ActivityOverview => {
    const live: ActionItem[] = []
    let latestAt = -Infinity
    let completedActions = 0
    let abortedItems = 0
    for (const bucket of Object.values(bySession)) {
      for (const item of bucket) {
        latestAt = Math.max(latestAt, item.createdAt ?? 0, item.completedAt ?? 0)
        if (LIVE_STATUSES.has(item.status)) live.push(item)
        if (item.itemType === 'action' && item.status === 'completed') completedActions++
        if (item.status === 'cancelled' || item.status === 'error') abortedItems++
      }
    }
    live.sort(byCreatedAt)
    return { live, latestAt, completedActions, abortedItems }
  },
  { memoizeOptions: { resultEqualityCheck: sameOverview } },
)
