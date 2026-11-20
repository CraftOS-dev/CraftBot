/**
 * The armed reply: an agent message the user chose to answer (key `r` in
 * the transcript). Module-level, like the browser's per-session "Replying
 * to" bar, so it survives the screen root unmounting when the chat comes
 * back. The chat shows it above the composer, sends it with the next
 * message (replyContext.originalMessage, see chat/intents.sendChat) and
 * clears it.
 */
import type { ChatMessage } from '../../../browser/frontend/src/types'

export interface ReplyTarget {
  sessionId: string
  messageId: string
  /** Short label for the "Replying to" line: the first 50 characters, as in the browser. */
  displayName: string
  /** The quoted message, sent as replyContext.originalMessage. */
  originalContent: string
}

let target: ReplyTarget | null = null
const listeners = new Set<() => void>()

function changed(): void {
  for (const listener of [...listeners]) listener()
}

/** The armed reply; with a session id, only when it belongs to that session. */
export function getReplyTarget(sessionId?: string): ReplyTarget | null {
  if (!target) return null
  return sessionId === undefined || target.sessionId === sessionId ? target : null
}

export function setReplyTarget(next: ReplyTarget): void {
  target = next
  changed()
}

export function clearReplyTarget(): void {
  if (!target) return
  target = null
  changed()
}

/** Be told when the reply target changes (for useSyncExternalStore). Returns an unsubscribe. */
export function subscribeReplyTarget(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * The reply target for a message, or null when it cannot be replied to.
 * Same rule as the browser: agent messages only, and not ones presenting
 * options (those are answered by choosing).
 */
export function replyTargetFor(message: ChatMessage): ReplyTarget | null {
  if (message.style !== 'agent' || message.options?.length) return null
  const content = message.content ?? ''
  if (!content.trim()) return null
  return {
    sessionId: message.sessionId,
    messageId: message.messageId,
    displayName: content.length > 50 ? `${content.slice(0, 50)}...` : content,
    originalContent: content,
  }
}
