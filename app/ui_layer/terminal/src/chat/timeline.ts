/**
 * One session's conversation as display units, in order.
 *
 * Messages and activity merge into one timeline (the browser's own
 * mergeTimeline). Consecutive activity between two messages forms a chunk; a
 * chunk counts only when it holds at least one real action (reply-only runs
 * show nothing but the reply, as in the browser). A unit is final once
 * nothing about it can change: a message as soon as it arrives, a chunk once
 * a message follows it or the run went idle with nothing still running. Final
 * units go into the terminal's scrollback once; the live region shows the rest.
 */
import type { ActionItem, ChatMessage } from '../../../browser/frontend/src/types'
import { mergeTimeline } from '../../../browser/frontend/src/components/Chat/timeline'
import { isChatSend } from './activity'

export type Unit =
  | { kind: 'message'; key: string; ts: number; message: ChatMessage; open?: boolean }
  | {
      kind: 'chunk'
      key: string
      ts: number
      items: ActionItem[]
      actionCount: number
      failed: number
      final: boolean
    }

const LIVE: ReadonlySet<string> = new Set(['running', 'waiting', 'paused', 'pending'])

/** An agent question or blocking choice the user has not answered yet. */
export function isOpenChoice(message: ChatMessage): boolean {
  if (message.style === 'user' || !message.options?.length || message.optionSelected) return false
  return !!message.isQuestion || message.requiresChoice !== false
}

export function buildUnits(messages: ChatMessage[], activity: ActionItem[], busy: boolean): Unit[] {
  const units: Unit[] = []
  let chunk: ActionItem[] = []
  const flush = (closedByMessage: boolean) => {
    if (chunk.length === 0) return
    const items = chunk.filter(i => !isChatSend(i))
    chunk = []
    const actions = items.filter(i => i.itemType === 'action')
    if (actions.length === 0) return
    const final = closedByMessage || (!busy && !items.some(i => LIVE.has(i.status)))
    units.push({
      kind: 'chunk',
      key: `chunk:${items[0].id}`,
      ts: items[0].createdAt ?? 0,
      items,
      actionCount: actions.length,
      failed: actions.filter(a => a.status === 'error').length,
      final,
    })
  }
  for (const entry of mergeTimeline(messages, activity)) {
    if (entry.kind === 'message') {
      flush(true)
      // Optimistic bubbles wait for the server's echo before they count.
      if (entry.message.pending) continue
      // A question or choice still waiting on the user lives in the pinned
      // box; it joins the transcript, with its answer, once answered.
      if (isOpenChoice(entry.message)) {
        units.push({ kind: 'message', key: `msg:${entry.message.messageId}`, ts: entry.ts, message: entry.message, open: true })
        continue
      }
      units.push({ kind: 'message', key: `msg:${entry.message.messageId}`, ts: entry.ts, message: entry.message })
    } else {
      chunk.push(entry.item)
    }
  }
  flush(false)
  return units
}

/** The chunk still being built by a running turn, if any. */
export function liveChunk(units: Unit[]): Extract<Unit, { kind: 'chunk' }> | null {
  const last = units[units.length - 1]
  return last && last.kind === 'chunk' && !last.final ? last : null
}
