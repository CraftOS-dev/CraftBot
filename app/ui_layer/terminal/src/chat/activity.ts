/**
 * How one action reads in a row: a human name and a one-line preview of the
 * input it acts on. Ported from the browser's ActivityBlocks.tsx (that module
 * also holds React/CSS rendering, so it cannot be imported here); the shared
 * helpers come from the browser's own actionNames.ts and parse.ts.
 */
import type { ActionItem } from '../../../browser/frontend/src/types'
import { extractTodos, normalizeActionName } from '../../../browser/frontend/src/components/activity/actionNames'
import { parseDict } from '../../../browser/frontend/src/components/activity/parse'
import { stripEmoji } from '../text/emoji'

/** Chat-send actions never render as rows: the message itself is their visible form. */
export const CHAT_SEND_ACTIONS: ReadonlySet<string> = new Set(['send_message', 'send_message_with_attachment'])

export function isChatSend(item: ActionItem): boolean {
  return item.itemType === 'action' && CHAT_SEND_ACTIONS.has(normalizeActionName(item.name))
}

function firstLine(text: string): string {
  const line = stripEmoji(text).split('\n').find(l => l.trim())?.trim() ?? ''
  return line.length > 200 ? `${line.slice(0, 200)}…` : line
}

/** "run_shell" -> "Run shell". */
export function displayActionName(name: string): string {
  const words = normalizeActionName(name).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// One input value as one short line: text as its first line, lists as
// their items, objects as their fields (the browser's formatValue).
function formatValue(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return firstLine(value)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  const part = (v: unknown) => (v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v))
  if (Array.isArray(value)) return firstLine(value.map(part).join(', '))
  if (typeof value === 'object') {
    return firstLine(Object.entries(value).map(([k, v]) => `${k}: ${part(v)}`).join(', '))
  }
  return ''
}

/**
 * The row's one-line preview, as the browser shows it: the value of the
 * input the action declares for display (its display param), a to-do
 * summary for update_todos, or for an action the backend did not describe
 * its first text input. A failed action shows its error instead.
 */
export function actionPreview(item: ActionItem): string {
  if (item.status === 'error' && item.error) return firstLine(item.error)
  const inputObj = parseDict(item.input)
  if (normalizeActionName(item.name) === 'update_todos') {
    const todos = extractTodos(inputObj)
    if (!todos) return ''
    const done = todos.filter(t => t.status === 'completed').length
    return `${done}/${todos.length} done`
  }
  if (item.displayParam !== undefined) {
    return item.displayParam && inputObj ? formatValue(inputObj[item.displayParam]) : ''
  }
  if (inputObj) {
    for (const [key, value] of Object.entries(inputObj)) {
      if (!key.startsWith('_') && typeof value === 'string' && value.trim()) return firstLine(value)
    }
  }
  return ''
}

export interface TodoRow {
  content: string
  status: string
}

/** The session's latest to-do list, read from its newest update_todos action. */
export function latestTodos(activity: ActionItem[]): TodoRow[] | null {
  for (let i = activity.length - 1; i >= 0; i--) {
    const item = activity[i]
    if (item.itemType !== 'action' || normalizeActionName(item.name) !== 'update_todos') continue
    const todos = extractTodos(parseDict(item.input))
    if (todos) return todos.map(t => ({ content: String(t.content ?? ''), status: String(t.status ?? '') }))
  }
  return null
}

export function formatDuration(ms: number | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  return `${minutes}m ${seconds}s`
}
