/**
 * The transcript screen's model, kept free of React and i18n so it can be
 * tested on its own: the session as blocks (messages and the activity
 * between them), each block's lines, the line layout the screen scrolls
 * through, search, and the Markdown forms used for copy and $EDITOR.
 *
 * Unlike the chat's scrollback (chat/timeline.ts), nothing is folded away
 * here: every action row, every reasoning item and every details payload is
 * part of the transcript.
 */
import stripAnsi from 'strip-ansi'
import type { ActionItem, ChatMessage } from '../../../browser/frontend/src/types'
import { QUESTION_DISMISSED } from '../../../browser/frontend/src/types'
import { mergeTimeline } from '../../../browser/frontend/src/components/Chat/timeline'
import { actionPreview, displayActionName, formatDuration, isChatSend } from '../chat/activity'
import { glyphs, paint, tone } from '../theme/theme'
import { splitGraphemes, truncate, width, wrap } from '../text/width'

export type Block =
  | { kind: 'message'; key: string; message: ChatMessage }
  | { kind: 'chunk'; key: string; items: ActionItem[] }

const LIVE: ReadonlySet<string> = new Set(['running', 'waiting', 'paused', 'pending'])

/** The marker the backend puts between a reply and the message it quotes. */
export const REPLY_MARKER = '[REPLYING TO PREVIOUS AGENT MESSAGE]:'

/** A user message's own text and the agent message it replied to, if any. */
export function splitReply(content: string): { text: string; quoted: string | null } {
  const at = content.indexOf(REPLY_MARKER)
  if (at === -1) return { text: content, quoted: null }
  return { text: content.slice(0, at).trimEnd(), quoted: content.slice(at + REPLY_MARKER.length).trim() }
}

function keepItem(item: ActionItem): boolean {
  if (isChatSend(item)) return false
  // A reasoning item that never produced text says nothing once it is over.
  if (item.itemType === 'reasoning' && !item.output?.trim() && !LIVE.has(item.status)) return false
  return true
}

/** One session's messages and activity as transcript blocks, oldest first. */
export function buildBlocks(messages: ChatMessage[], activity: ActionItem[]): Block[] {
  const blocks: Block[] = []
  let chunk: ActionItem[] = []
  const flush = () => {
    const items = chunk.filter(keepItem)
    chunk = []
    if (items.length) blocks.push({ kind: 'chunk', key: `chunk:${items[0].id}`, items })
  }
  for (const entry of mergeTimeline(messages, activity)) {
    if (entry.kind === 'message') {
      flush()
      // Optimistic bubbles wait for the server's echo.
      if (!entry.message.pending) blocks.push({ kind: 'message', key: `msg:${entry.message.messageId}`, message: entry.message })
    } else {
      chunk.push(entry.item)
    }
  }
  flush()
  return blocks
}

// --- chunk lines ------------------------------------------------------------

export interface ChunkLabels {
  actions: (count: number) => string
  failed: (count: number) => string
  reasoning: string
  thinking: string
  status: Record<'running' | 'waiting' | 'paused' | 'pending' | 'cancelled', string>
}

function itemDuration(item: ActionItem, now: number): string {
  if (LIVE.has(item.status)) return item.createdAt ? formatDuration(Math.max(0, now - item.createdAt)) : ''
  if (item.duration != null) return formatDuration(item.duration)
  if (item.completedAt && item.createdAt) return formatDuration(item.completedAt - item.createdAt)
  return ''
}

function statusMark(item: ActionItem): string {
  const g = glyphs()
  switch (item.status) {
    case 'completed':
      return tone.success(g.done)
    case 'error':
      return tone.error(g.failed)
    case 'running':
      return tone.brand(g.running)
    default:
      return tone.muted(g.pending)
  }
}

/** The one-line summary of a chunk: "▸ 6 actions · 41.2s · ✗ 1 failed". */
export function chunkHeader(items: ActionItem[], labels: ChunkLabels): string {
  const g = glyphs()
  const actions = items.filter(i => i.itemType === 'action')
  const failed = actions.filter(a => a.status === 'error').length
  const live = items.some(i => LIVE.has(i.status))
  const first = items[0]?.createdAt ?? 0
  const last = Math.max(...items.map(i => i.completedAt ?? i.createdAt ?? 0))
  const parts = [actions.length ? labels.actions(actions.length) : labels.reasoning]
  if (live) parts.push(labels.status.running)
  else if (first && last > first) parts.push(formatDuration(last - first))
  let line = tone.muted(`${g.chunk} ${parts.join(' · ')}`)
  if (failed) line += ' ' + tone.error(`${g.failed} ${labels.failed(failed)}`)
  return line
}

function indented(text: string, indent: string, columns: number, paintLine: (s: string) => string): string[] {
  const room = Math.max(10, columns - width(indent))
  const out: string[] = []
  for (const line of text.replace(/\t/g, '    ').split('\n')) {
    if (!line.trim()) {
      out.push('')
      continue
    }
    for (const piece of wrap(line, room)) out.push(indent + paintLine(piece))
  }
  while (out.length && out[out.length - 1] === '') out.pop()
  return out
}

/**
 * A chunk with every row: status, name, preview and duration for each
 * action (with its full error text), and each reasoning item's text.
 * Collapsed, only the summary line.
 */
export function chunkLines(items: ActionItem[], labels: ChunkLabels, columns: number, expanded = true, now = Date.now()): string[] {
  const g = glyphs()
  const lines = [chunkHeader(items, labels)]
  if (!expanded) return lines
  for (const item of items) {
    if (item.itemType === 'reasoning') {
      lines.push(`  ${tone.muted(labels.reasoning)}`)
      const text = item.output?.trim()
      if (text) lines.push(...indented(text, `  ${tone.muted(g.vbar)} `, columns, s => tone.muted(tone.italic(s))))
      else lines.push(`  ${tone.muted(g.vbar)} ${tone.muted(labels.thinking)}`)
      continue
    }
    const name = displayActionName(item.name)
    const statusWord = item.status in labels.status ? labels.status[item.status as keyof ChunkLabels['status']] : ''
    const duration = itemDuration(item, now)
    const tail = [statusWord, duration].filter(Boolean).join(' ')
    const fixed = `  ${g.done} ${name}`
    const preview = item.status === 'error' ? '' : actionPreview(item)
    const room = Math.max(0, columns - width(fixed) - (tail ? width(tail) + 2 : 0) - 2)
    const shownPreview = preview && room > 3 ? truncate(preview.replace(/\t/g, ' '), room) : ''
    lines.push(
      `  ${statusMark(item)} ${name}` +
        (shownPreview ? `  ${tone.muted(shownPreview)}` : '') +
        (tail ? `  ${tone.muted(tail)}` : ''),
    )
    if (item.status === 'error' && item.error?.trim()) {
      lines.push(...indented(item.error.trim(), '      ', columns, s => tone.error(s)))
    }
  }
  return lines
}

// --- layout -----------------------------------------------------------------

export interface Layout {
  /** Display lines, each fitted to the width. */
  lines: string[]
  /** For each line, the index of the block it belongs to (-1: gaps and headers). */
  blockOf: number[]
  /** First line of each block. */
  starts: number[]
  /** One past the last line of each block. */
  ends: number[]
}

/** Lay blocks out as lines (header lines first, one blank line between blocks). */
export function layoutBlocks(
  blocks: Block[],
  render: (block: Block, index: number) => string[],
  columns: number,
  header: string[] = [],
): Layout {
  const lines: string[] = []
  const blockOf: number[] = []
  const starts: number[] = []
  const ends: number[] = []
  for (const line of header) {
    for (const piece of fit(line, columns)) {
      lines.push(piece)
      blockOf.push(-1)
    }
  }
  blocks.forEach((block, index) => {
    if (lines.length) {
      lines.push('')
      blockOf.push(-1)
    }
    starts.push(lines.length)
    for (const line of render(block, index)) {
      for (const piece of fit(line, columns)) {
        lines.push(piece)
        blockOf.push(index)
      }
    }
    ends.push(lines.length)
  })
  return { lines, blockOf, starts, ends }
}

/** A line hard-wrapped to the width (tabs expanded: Ink cannot measure them). */
export function fit(line: string, columns: number): string[] {
  const text = line.includes('\t') ? line.replace(/\t/g, '    ') : line
  if (text === '' || width(text) <= columns) return [text]
  return wrap(text, columns)
}

/** Where the view's top edge sits: a block and a line offset into it. */
export interface Anchor {
  key: string
  offset: number
}

export function maxTop(layout: Layout, height: number): number {
  return Math.max(0, layout.lines.length - height)
}

/** The top line for an anchor; null anchors follow the bottom (newest). */
export function resolveTop(anchor: Anchor | null, blocks: Block[], layout: Layout, height: number): number {
  const bottom = maxTop(layout, height)
  if (!anchor) return bottom
  const index = blocks.findIndex(b => b.key === anchor.key)
  if (index === -1) return bottom
  return Math.max(0, Math.min(bottom, layout.starts[index] + anchor.offset))
}

/** The anchor that keeps line `top` at the top when blocks are added above. */
export function anchorFor(top: number, blocks: Block[], layout: Layout, height: number): Anchor | null {
  if (blocks.length === 0) return null
  const clamped = Math.max(0, Math.min(maxTop(layout, height), top))
  // The first block that starts at or after the top line, or the last one.
  let index = layout.starts.findIndex(start => start >= clamped)
  if (index === -1) index = blocks.length - 1
  if (index > 0 && layout.starts[index] > clamped && layout.ends[index - 1] > clamped) index -= 1
  return { key: blocks[index].key, offset: clamped - layout.starts[index] }
}

/** Scroll the least needed so a block is in view (its top when it is taller than the view). */
export function revealBlock(top: number, index: number, layout: Layout, height: number): number {
  const start = layout.starts[index]
  const end = layout.ends[index]
  if (start === undefined || end === undefined) return top
  if (start < top) return start
  if (end > top + height) return end - start > height ? start : end - height
  return top
}

/** The block a line belongs to, or the nearest block after it (else before it). */
export function blockAtLine(line: number, layout: Layout): number {
  for (let i = Math.max(0, line); i < layout.blockOf.length; i++) {
    if (layout.blockOf[i] >= 0) return layout.blockOf[i]
  }
  for (let i = Math.min(line, layout.blockOf.length - 1); i >= 0; i--) {
    if (layout.blockOf[i] >= 0) return layout.blockOf[i]
  }
  return -1
}

// --- search -----------------------------------------------------------------

/** Lines whose visible text contains the query (case-insensitive). */
export function findMatches(lines: string[], query: string): number[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  const out: number[] = []
  lines.forEach((line, index) => {
    if (stripAnsi(line).toLowerCase().includes(needle)) out.push(index)
  })
  return out
}

/** The next match after `from` (dir 1) or before it (dir -1), wrapping around. */
export function stepMatch(matches: number[], from: number, dir: 1 | -1): number | null {
  if (matches.length === 0) return null
  if (dir === 1) return matches.find(m => m > from) ?? matches[0]
  for (let i = matches.length - 1; i >= 0; i--) if (matches[i] < from) return matches[i]
  return matches[matches.length - 1]
}

/** The line as plain text with every occurrence of the query marked. */
export function highlightMatches(line: string, query: string, mark: (s: string) => string = s => paint.inverse(s)): string {
  const plain = stripAnsi(line)
  const needle = query.trim().toLowerCase()
  if (!needle) return line
  const lower = plain.toLowerCase()
  // Lowercasing can change lengths (rare scripts): fall back to the plain line.
  if (lower.length !== plain.length) return plain
  let out = ''
  let at = 0
  for (;;) {
    const hit = lower.indexOf(needle, at)
    if (hit === -1) break
    out += plain.slice(at, hit) + mark(plain.slice(hit, hit + needle.length))
    at = hit + needle.length
  }
  return out + plain.slice(at)
}

// --- Markdown forms -----------------------------------------------------------

/** A message as Markdown for the clipboard (a reply's quote left out, as in the browser). */
export function messageMarkdown(message: ChatMessage): string {
  const content = message.style === 'user' ? splitReply(message.content ?? '').text : message.content ?? ''
  const parts = [content.trim()]
  for (const attachment of message.attachments ?? []) {
    parts.push(`[${attachment.name}]${attachment.path ? `(${attachment.path})` : ''}`)
  }
  return parts.filter(Boolean).join('\n\n')
}

function inlineCode(text: string): string {
  const one = text.replace(/\s+/g, ' ').trim()
  if (!one) return ''
  const fence = one.includes('`') ? '``' : '`'
  return `${fence}${one}${fence}`
}

/** A chunk as a Markdown list: one item per action or reasoning step. */
export function chunkMarkdown(items: ActionItem[], labels: ChunkLabels, now = Date.now()): string {
  const out: string[] = []
  for (const item of items) {
    if (item.itemType === 'reasoning') {
      const text = item.output?.trim()
      out.push(`- ${labels.reasoning}${text ? `:\n${text.split('\n').map(l => `  > ${l}`).join('\n')}` : ''}`)
      continue
    }
    const mark = item.status === 'completed' ? '[x]' : item.status === 'error' ? '[!]' : '[ ]'
    const preview = item.status === 'error' ? '' : inlineCode(actionPreview(item))
    const duration = itemDuration(item, now)
    const statusWord = item.status in labels.status ? labels.status[item.status as keyof ChunkLabels['status']] : ''
    const tail = [statusWord, duration].filter(Boolean).join(', ')
    let line = `- ${mark} ${displayActionName(item.name)}${preview ? ` ${preview}` : ''}${tail ? ` (${tail})` : ''}`
    if (item.status === 'error' && item.error?.trim()) {
      line += '\n' + item.error.trim().split('\n').map(l => `  > ${l}`).join('\n')
    }
    out.push(line)
  }
  return out.join('\n')
}

export interface MarkdownOptions {
  title: string
  /** "Aria · 14:03" for a message's heading. */
  heading: (message: ChatMessage) => string
  labels: ChunkLabels
  detailsLabel: string
  replyingToLabel: string
}

/** The whole conversation as one Markdown document (for $EDITOR). */
export function conversationMarkdown(blocks: Block[], options: MarkdownOptions): string {
  const out: string[] = [`# ${options.title}`]
  for (const block of blocks) {
    if (block.kind === 'chunk') {
      out.push(`> ${stripAnsi(chunkHeader(block.items, options.labels))}`, chunkMarkdown(block.items, options.labels))
      continue
    }
    const message = block.message
    out.push(`## ${options.heading(message)}`)
    const body = messageMarkdown(message)
    if (body) out.push(body)
    if (message.style === 'user') {
      const { quoted } = splitReply(message.content ?? '')
      if (quoted) out.push(`> ${options.replyingToLabel}:\n${quoted.split('\n').map(l => `> ${l}`).join('\n')}`)
    }
    if (message.options?.length) {
      const chosen = message.optionSelected
      out.push(message.options.map(o => `- ${chosen && chosen === o.value ? '[x]' : '[ ]'} ${o.label}`).join('\n'))
      if (chosen === QUESTION_DISMISSED) out.push('- (dismissed)')
    }
    if (message.details?.trim()) out.push(`<details><summary>${options.detailsLabel}</summary>\n\n${message.details.trim()}\n\n</details>`)
  }
  return out.join('\n\n') + '\n'
}

/** A file-name-safe slug of a title (for the $EDITOR temp file). */
export function slug(title: string): string {
  const ascii = splitGraphemes(title.toLowerCase())
    .map(c => (/^[a-z0-9]$/.test(c) ? c : '-'))
    .join('')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  return ascii.slice(0, 40) || 'chat'
}
