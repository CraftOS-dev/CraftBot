// One-line speech-bubble formatters for the mascot's action display.
// Each formatter produces a small POJO (label + body + status).
//
// SupportedActionName (from actionNames.ts) is the shared contract: if
// you add a new action name to SUPPORTED_ACTION_NAMES, TypeScript will
// force you to add the matching formatter to FORMATTER_REGISTRY here.

import { basename, strField, arrField, dictField } from './parse'
import { extractTodos, isSupportedActionName, normalizeActionName, type SupportedActionName } from './actionNames'
import i18n from '../../i18n/config'
import { formatNumber } from '../../i18n/format'

// Non-React module: pull the translated, count-aware label for one of the
// shared "N thing(s)" bodies. `count` drives i18next plural selection; the
// separately-formatted `formatted` string carries the locale-formatted
// number that the message actually renders (via {{formatted}}).
// The plural label key is chosen at runtime from the action type, so it can't
// be a compile-time literal; validation is by catalog presence, not tsc.
const translate = i18n.t as unknown as (key: string, opts?: Record<string, unknown>) => string

function tCount(key: string, n: number): string {
  return translate(key, { count: n, formatted: formatNumber(n) })
}

// ─────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────

export type MascotActionStatus = 'running' | 'completed' | 'error' | 'cancelled'

/** Project the broader runtime ActionStatus union ('running' | 'pending'
 *  | 'completed' | 'error' | 'cancelled' | 'waiting' | 'paused') down
 *  to the three-value result domain the mascot formatters understand.
 *  Anything that isn't explicitly an error or cancel is treated as a
 *  successful completion. */
export function toMascotResultStatus(status: string): 'completed' | 'error' | 'cancelled' {
  if (status === 'error') return 'error'
  if (status === 'cancelled') return 'cancelled'
  return 'completed'
}

/** Output of a formatter: what the speech bubble actually renders.
 *  - `status` drives the icon (spinner / check / X / ban).
 *  - `label` is the primary line — sans-serif, slightly heavier.
 *  - `body` is the optional secondary line — sans by default.
 *  - `bodyMono: true` switches the body to a monospace font; use for
 *    paths, commands, regex patterns, and other code-like content. */
export interface MascotActionFormat {
  status: MascotActionStatus
  label: string
  body?: string
  bodyMono?: boolean
}

/** Each supported action provides two formatter functions — one for the
 *  "running" phase, one for the "result" phase. Splitting them (instead
 *  of one function dispatched on status) lets each phase pull only the
 *  fields it actually needs and keeps the conditional logic minimal. */
export interface MascotActionFormatter {
  running: (input: Record<string, unknown> | null) => MascotActionFormat
  result: (
    input: Record<string, unknown> | null,
    output: Record<string, unknown> | null,
    status: 'completed' | 'error' | 'cancelled',
  ) => MascotActionFormat
}

// ─────────────────────────────────────────────────────────────────────
// String helpers
// ─────────────────────────────────────────────────────────────────────
// `basename` is imported from parse.ts — same util the timeline rows use.

/** Truncate `s` to `max` characters, appending an ellipsis on overflow. */
function trim(s: string, max: number): string {
  return s.length > max ? s.slice(0, Math.max(0, max - 1)).trimEnd() + '…' : s
}

/** Line count for a possibly-empty multi-line string (ignores trailing newline). */
function lineCount(s: string): number {
  if (!s) return 0
  return s.replace(/\n$/, '').split('\n').length
}

/** Hostname-only view of a URL — strips protocol + path + query, so it
 *  fits in a one-line bubble body. Falls back to the input on parse error. */
function hostname(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

/** Wrap a string in curly quotes — for displaying user-facing queries
 *  (search query, prompt, etc.) as conversational text. */
function quote(s: string): string {
  return `“${s}”`
}

/** Snippet of the first N non-empty characters from a free-form text
 *  output, joined onto one line. Used for "first words of summary"
 *  bodies (image description, video summary, etc.). */
function firstSnippet(text: string, max = 60): string {
  const compact = text.trim().replace(/\s+/g, ' ')
  return trim(compact, max)
}

// ─────────────────────────────────────────────────────────────────────
// Per-action formatters
// ─────────────────────────────────────────────────────────────────────
//
// Each formatter pulls the same input/output fields the renderer uses
// (see actionNames.ts), so the source-of-truth for "which fields matter"
// stays in one place per action.

// FILE OPS ───────────────────────────────────────────────────────────

const stream_edit: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'file_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.streamEdit.editing'), body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, _o, s) => {
    const fp = strField(i, 'file_path') ?? ''
    const verb = s === 'completed' ? i18n.t('activity:action.streamEdit.edited') : s === 'error' ? i18n.t('activity:action.streamEdit.failed') : i18n.t('activity:action.streamEdit.cancelled')
    return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
}

const read_file: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'file_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.readFile.reading'), body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, o, s) => {
    const fp = strField(i, 'file_path') ?? ''
    const lines = lineCount(strField(o, 'content') ?? '')
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.readFile.failed') : i18n.t('activity:action.readFile.cancelled')
      return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
    }
    return { status: s, label: i18n.t('activity:action.readFile.read'), body: lines > 0 ? tCount('activity:count.lines', lines) : (fp ? basename(fp) : undefined), bodyMono: lines === 0 && !!fp }
  },
}

const find_files: MascotActionFormatter = {
  running: (i) => {
    const pattern = strField(i, 'pattern') ?? ''
    return { status: 'running', label: i18n.t('activity:action.findFiles.finding'), body: pattern || undefined, bodyMono: true }
  },
  result: (i, o, s) => {
    const pattern = strField(i, 'pattern') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.findFiles.failed') : i18n.t('activity:action.findFiles.cancelled')
      return { status: s, label: verb, body: pattern || undefined, bodyMono: true }
    }
    const count = (arrField(o, 'matches') ?? []).length
    return { status: s, label: tCount('activity:action.findFiles.found', count), body: pattern || undefined, bodyMono: true }
  },
}

const list_folder: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.listFolder.listing'), body: path ? basename(path) || '/' : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'path') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.listFolder.failed') : i18n.t('activity:action.listFolder.cancelled')
      return { status: s, label: verb, body: path ? basename(path) || '/' : undefined, bodyMono: !!path }
    }
    const count = (arrField(o, 'contents') ?? []).length
    return { status: s, label: i18n.t('activity:action.listFolder.listed'), body: tCount('activity:count.items', count) }
  },
}

// Formatter for convert_to_pdf — covers all source formats via one schema.
const convertToPdf: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'output_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.convertToPdf.creating'), body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, o, s) => {
    const fp = strField(o, 'path') ?? strField(i, 'output_path') ?? ''
    const verb = s === 'completed' ? i18n.t('activity:action.convertToPdf.created') : s === 'error' ? i18n.t('activity:action.convertToPdf.failed') : i18n.t('activity:action.convertToPdf.cancelled')
    return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
}

const read_pdf: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'file_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.readPdf.reading'), body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, o, s) => {
    const fp = strField(i, 'file_path') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.readPdf.failed') : i18n.t('activity:action.readPdf.cancelled')
      return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
    }
    const contentObj = dictField(o, 'content')
    const elements = arrField(contentObj, 'elements') ?? []
    return { status: s, label: i18n.t('activity:action.readPdf.read'), body: elements.length > 0 ? tCount('activity:count.elements', elements.length) : (fp ? basename(fp) : undefined), bodyMono: elements.length === 0 && !!fp }
  },
}

const convert_to_markdown: MascotActionFormatter = {
  running: (i) => {
    const src = strField(i, 'input_file') ?? ''
    return { status: 'running', label: i18n.t('activity:action.convertToMarkdown.converting'), body: src ? basename(src) : undefined, bodyMono: !!src }
  },
  result: (i, o, s) => {
    const out = strField(o, 'md_file') ?? strField(i, 'output_md') ?? ''
    const verb = s === 'completed' ? i18n.t('activity:action.convertToMarkdown.converted') : s === 'error' ? i18n.t('activity:action.convertToMarkdown.failed') : i18n.t('activity:action.convertToMarkdown.cancelled')
    return { status: s, label: verb, body: out ? basename(out) : undefined, bodyMono: !!out }
  },
}

// CODE EXECUTION ─────────────────────────────────────────────────────

const run_python: MascotActionFormatter = {
  running: (i) => {
    const lines = lineCount(strField(i, 'code') ?? '')
    return { status: 'running', label: i18n.t('activity:action.runPython.running'), body: lines > 0 ? tCount('activity:count.lines', lines) : undefined }
  },
  result: (_i, o, s) => {
    const stderr = strField(o, 'stderr') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.runPython.failed') : i18n.t('activity:action.runPython.cancelled')
      return { status: s, label: verb, body: stderr ? firstSnippet(stderr, 60) : undefined }
    }
    // Successful completion that wrote to stderr usually still indicates
    // a problem worth surfacing (e.g., warnings). Show the first stderr
    // line; otherwise just say it ran.
    if (stderr) return { status: s, label: i18n.t('activity:action.runPython.ran'), body: firstSnippet(stderr, 60) }
    const stdout = strField(o, 'stdout') ?? ''
    return { status: s, label: i18n.t('activity:action.runPython.ran'), body: stdout ? tCount('activity:count.linesOutput', lineCount(stdout)) : undefined }
  },
}

const run_shell: MascotActionFormatter = {
  running: (i) => {
    const cmd = strField(i, 'command') ?? ''
    return { status: 'running', label: i18n.t('activity:action.runShell.running'), body: cmd ? `$ ${cmd}` : undefined, bodyMono: true }
  },
  result: (i, _o, s) => {
    const cmd = strField(i, 'command') ?? ''
    const verb = s === 'completed' ? i18n.t('activity:action.runShell.ran') : s === 'error' ? i18n.t('activity:action.runShell.failed') : i18n.t('activity:action.runShell.cancelled')
    return { status: s, label: verb, body: cmd ? `$ ${cmd}` : undefined, bodyMono: true }
  },
}

// WEB ────────────────────────────────────────────────────────────────

const web_search: MascotActionFormatter = {
  running: (i) => {
    const q = strField(i, 'query') ?? ''
    return { status: 'running', label: i18n.t('activity:action.webSearch.searching'), body: q ? quote(q) : undefined }
  },
  result: (i, o, s) => {
    const q = strField(i, 'query') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.webSearch.failed') : i18n.t('activity:action.webSearch.cancelled')
      return { status: s, label: verb, body: q ? quote(q) : undefined }
    }
    const count = (arrField(o, 'results') ?? []).length
    return { status: s, label: tCount('activity:action.webSearch.found', count), body: q ? quote(q) : undefined }
  },
}

const web_fetch: MascotActionFormatter = {
  running: (i) => {
    const url = strField(i, 'url') ?? ''
    return { status: 'running', label: i18n.t('activity:action.webFetch.fetching'), body: url ? hostname(url) : undefined }
  },
  result: (i, o, s) => {
    const url = strField(i, 'url') ?? ''
    const title = strField(o, 'title')
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.webFetch.failed') : i18n.t('activity:action.webFetch.cancelled')
      return { status: s, label: verb, body: url ? hostname(url) : undefined }
    }
    return { status: s, label: title ? i18n.t('activity:action.webFetch.fetchedTitle', { title: trim(title, 40) }) : i18n.t('activity:action.webFetch.fetchedPage'), body: url ? hostname(url) : undefined }
  },
}

const http_request: MascotActionFormatter = {
  running: (i) => {
    const method = (strField(i, 'method') ?? 'GET').toUpperCase()
    const url = strField(i, 'url') ?? ''
    return { status: 'running', label: i18n.t('activity:action.httpRequest.request', { method }), body: url ? hostname(url) : undefined }
  },
  result: (i, o, s) => {
    const method = (strField(i, 'method') ?? 'GET').toUpperCase()
    const url = strField(i, 'url') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.httpRequest.failed', { method }) : i18n.t('activity:action.httpRequest.cancelled', { method })
      return { status: s, label: verb, body: url ? hostname(url) : undefined }
    }
    const body = strField(o, 'body') ?? ''
    return { status: s, label: i18n.t('activity:action.httpRequest.response', { method }), body: body ? tCount('activity:count.chars', body.length) : (url ? hostname(url) : undefined) }
  },
}

// MEDIA ──────────────────────────────────────────────────────────────

const generate_image: MascotActionFormatter = {
  running: (i) => {
    const p = strField(i, 'prompt') ?? ''
    return { status: 'running', label: i18n.t('activity:action.generateImage.generating'), body: p ? quote(trim(p, 60)) : undefined }
  },
  result: (i, o, s) => {
    const p = strField(i, 'prompt') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.generateImage.failed') : i18n.t('activity:action.generateImage.cancelled')
      return { status: s, label: verb, body: p ? quote(trim(p, 60)) : undefined }
    }
    const count = (arrField(o, 'image_paths') ?? []).length
    return { status: s, label: tCount('activity:action.generateImage.generated', count), body: p ? quote(trim(p, 60)) : undefined }
  },
}

const describe_image: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'image_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.describeImage.describing'), body: path ? basename(path) : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'image_path') ?? ''
    const desc = strField(o, 'description') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.describeImage.failed') : i18n.t('activity:action.describeImage.cancelled')
      return { status: s, label: verb, body: path ? basename(path) : undefined, bodyMono: !!path }
    }
    return { status: s, label: i18n.t('activity:action.describeImage.described'), body: desc ? firstSnippet(desc, 60) : (path ? basename(path) : undefined), bodyMono: !desc && !!path }
  },
}

const perform_ocr: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'image_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.performOcr.reading'), body: path ? basename(path) : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'image_path') ?? ''
    const summary = strField(o, 'summary') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.performOcr.failed') : i18n.t('activity:action.performOcr.cancelled')
      return { status: s, label: verb, body: path ? basename(path) : undefined, bodyMono: !!path }
    }
    return { status: s, label: i18n.t('activity:action.performOcr.extracted'), body: summary ? tCount('activity:count.characters', summary.length) : (path ? basename(path) : undefined), bodyMono: !summary && !!path }
  },
}

const understand_video: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'video_path') ?? ''
    return { status: 'running', label: i18n.t('activity:action.understandVideo.analyzing'), body: path ? basename(path) : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'video_path') ?? ''
    const summary = strField(o, 'summary') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.understandVideo.failed') : i18n.t('activity:action.understandVideo.cancelled')
      return { status: s, label: verb, body: path ? basename(path) : undefined, bodyMono: !!path }
    }
    return { status: s, label: i18n.t('activity:action.understandVideo.analyzed'), body: summary ? firstSnippet(summary, 60) : (path ? basename(path) : undefined), bodyMono: !summary && !!path }
  },
}

// SEARCH ─────────────────────────────────────────────────────────────

const grep_files: MascotActionFormatter = {
  running: (i) => {
    const p = strField(i, 'pattern') ?? ''
    return { status: 'running', label: i18n.t('activity:action.grepFiles.grepping'), body: p || undefined, bodyMono: true }
  },
  result: (i, o, s) => {
    const p = strField(i, 'pattern') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.grepFiles.failed') : i18n.t('activity:action.grepFiles.cancelled')
      return { status: s, label: verb, body: p || undefined, bodyMono: true }
    }
    const count = (arrField(o, 'filenames') ?? []).length
    return { status: s, label: tCount('activity:action.grepFiles.foundIn', count), body: p || undefined, bodyMono: true }
  },
}

const memory_search: MascotActionFormatter = {
  running: (i) => {
    const q = strField(i, 'query') ?? ''
    return { status: 'running', label: i18n.t('activity:action.memorySearch.searching'), body: q ? quote(q) : undefined }
  },
  result: (i, o, s) => {
    const q = strField(i, 'query') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? i18n.t('activity:action.memorySearch.failed') : i18n.t('activity:action.memorySearch.cancelled')
      return { status: s, label: verb, body: q ? quote(q) : undefined }
    }
    const count = (arrField(o, 'results') ?? []).length
    return { status: s, label: tCount('activity:action.memorySearch.found', count), body: q ? quote(q) : undefined }
  },
}

// MESSAGING + TASK CONTROL ───────────────────────────────────────────
//
// send_message and send_message_with_attachment normally bypass these
// formatters — the narration FSM routes them through the 'message'
// phase that displays the user-facing message text directly. These
// fallback formatters exist for type-completeness (Record exhaustive
// over SupportedActionName) and as a sensible last-resort display if
// the message-phase routing is ever bypassed.

const send_message: MascotActionFormatter = {
  running: (i) => {
    const msg = strField(i, 'message') ?? ''
    return { status: 'running', label: i18n.t('activity:action.sendMessage.sending'), body: msg ? firstSnippet(msg, 60) : undefined }
  },
  result: (_i, _o, s) => {
    const verb = s === 'completed' ? i18n.t('activity:action.sendMessage.sent') : s === 'error' ? i18n.t('activity:action.sendMessage.failed') : i18n.t('activity:action.sendMessage.cancelled')
    return { status: s, label: verb }
  },
}

const send_message_with_attachment: MascotActionFormatter = {
  running: (i) => {
    const count = (arrField(i, 'file_paths') ?? []).length
    return { status: 'running', label: i18n.t('activity:action.sendMessage.sending'), body: count > 0 ? tCount('activity:count.attachmentsPlus', count) : undefined }
  },
  result: (i, _o, s) => {
    const count = (arrField(i, 'file_paths') ?? []).length
    const verb = s === 'completed' ? i18n.t('activity:action.sendMessage.sent') : s === 'error' ? i18n.t('activity:action.sendMessage.failed') : i18n.t('activity:action.sendMessage.cancelled')
    return { status: s, label: verb, body: count > 0 ? tCount('activity:count.attachmentsPlus', count) : undefined }
  },
}

// TODOS ──────────────────────────────────────────────────────────────

const update_todos: MascotActionFormatter = {
  running: (i) => {
    const todos = extractTodos(i)
    if (!todos || todos.length === 0) {
      return { status: 'running', label: i18n.t('activity:action.updateTodos.updating') }
    }
    const done = todos.filter(t => t.status === 'completed').length
    const inProgress = todos.find(t => t.status === 'in_progress')
    const progress = i18n.t('activity:action.updateTodos.progress', { done: formatNumber(done), total: formatNumber(todos.length) })
    const body = inProgress ? i18n.t('activity:action.updateTodos.progressWithTask', { progress, task: trim(inProgress.content, 40) }) : progress
    return { status: 'running', label: i18n.t('activity:action.updateTodos.updating'), body }
  },
  result: (i, _o, s) => {
    const todos = extractTodos(i)
    const verb = s === 'completed' ? i18n.t('activity:action.updateTodos.updated') : s === 'error' ? i18n.t('activity:action.updateTodos.failed') : i18n.t('activity:action.updateTodos.cancelled')
    if (!todos || todos.length === 0) {
      return { status: s, label: verb }
    }
    const done = todos.filter(t => t.status === 'completed').length
    return { status: s, label: verb, body: i18n.t('activity:action.updateTodos.progress', { done: formatNumber(done), total: formatNumber(todos.length) }) }
  },
}

// ─────────────────────────────────────────────────────────────────────
// Registry + lookup
// ─────────────────────────────────────────────────────────────────────

/** Exhaustive map from every SupportedActionName to its formatter.
 *  Typed as Record<SupportedActionName, …> so any new entry in
 *  SUPPORTED_ACTION_NAMES (in actionNames.ts) becomes a compile error
 *  here until you add the matching formatter. */
const FORMATTER_REGISTRY: Record<SupportedActionName, MascotActionFormatter> = {
  // file ops
  stream_edit,
  read_file,
  find_files,
  list_folder,
  convert_to_pdf: convertToPdf,
  convert_from_pdf: convertToPdf,
  read_pdf,
  convert_to_markdown,
  // code execution
  run_python,
  run_shell,
  // web
  web_search,
  web_fetch,
  http_request,
  // media
  generate_image,
  describe_image,
  perform_ocr,
  understand_video,
  // search
  grep_files,
  memory_search,
  // messaging
  send_message,
  send_message_with_attachment,
  // todos
  update_todos,
}

/** Turn an action name (typically snake_case from the agent's tool
 *  metadata) into a human-readable phrase: underscores/dashes → spaces,
 *  collapsed whitespace, first letter capitalized.
 *    "update_todos" → "Update todos"
 *    "list-folder"       → "List folder" */
function humanizeActionName(name: string): string {
  const spaced = name.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
  if (!spaced) return i18n.t('activity:generic.actionNoun')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Build a generic formatter for an action name that isn't in
 *  FORMATTER_REGISTRY. The action name is interpolated into the
 *  label so the user still sees WHICH action is running/finished —
 *  the only thing we can't do for unknown actions is read meaningful
 *  fields out of their input/output payloads. */
function makeGenericFormatter(name: string): MascotActionFormatter {
  const humanized = humanizeActionName(name)
  return {
    running: () => ({ status: 'running', label: i18n.t('activity:generic.running', { name: humanized }) }),
    result: (_i, _o, s) => ({
      status: s,
      label: s === 'completed' ? i18n.t('activity:generic.completed', { name: humanized })
        : s === 'error' ? i18n.t('activity:generic.failed', { name: humanized })
          : i18n.t('activity:generic.cancelled', { name: humanized }),
    }),
  }
}

/** Look up the formatter for an action name. Falls back to a
 *  name-aware generic formatter for any name not in the supported
 *  set — that's intentional: actions without a custom renderer in
 *  the timeline row should ALSO not have custom-extraction bubble
 *  content (the user said: "ONLY handle actions that is also handled
 *  in the action renderer"). But the generic version still SHOWS the
 *  action name so the user knows what's happening. */
export function getMascotFormatter(name: string | undefined): MascotActionFormatter {
  // Final-final fallback when the action has no name at all (defensive —
  // shouldn't happen in practice, but keeps the bubble alive if it does).
  if (!name) return makeGenericFormatter(i18n.t('activity:generic.actionNoun'))
  const normalized = normalizeActionName(name)
  return isSupportedActionName(normalized) ? FORMATTER_REGISTRY[normalized] : makeGenericFormatter(name)
}
