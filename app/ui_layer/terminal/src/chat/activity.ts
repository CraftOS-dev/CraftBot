/**
 * How one action reads in a row: a human name and a one-line preview of its
 * primary input. Ported from the browser's ActivityBlocks.tsx (that module
 * also holds React/CSS rendering, so it cannot be imported here); the shared
 * helpers come from the browser's own actionNames.ts and parse.ts.
 */
import type { ActionItem } from '../../../browser/frontend/src/types'
import { extractTodos, normalizeActionName } from '../../../browser/frontend/src/components/activity/actionNames'
import { parseDict, strField } from '../../../browser/frontend/src/components/activity/parse'
import { stripEmoji } from '../text/emoji'

const PREVIEW_KEYS: Record<string, string[]> = {
  web_search: ['query'],
  memory_search: ['query'],
  web_fetch: ['url'],
  http_request: ['url'],
  read_file: ['file_path'],
  write_file: ['file_path'],
  stream_edit: ['file_path'],
  read_pdf: ['file_path'],
  find_files: ['pattern'],
  grep_files: ['pattern'],
  list_folder: ['path'],
  convert_to_pdf: ['source_path', 'url', 'output_path'],
  convert_from_pdf: ['source_path', 'output_path'],
  convert_to_markdown: ['input_file'],
  run_shell: ['command'],
  run_python: ['code'],
  generate_image: ['prompt'],
  describe_image: ['image_path'],
  perform_ocr: ['image_path'],
  understand_video: ['video_path'],
  send_message_with_attachment: ['message'],
  mini_browser_navigate: ['url'],
  mini_browser_type: ['text'],
  mini_browser_press_key: ['keys'],
  mini_browser_select_option: ['value'],
  mini_browser_wait: ['text'],
  mini_browser_scroll: ['direction'],
  mini_browser_login: ['username'],
}

/** Chat-send actions never render as rows: the message itself is their visible form. */
export const CHAT_SEND_ACTIONS: ReadonlySet<string> = new Set(['send_message', 'send_message_with_attachment'])

export function isChatSend(item: ActionItem): boolean {
  return item.itemType === 'action' && CHAT_SEND_ACTIONS.has(normalizeActionName(item.name))
}

function firstLine(text: string): string {
  const line = stripEmoji(text).split('\n').find(l => l.trim())?.trim() ?? ''
  return line.length > 200 ? `${line.slice(0, 200)}...` : line
}

/** "run_shell" -> "Run shell". */
export function displayActionName(name: string): string {
  const words = normalizeActionName(name).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function actionPreview(item: ActionItem): string {
  if (item.status === 'error' && item.error) return firstLine(item.error)
  const inputObj = parseDict(item.input)
  const normalized = normalizeActionName(item.name)
  if (normalized === 'update_todos') {
    const todos = extractTodos(inputObj)
    if (!todos) return ''
    const done = todos.filter(t => t.status === 'completed').length
    return `${done}/${todos.length} done`
  }
  const keys = PREVIEW_KEYS[normalized]
  if (keys) {
    for (const key of keys) {
      const value = strField(inputObj, key)
      if (value?.trim()) return firstLine(value)
    }
  }
  if (inputObj) {
    for (const value of Object.values(inputObj)) {
      if (typeof value === 'string' && value.trim()) return firstLine(value)
    }
  }
  return item.input ? firstLine(item.input) : ''
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
