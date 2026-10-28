/**
 * Final transcript units as terminal text, written into scrollback once.
 *
 *   ❯ Find a table for two at 7 tonight.
 *
 *   ✓ 3 actions · Web search (2), Run shell · 41.2s
 *
 *   ● Booked Sorae for 19:00. The confirmation
 *     number is 4417.
 *     ✓ 19:00 works
 *
 *   · Memory processing finished
 *
 * Each block hangs under a two-cell gutter: the prompt for the user, a dot
 * for the agent, the outcome of a group of actions, a quiet dot for notices,
 * a cross for errors. One blank line opens where the kind of content
 * changes; blocks of the same kind sit flush, and a user message always
 * opens a new group. Lines are wrapped to the width at write time; a width
 * change prints the recent units again. Details live in the transcript
 * screen (Ctrl+O).
 */
import type { ActionItem, ChatMessage } from '../../../browser/frontend/src/types'
import { QUESTION_DISMISSED } from '../../../browser/frontend/src/types'
import i18n from '../platform/i18n'
import { actionPreview, displayActionName, formatDuration } from '../chat/activity'
import type { Unit } from '../chat/timeline'
import { glyphs, tone } from '../theme/theme'
import { renderMarkdown } from './markdown'
import { stripEmoji } from '../text/emoji'
import { oneLine, truncate, width, wrapLines } from '../text/width'

/** Cells of the gutter every block hangs under. */
const INDENT = 2

export type Group = 'user' | 'agent' | 'actions' | 'notice'

export function groupOf(unit: Unit): Group {
  if (unit.kind === 'chunk') return 'actions'
  if (unit.message.style === 'user') return 'user'
  if (unit.message.style === 'agent') return 'agent'
  return 'notice'
}

export function clockTime(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000)
  return d.toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })
}

function formatBytes(size: number | undefined): string {
  if (!size || size < 0) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

/** "Aria · 14:03": who wrote a message and when (the transcript screen's heading). */
export function senderLine(message: ChatMessage): string {
  const g = glyphs()
  const sender = stripEmoji(message.sender ?? '')
  const time = tone.muted(` ${g.sep} ${clockTime(message.timestamp)}`)
  switch (message.style) {
    case 'agent':
      return tone.brandBold(sender) + time
    case 'user':
      return tone.bold(sender || i18n.t('screensView:transcript.you')) + time
    case 'error':
      return tone.error(tone.bold(sender || i18n.t('tui:transcript.error'))) + time
    default:
      return tone.muted(tone.bold(sender || i18n.t('tui:transcript.system'))) + time
  }
}

/** Lines hung under a gutter mark: the mark on the first, the indent on the rest. */
function hang(mark: string, lines: string[], columns: number): string[] {
  const inner = Math.max(10, columns - INDENT - 1)
  const wrapped = wrapLines(lines.length ? lines : [''], inner)
  return wrapped.map((line, i) => (i === 0 ? mark + ' ' : ' '.repeat(INDENT)) + line)
}

function markOf(message: ChatMessage): string {
  const g = glyphs()
  switch (message.style) {
    case 'agent':
      return tone.brand(g.agent)
    case 'user':
      return tone.muted(g.prompt)
    case 'error':
      return tone.error(g.failed)
    default:
      return tone.muted(g.notice)
  }
}

export function renderMessage(message: ChatMessage, columns: number): string[] {
  const g = glyphs()
  const inner = Math.max(10, columns - INDENT - 1)
  let body = renderMarkdown(message.content ?? '', inner)
  if (message.style === 'error') body = body.map(l => tone.error(l))
  else if (message.style === 'system' || message.style === 'info') body = body.map(l => tone.muted(l))

  // What hangs under the text: files, the answer given, outputs, details.
  const extra: string[] = []
  for (const attachment of message.attachments ?? []) {
    const size = formatBytes(attachment.size)
    extra.push(
      `${tone.muted(g.artifact)} ${stripEmoji(attachment.name)}` +
        (size ? tone.muted(` ${g.sep} ${size}`) : '') +
        (attachment.path ? tone.dim(`  ${attachment.path}`) : ''),
    )
  }
  if (message.options?.length) {
    const chosen = message.optionSelected
    if (chosen && chosen !== QUESTION_DISMISSED) {
      const label = stripEmoji(message.options.find(o => o.value === chosen)?.label ?? chosen)
      extra.push(`${tone.success(g.done)} ${label}`)
    } else if (chosen === QUESTION_DISMISSED) {
      extra.push(tone.muted(`${g.failed} ${i18n.t('tui:question.dismissed')}`))
    } else if (message.requiresChoice === false) {
      // Convenience links rather than a blocking choice: list them.
      message.options.forEach((o, i) => extra.push(`${tone.muted(`${i + 1}.`)} ${stripEmoji(o.label)}${o.url ? tone.dim(`  ${o.url}`) : ''}`))
    }
  }
  if (message.uiArtifact) {
    extra.push(
      tone.muted(
        `${g.artifact} ${i18n.t('tui:transcript.interactiveOutput', {
          title: stripEmoji(message.uiArtifact.title),
          revision: message.uiArtifact.revision,
        })}`,
      ),
    )
  }
  if (message.details) extra.push(tone.dim(i18n.t('tui:transcript.detailsHint')))
  return hang(markOf(message), [...body, ...extra], columns)
}

/** "Web search (2), Run shell": action names in order of first use, repeats counted. */
function actionNames(actions: ActionItem[]): string {
  const counts = new Map<string, number>()
  for (const a of actions) {
    const name = displayActionName(a.name)
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  return [...counts].map(([name, n]) => (n > 1 ? `${name} (${n})` : name)).join(', ')
}

/**
 * A finished group of actions as one line, led by its outcome:
 *
 *   ✓ Web search · flights KUL to NRT on 12 Nov · 1.1s
 *   ✓ 9 actions · Label email (7), Archive email (2) · 51s
 *   ✗ 9 actions · 1 failed · Archive email: rate limited · 51s
 *   ■ 4 actions · stopped · 6.2s
 */
export function renderChunk(unit: Extract<Unit, { kind: 'chunk' }>, columns: number): string[] {
  const g = glyphs()
  const actions = unit.items.filter(i => i.itemType === 'action')
  const first = unit.items[0]?.createdAt ?? 0
  const last = Math.max(...unit.items.map(i => i.completedAt ?? i.createdAt ?? 0))
  const duration = formatDuration(last - first)
  const failedItem = actions.find(a => a.status === 'error')
  const stopped = !failedItem && actions.some(a => a.status === 'cancelled')
  const sep = tone.dim(` ${g.sep} `)

  const mark = failedItem ? tone.error(g.failed) : stopped ? tone.warn(g.stopped) : tone.success(g.done)
  const parts: string[] = []
  if (actions.length === 1) {
    const only = actions[0]
    parts.push(displayActionName(only.name))
    if (failedItem) parts.push(tone.error(oneLine(actionPreview(only))))
    else if (stopped) parts.push(tone.warn(i18n.t('tui:transcript.stopped')))
    else {
      const preview = oneLine(actionPreview(only))
      if (preview) parts.push(tone.muted(preview))
    }
  } else {
    parts.push(i18n.t('tui:transcript.actions', { count: unit.actionCount }))
    if (failedItem) {
      parts.push(tone.error(i18n.t('tui:transcript.failed', { count: unit.failed })))
      const reason = oneLine(actionPreview(failedItem))
      parts.push(tone.error(`${displayActionName(failedItem.name)}${reason ? `: ${reason}` : ''}`))
    } else if (stopped) {
      parts.push(tone.warn(i18n.t('tui:transcript.stopped')))
    } else {
      parts.push(tone.muted(actionNames(actions)))
    }
  }
  const tail = duration ? sep + tone.dim(duration) : ''
  const room = Math.max(10, columns - INDENT - 1 - width(tail))
  return [`${mark} ${truncate(parts.join(sep), room)}${tail}`]
}

/**
 * A unit as the block it adds to scrollback. `previous` is the group of the
 * unit printed before it (null at the top of a session): a blank line opens
 * only where the group changes, and before every user message.
 */
export function renderUnit(unit: Unit, columns: number, previous: Group | null = null): string {
  const group = groupOf(unit)
  const gap = previous === null || previous !== group || group === 'user' ? '\n' : ''
  const lines = unit.kind === 'message' ? renderMessage(unit.message, columns) : renderChunk(unit, columns)
  return gap + lines.join('\n') + '\n'
}

/** The divider printed when the chat opens a session: "── Main ───────". */
export function renderSessionDivider(title: string, columns: number): string {
  const g = glyphs()
  const label = truncate(stripEmoji(title), Math.max(8, columns - 10))
  const rest = Math.max(2, Math.min(columns, 100) - width(label) - 5)
  return '\n' + tone.border(g.rule.repeat(2)) + ' ' + tone.bold(label) + ' ' + tone.border(g.rule.repeat(rest)) + '\n'
}

export interface WelcomeInfo {
  version: string
  agentName: string
  model: string
}

/**
 * The card printed when the chat starts: the product and version in the top
 * edge, the agent and its model, a line on how to begin, and the first keys
 * in the bottom edge. Under 48 columns, two plain lines instead.
 *
 *   ╭─ CraftBot v1.4.5 ──────────────────────────────────────╮
 *   │ Aria · claude-sonnet-5                                  │
 *   │ Ask anything. Type / for commands, @ to attach files.   │
 *   ╰─ / commands · ? help · Ctrl+X s sessions ───────────────╯
 */
export function renderWelcome(info: WelcomeInfo, columns: number): string {
  const g = glyphs()
  const version = info.version ? `v${info.version.replace(/^v/, '')}` : ''
  const keys: [string, string][] = [
    ['/', i18n.t('tui:welcome.commands')],
    ['?', i18n.t('tui:welcome.help')],
    ['Ctrl+X s', i18n.t('tui:welcome.sessions')],
    ['Ctrl+O', i18n.t('tui:welcome.transcript')],
  ]
  const hintText = (list: [string, string][]) => list.map(([k, l]) => `${tone.bold(k)} ${tone.muted(l)}`).join(tone.dim(` ${g.sep} `))
  const hintWidth = (list: [string, string][]) => width(list.map(([k, l]) => `${k} ${l}`).join(` ${g.sep} `))

  if (columns < 48) {
    return '\n' + `${tone.brandBold('CraftBot')}${version ? ' ' + tone.muted(version) : ''}` + '\n' + hintText(keys.slice(0, 2)) + '\n'
  }

  const boxWidth = Math.min(columns - 1, 76)
  const inner = boxWidth - 4
  const edge = (left: string, right: string, label: string, labelWidth: number) =>
    tone.brand(left + g.boxH + ' ') + label + tone.brand(' ' + g.boxH.repeat(Math.max(0, boxWidth - labelWidth - 5)) + right)
  const row = (text: string) => {
    const shown = truncate(text, inner)
    return tone.brand(g.boxV) + ' ' + shown + ' '.repeat(Math.max(0, inner - width(shown))) + ' ' + tone.brand(g.boxV)
  }
  const shownKeys = keys.slice()
  while (shownKeys.length > 1 && hintWidth(shownKeys) > boxWidth - 6) shownKeys.pop()
  const title = `${tone.brandBold('CraftBot')}${version ? ' ' + tone.muted(version) : ''}`
  const titleWidth = width(`CraftBot${version ? ' ' + version : ''}`)
  const facts = [tone.bold(stripEmoji(info.agentName)), info.model ? tone.muted(info.model) : ''].filter(Boolean).join(tone.dim(` ${g.sep} `))

  const lines = [
    edge(g.boxTopLeft, g.boxTopRight, title, titleWidth),
    ...(facts ? [row(facts)] : []),
    row(tone.muted(i18n.t('tui:welcome.tagline'))),
    edge(g.boxBottomLeft, g.boxBottomRight, hintText(shownKeys), hintWidth(shownKeys)),
  ]
  return '\n' + lines.join('\n') + '\n'
}
