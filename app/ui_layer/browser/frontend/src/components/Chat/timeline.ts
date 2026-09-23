import type { ActionItem, ChatMessage } from '../../types'

// One row of the linear session timeline: a chat message or an inline
// activity item (action / reasoning block), merged by timestamp.
export type TimelineEntry =
  | { kind: 'message'; ts: number; message: ChatMessage }
  | { kind: 'activity'; ts: number; item: ActionItem }

const messageTs = (message: ChatMessage) => message.timestamp * 1000
const activityTs = (item: ActionItem) => item.createdAt ?? 0

function isOrdered<T>(list: T[], ts: (entry: T) => number): boolean {
  for (let i = 1; i < list.length; i++) {
    if (ts(list[i - 1]) > ts(list[i])) return false
  }
  return true
}

/**
 * One session's messages and activity as a single timeline in timestamp order.
 * Message timestamps are epoch seconds; activity createdAt is epoch ms —
 * normalized to ms.
 *
 * Both buckets are normally already ordered by their slices, so this is a
 * linear merge instead of a sort. On equal timestamps the message goes first,
 * as the stable sort of [...messages, ...activity] did; an out-of-order bucket
 * falls back to exactly that sort.
 */
export function mergeTimeline(messages: ChatMessage[], activity: ActionItem[]): TimelineEntry[] {
  const entries: TimelineEntry[] = []
  if (!isOrdered(messages, messageTs) || !isOrdered(activity, activityTs)) {
    for (const message of messages) {
      entries.push({ kind: 'message', ts: messageTs(message), message })
    }
    for (const item of activity) {
      entries.push({ kind: 'activity', ts: activityTs(item), item })
    }
    return entries.sort((a, b) => a.ts - b.ts)
  }

  let m = 0
  let a = 0
  while (m < messages.length && a < activity.length) {
    const ts = messageTs(messages[m])
    if (ts <= activityTs(activity[a])) {
      entries.push({ kind: 'message', ts, message: messages[m++] })
    } else {
      const item = activity[a++]
      entries.push({ kind: 'activity', ts: activityTs(item), item })
    }
  }
  for (; m < messages.length; m++) {
    entries.push({ kind: 'message', ts: messageTs(messages[m]), message: messages[m] })
  }
  for (; a < activity.length; a++) {
    entries.push({ kind: 'activity', ts: activityTs(activity[a]), item: activity[a] })
  }
  return entries
}
