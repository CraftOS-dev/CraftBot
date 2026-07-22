// One-line speech-bubble formatters for the mascot's action display.
// Parallel to the JSX renderers in renderers.tsx — same action set, same
// input/output field extraction, but each formatter produces a small POJO
// (label + body + status) instead of card-sized JSX.
//
// COLOCATED WITH THE RENDERERS ON PURPOSE: SupportedActionName is the
// shared type between the two registries. If you add a new action's
// renderer to REGISTRY in renderers.tsx, you must add it to
// SUPPORTED_ACTION_NAMES — and then TypeScript will force you to add the
// matching formatter to FORMATTER_REGISTRY here too (and vice versa).
// That prevents the two display paths from drifting out of sync.

import { basename, strField, arrField, dictField } from './parse'
import { extractTodos, isSupportedActionName, normalizeActionName, type SupportedActionName } from './renderers'

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
// `basename` is imported from parse.ts — same util the renderers use.

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
// (see renderers.tsx), so the source-of-truth for "which fields matter"
// stays in one place per action.

// FILE OPS ───────────────────────────────────────────────────────────

const stream_edit: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'file_path') ?? ''
    return { status: 'running', label: 'Editing file', body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, _o, s) => {
    const fp = strField(i, 'file_path') ?? ''
    const verb = s === 'completed' ? 'Edited file' : s === 'error' ? 'Edit failed' : 'Edit cancelled'
    return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
}

const read_file: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'file_path') ?? ''
    return { status: 'running', label: 'Reading file', body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, o, s) => {
    const fp = strField(i, 'file_path') ?? ''
    const lines = lineCount(strField(o, 'content') ?? '')
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Read failed' : 'Read cancelled'
      return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
    }
    return { status: s, label: 'Read file', body: lines > 0 ? `${lines.toLocaleString()} lines` : (fp ? basename(fp) : undefined), bodyMono: lines === 0 && !!fp }
  },
}

const find_files: MascotActionFormatter = {
  running: (i) => {
    const pattern = strField(i, 'pattern') ?? ''
    return { status: 'running', label: 'Finding files', body: pattern || undefined, bodyMono: true }
  },
  result: (i, o, s) => {
    const pattern = strField(i, 'pattern') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Find failed' : 'Find cancelled'
      return { status: s, label: verb, body: pattern || undefined, bodyMono: true }
    }
    const count = (arrField(o, 'matches') ?? []).length
    return { status: s, label: `Found ${count.toLocaleString()} file${count === 1 ? '' : 's'}`, body: pattern || undefined, bodyMono: true }
  },
}

const list_folder: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'path') ?? ''
    return { status: 'running', label: 'Listing folder', body: path ? basename(path) || '/' : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'path') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'List failed' : 'List cancelled'
      return { status: s, label: verb, body: path ? basename(path) || '/' : undefined, bodyMono: !!path }
    }
    const count = (arrField(o, 'contents') ?? []).length
    return { status: s, label: 'Listed folder', body: `${count.toLocaleString()} item${count === 1 ? '' : 's'}` }
  },
}

// Formatter for convert_to_pdf — covers all source formats via one schema.
const convertToPdf: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'output_path') ?? ''
    return { status: 'running', label: 'Creating PDF', body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, o, s) => {
    const fp = strField(o, 'path') ?? strField(i, 'output_path') ?? ''
    const verb = s === 'completed' ? 'Created PDF' : s === 'error' ? 'PDF creation failed' : 'PDF creation cancelled'
    return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
}

const read_pdf: MascotActionFormatter = {
  running: (i) => {
    const fp = strField(i, 'file_path') ?? ''
    return { status: 'running', label: 'Reading PDF', body: fp ? basename(fp) : undefined, bodyMono: !!fp }
  },
  result: (i, o, s) => {
    const fp = strField(i, 'file_path') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'PDF read failed' : 'PDF read cancelled'
      return { status: s, label: verb, body: fp ? basename(fp) : undefined, bodyMono: !!fp }
    }
    const contentObj = dictField(o, 'content')
    const elements = arrField(contentObj, 'elements') ?? []
    return { status: s, label: 'Read PDF', body: elements.length > 0 ? `${elements.length} element${elements.length === 1 ? '' : 's'}` : (fp ? basename(fp) : undefined), bodyMono: elements.length === 0 && !!fp }
  },
}

const convert_to_markdown: MascotActionFormatter = {
  running: (i) => {
    const src = strField(i, 'input_file') ?? ''
    return { status: 'running', label: 'Converting to markdown', body: src ? basename(src) : undefined, bodyMono: !!src }
  },
  result: (i, o, s) => {
    const out = strField(o, 'md_file') ?? strField(i, 'output_md') ?? ''
    const verb = s === 'completed' ? 'Converted to markdown' : s === 'error' ? 'Convert failed' : 'Convert cancelled'
    return { status: s, label: verb, body: out ? basename(out) : undefined, bodyMono: !!out }
  },
}

// CODE EXECUTION ─────────────────────────────────────────────────────

const run_python: MascotActionFormatter = {
  running: (i) => {
    const lines = lineCount(strField(i, 'code') ?? '')
    return { status: 'running', label: 'Running Python', body: lines > 0 ? `${lines} line${lines === 1 ? '' : 's'}` : undefined }
  },
  result: (_i, o, s) => {
    const stderr = strField(o, 'stderr') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Python failed' : 'Python cancelled'
      return { status: s, label: verb, body: stderr ? firstSnippet(stderr, 60) : undefined }
    }
    // Successful completion that wrote to stderr usually still indicates
    // a problem worth surfacing (e.g., warnings). Show the first stderr
    // line; otherwise just say it ran.
    if (stderr) return { status: s, label: 'Ran Python', body: firstSnippet(stderr, 60) }
    const stdout = strField(o, 'stdout') ?? ''
    return { status: s, label: 'Ran Python', body: stdout ? `${lineCount(stdout)} line${lineCount(stdout) === 1 ? '' : 's'} output` : undefined }
  },
}

const run_shell: MascotActionFormatter = {
  running: (i) => {
    const cmd = strField(i, 'command') ?? ''
    return { status: 'running', label: 'Running command', body: cmd ? `$ ${cmd}` : undefined, bodyMono: true }
  },
  result: (i, _o, s) => {
    const cmd = strField(i, 'command') ?? ''
    const verb = s === 'completed' ? 'Ran command' : s === 'error' ? 'Command failed' : 'Command cancelled'
    return { status: s, label: verb, body: cmd ? `$ ${cmd}` : undefined, bodyMono: true }
  },
}

// WEB ────────────────────────────────────────────────────────────────

const web_search: MascotActionFormatter = {
  running: (i) => {
    const q = strField(i, 'query') ?? ''
    return { status: 'running', label: 'Searching web', body: q ? quote(q) : undefined }
  },
  result: (i, o, s) => {
    const q = strField(i, 'query') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Search failed' : 'Search cancelled'
      return { status: s, label: verb, body: q ? quote(q) : undefined }
    }
    const count = (arrField(o, 'results') ?? []).length
    return { status: s, label: `Found ${count.toLocaleString()} result${count === 1 ? '' : 's'}`, body: q ? quote(q) : undefined }
  },
}

const web_fetch: MascotActionFormatter = {
  running: (i) => {
    const url = strField(i, 'url') ?? ''
    return { status: 'running', label: 'Fetching page', body: url ? hostname(url) : undefined }
  },
  result: (i, o, s) => {
    const url = strField(i, 'url') ?? ''
    const title = strField(o, 'title')
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Fetch failed' : 'Fetch cancelled'
      return { status: s, label: verb, body: url ? hostname(url) : undefined }
    }
    return { status: s, label: title ? `Fetched ${trim(title, 40)}` : 'Fetched page', body: url ? hostname(url) : undefined }
  },
}

const http_request: MascotActionFormatter = {
  running: (i) => {
    const method = (strField(i, 'method') ?? 'GET').toUpperCase()
    const url = strField(i, 'url') ?? ''
    return { status: 'running', label: `${method} request`, body: url ? hostname(url) : undefined }
  },
  result: (i, o, s) => {
    const method = (strField(i, 'method') ?? 'GET').toUpperCase()
    const url = strField(i, 'url') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? `${method} failed` : `${method} cancelled`
      return { status: s, label: verb, body: url ? hostname(url) : undefined }
    }
    const body = strField(o, 'body') ?? ''
    return { status: s, label: `${method} response`, body: body ? `${body.length.toLocaleString()} chars` : (url ? hostname(url) : undefined) }
  },
}

// MEDIA ──────────────────────────────────────────────────────────────

const generate_image: MascotActionFormatter = {
  running: (i) => {
    const p = strField(i, 'prompt') ?? ''
    return { status: 'running', label: 'Generating image', body: p ? quote(trim(p, 60)) : undefined }
  },
  result: (i, o, s) => {
    const p = strField(i, 'prompt') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Generation failed' : 'Generation cancelled'
      return { status: s, label: verb, body: p ? quote(trim(p, 60)) : undefined }
    }
    const count = (arrField(o, 'image_paths') ?? []).length
    return { status: s, label: `Generated ${count} image${count === 1 ? '' : 's'}`, body: p ? quote(trim(p, 60)) : undefined }
  },
}

const describe_image: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'image_path') ?? ''
    return { status: 'running', label: 'Describing image', body: path ? basename(path) : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'image_path') ?? ''
    const desc = strField(o, 'description') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Describe failed' : 'Describe cancelled'
      return { status: s, label: verb, body: path ? basename(path) : undefined, bodyMono: !!path }
    }
    return { status: s, label: 'Described image', body: desc ? firstSnippet(desc, 60) : (path ? basename(path) : undefined), bodyMono: !desc && !!path }
  },
}

const perform_ocr: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'image_path') ?? ''
    return { status: 'running', label: 'Reading image text', body: path ? basename(path) : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'image_path') ?? ''
    const summary = strField(o, 'summary') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'OCR failed' : 'OCR cancelled'
      return { status: s, label: verb, body: path ? basename(path) : undefined, bodyMono: !!path }
    }
    return { status: s, label: 'Extracted text', body: summary ? `${summary.length.toLocaleString()} characters` : (path ? basename(path) : undefined), bodyMono: !summary && !!path }
  },
}

const understand_video: MascotActionFormatter = {
  running: (i) => {
    const path = strField(i, 'video_path') ?? ''
    return { status: 'running', label: 'Analyzing video', body: path ? basename(path) : undefined, bodyMono: !!path }
  },
  result: (i, o, s) => {
    const path = strField(i, 'video_path') ?? ''
    const summary = strField(o, 'summary') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Analysis failed' : 'Analysis cancelled'
      return { status: s, label: verb, body: path ? basename(path) : undefined, bodyMono: !!path }
    }
    return { status: s, label: 'Analyzed video', body: summary ? firstSnippet(summary, 60) : (path ? basename(path) : undefined), bodyMono: !summary && !!path }
  },
}

// SEARCH ─────────────────────────────────────────────────────────────

const grep_files: MascotActionFormatter = {
  running: (i) => {
    const p = strField(i, 'pattern') ?? ''
    return { status: 'running', label: 'Grepping', body: p || undefined, bodyMono: true }
  },
  result: (i, o, s) => {
    const p = strField(i, 'pattern') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Grep failed' : 'Grep cancelled'
      return { status: s, label: verb, body: p || undefined, bodyMono: true }
    }
    const count = (arrField(o, 'filenames') ?? []).length
    return { status: s, label: `Found in ${count.toLocaleString()} file${count === 1 ? '' : 's'}`, body: p || undefined, bodyMono: true }
  },
}

const memory_search: MascotActionFormatter = {
  running: (i) => {
    const q = strField(i, 'query') ?? ''
    return { status: 'running', label: 'Searching memory', body: q ? quote(q) : undefined }
  },
  result: (i, o, s) => {
    const q = strField(i, 'query') ?? ''
    if (s !== 'completed') {
      const verb = s === 'error' ? 'Memory search failed' : 'Memory search cancelled'
      return { status: s, label: verb, body: q ? quote(q) : undefined }
    }
    const count = (arrField(o, 'results') ?? []).length
    return { status: s, label: `Found ${count.toLocaleString()} memor${count === 1 ? 'y' : 'ies'}`, body: q ? quote(q) : undefined }
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
    return { status: 'running', label: 'Sending message', body: msg ? firstSnippet(msg, 60) : undefined }
  },
  result: (_i, _o, s) => {
    const verb = s === 'completed' ? 'Sent message' : s === 'error' ? 'Send failed' : 'Send cancelled'
    return { status: s, label: verb }
  },
}

const send_message_with_attachment: MascotActionFormatter = {
  running: (i) => {
    const count = (arrField(i, 'file_paths') ?? []).length
    return { status: 'running', label: 'Sending message', body: count > 0 ? `+ ${count} attachment${count === 1 ? '' : 's'}` : undefined }
  },
  result: (i, _o, s) => {
    const count = (arrField(i, 'file_paths') ?? []).length
    const verb = s === 'completed' ? 'Sent message' : s === 'error' ? 'Send failed' : 'Send cancelled'
    return { status: s, label: verb, body: count > 0 ? `+ ${count} attachment${count === 1 ? '' : 's'}` : undefined }
  },
}

// TODOS ──────────────────────────────────────────────────────────────

const update_todos: MascotActionFormatter = {
  running: (i) => {
    const todos = extractTodos(i)
    if (!todos || todos.length === 0) {
      return { status: 'running', label: 'Updating todos' }
    }
    const done = todos.filter(t => t.status === 'completed').length
    const inProgress = todos.find(t => t.status === 'in_progress')
    const progress = `${done}/${todos.length} done`
    const body = inProgress ? `${progress} · ${trim(inProgress.content, 40)}` : progress
    return { status: 'running', label: 'Updating todos', body }
  },
  result: (i, _o, s) => {
    const todos = extractTodos(i)
    const verb = s === 'completed' ? 'Updated todos' : s === 'error' ? 'Update failed' : 'Update cancelled'
    if (!todos || todos.length === 0) {
      return { status: s, label: verb }
    }
    const done = todos.filter(t => t.status === 'completed').length
    return { status: s, label: verb, body: `${done}/${todos.length} done` }
  },
}

// ─────────────────────────────────────────────────────────────────────
// Registry + lookup
// ─────────────────────────────────────────────────────────────────────

/** Exhaustive map from every SupportedActionName to its formatter.
 *  Typed as Record<SupportedActionName, …> so any new entry in
 *  SUPPORTED_ACTION_NAMES (in renderers.tsx) becomes a compile error
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
  if (!spaced) return 'action'
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
    running: () => ({ status: 'running', label: `Running ${humanized}` }),
    result: (_i, _o, s) => ({
      status: s,
      label: s === 'completed' ? `${humanized} completed`
        : s === 'error' ? `${humanized} failed`
          : `${humanized} cancelled`,
    }),
  }
}

/** Final-final fallback used when the action has no name at all
 *  (defensive — shouldn't happen in practice, but keeps the bubble
 *  alive instead of crashing if it does). */
const GENERIC_FORMATTER: MascotActionFormatter = makeGenericFormatter('action')

/** Look up the formatter for an action name. Falls back to a
 *  name-aware generic formatter for any name not in the supported
 *  set — that's intentional: actions without a custom renderer in
 *  renderers.tsx should ALSO not have custom-extraction bubble
 *  content (the user said: "ONLY handle actions that is also handled
 *  in the action renderer"). But the generic version still SHOWS the
 *  action name so the user knows what's happening. */
export function getMascotFormatter(name: string | undefined): MascotActionFormatter {
  if (!name) return GENERIC_FORMATTER
  const normalized = normalizeActionName(name)
  return isSupportedActionName(normalized) ? FORMATTER_REGISTRY[normalized] : makeGenericFormatter(name)
}
