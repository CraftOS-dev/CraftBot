/**
 * What the user can do to the conversation, as backend messages.
 *
 * Same wire payloads and optimistic updates as the browser's
 * WebSocketContext: an optimistic user bubble reconciled by clientId, the
 * session marked running at once, and a pinned question answered by a
 * normal message. A new chat is the lazy "new" session: the backend creates
 * it on the first message and announces it with session_created carrying
 * our clientId, and the chat switches to it.
 */
import { randomUUID } from 'node:crypto'
import { readFileSync, statSync } from 'node:fs'
import { basename, extname } from 'node:path'
import type { ChatMessage } from '../../../browser/frontend/src/types'
import { QUESTION_DISMISSED } from '../../../browser/frontend/src/types'
import {
  addOptimistic,
  historyRequested,
  markOptionSelected,
  transferSession,
} from '../../../browser/frontend/src/store/slices/messagesSlice'
import { setSessionRunState } from '../../../browser/frontend/src/store/slices/agentSlice'
import { transferDraft } from '../../../browser/frontend/src/store/slices/chatInputSlice'
import { selectPendingQuestions } from '../../../browser/frontend/src/store/selectors/messages'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import { getApiBaseUrl } from '../platform/connection'
import { send } from '../state/hooks'
import { store } from '../state/store'
import { setActiveSession } from '../state/tuiSlice'
import { adoptSession } from './transcriptWriter'

/** Draft sends waiting for their session_created. */
const pendingDraftClientIds = new Set<string>()

onInboundMessage(msg => {
  if (msg.type !== 'session_created') return
  const d = (msg.data ?? {}) as { session?: { id: string }; clientId?: string | null; startsRun?: boolean }
  if (!d.session || !d.clientId || !pendingDraftClientIds.has(d.clientId)) return
  pendingDraftClientIds.delete(d.clientId)
  store.dispatch(transferSession({ from: 'new', to: d.session.id }))
  store.dispatch(transferDraft({ from: 'new', to: d.session.id }))
  store.dispatch(setSessionRunState({ sessionId: 'new', state: 'idle' }))
  store.dispatch(setSessionRunState({ sessionId: d.session.id, state: d.startsRun === false ? 'idle' : 'running' }))
  if (store.getState().tui.activeSessionId === 'new') {
    adoptSession('new', d.session.id)
    store.dispatch(setActiveSession(d.session.id))
  }
})

export interface FileAttachment {
  name: string
  type: string
  size: number
  /** Absolute path on this machine. */
  path: string
}

/** Inline up to this size as base64; larger files are uploaded first. */
const INLINE_LIMIT = 50 * 1024 * 1024
export const MAX_ATTACHMENTS = 10
export const MAX_TOTAL_BYTES = 200 * 1024 * 1024

const MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.pdf': 'application/pdf',
  '.txt': 'text/plain',
  '.md': 'text/markdown',
  '.csv': 'text/csv',
  '.json': 'application/json',
  '.zip': 'application/zip',
}

export function describeFile(path: string): FileAttachment {
  const stat = statSync(path)
  if (!stat.isFile()) throw new Error(`${path} is not a file`)
  return { name: basename(path), size: stat.size, type: MIME[extname(path).toLowerCase()] ?? 'application/octet-stream', path }
}

async function uploadLarge(file: FileAttachment): Promise<string> {
  const form = new FormData()
  form.append('file', new Blob([readFileSync(file.path)], { type: file.type }), file.name)
  const resp = await fetch(`${getApiBaseUrl()}/api/chat-attachments/upload`, { method: 'POST', body: form })
  if (!resp.ok) throw new Error(`upload failed: ${resp.status}`)
  const body = (await resp.json()) as { serverPath?: string; path?: string }
  const serverPath = body.serverPath ?? body.path
  if (!serverPath) throw new Error('upload returned no path')
  return serverPath
}

async function encodeAttachments(files: FileAttachment[]): Promise<Record<string, unknown>[]> {
  const out: Record<string, unknown>[] = []
  for (const file of files) {
    if (file.size > INLINE_LIMIT) {
      out.push({ name: file.name, type: file.type, size: file.size, serverPath: await uploadLarge(file) })
    } else {
      out.push({ name: file.name, type: file.type, size: file.size, content: readFileSync(file.path).toString('base64') })
    }
  }
  return out
}

/** Send a chat message (or a slash command) into `sessionId`. */
export async function sendChat(
  content: string,
  sessionId: string,
  files: FileAttachment[] = [],
  replyTo?: string,
): Promise<void> {
  const clientId = randomUUID()
  if (sessionId === 'new') pendingDraftClientIds.add(clientId)

  if (content.trimStart().startsWith('/') && files.length === 0) {
    send('command', { command: content.trim(), sessionId, clientId })
    return
  }

  store.dispatch(setSessionRunState({ sessionId, state: 'running' }))
  const optimistic: ChatMessage = {
    sender: 'You',
    content,
    style: 'user',
    timestamp: Date.now() / 1000,
    messageId: `pending:${clientId}`,
    sessionId,
    clientId,
    pending: true,
  }
  store.dispatch(addOptimistic(optimistic))

  // A message answers the pinned question shown above the composer.
  const shown = selectPendingQuestions(store.getState(), sessionId)[0]
  if (shown) {
    store.dispatch(markOptionSelected({
      sessionId,
      messageId: shown.messageId,
      value: content.trim() || files.map(f => f.name).join(', '),
    }))
  }

  send('message', {
    content,
    sessionId,
    attachments: await encodeAttachments(files),
    replyContext: replyTo ? { originalMessage: replyTo } : null,
    clientId,
  })
}

export function stopSession(sessionId: string): void {
  store.dispatch(setSessionRunState({ sessionId, state: 'stopping' }))
  send('session_stop', { sessionId })
}

/** Answer a pinned agent question with an option value or free text. */
export function answerQuestion(question: ChatMessage, value: string): void {
  store.dispatch(markOptionSelected({ sessionId: question.sessionId, messageId: question.messageId, value }))
  store.dispatch(setSessionRunState({ sessionId: question.sessionId, state: 'running' }))
  send('question_response', { value, sessionId: question.sessionId, messageId: question.messageId, dismissed: false })
}

/** Dismiss a pinned question; this interrupts the task, as in the browser. */
export function dismissQuestion(question: ChatMessage): void {
  store.dispatch(markOptionSelected({ sessionId: question.sessionId, messageId: question.messageId, value: QUESTION_DISMISSED }))
  send('question_response', {
    value: QUESTION_DISMISSED,
    sessionId: question.sessionId,
    messageId: question.messageId,
    dismissed: true,
  })
}

/** Pick an option on a non-question choice message (e.g. Continue / Stop at a limit). */
export function clickOption(message: ChatMessage, value: string): void {
  store.dispatch(markOptionSelected({ sessionId: message.sessionId, messageId: message.messageId, value }))
  send('option_click', { value, sessionId: message.sessionId, messageId: message.messageId })
}

export function requestHistory(sessionId: string, beforeTimestamp?: number, limit = 50): void {
  if (beforeTimestamp === undefined) store.dispatch(historyRequested({ sessionId }))
  send('chat_history', { sessionId, limit, ...(beforeTimestamp !== undefined ? { beforeTimestamp } : {}) })
}

export function markSeen(sessionId: string, messageId: string): void {
  if (!messageId || messageId.startsWith('pending:')) return
  send('session_seen', { sessionId, messageId })
}
