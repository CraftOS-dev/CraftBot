/**
 * The live block of a running turn:
 *
 *   ⠹ Working… 12s · esc stop
 *     ├ ✓ 6 more done
 *     ├ ✓ Read file      src/main.ts                       0.8s
 *     └ ◐ Run shell      npm test                          3.2s
 *
 * The working row heads it: the one animated glyph on screen, the state in
 * words, the elapsed time and the way to stop. While a question waits on the
 * user the spinner gives way to a still mark. Under it hang the running
 * chunk's latest actions (status glyph, name, one-line preview, timer) and
 * the sub-agents still at work; older finished actions fold into one row.
 * The block never unmounts between actions, so the region does not jump.
 */
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { ActionItem } from '../../../browser/frontend/src/types'
import { actionPreview, displayActionName, formatDuration } from './activity'
import { glyphs, ink, spinnerFrames } from '../theme/theme'
import { padEnd, truncate, width } from '../text/width'
import { useTicker } from '../ui/useTicker'

/** Child rows under the working row, the fold row included. */
export const MAX_CHILD_ROWS = 4

function statusGlyph(item: ActionItem): { glyph: string; color?: string } {
  const g = glyphs()
  switch (item.status) {
    case 'completed':
      return { glyph: g.done, color: ink.success }
    case 'error':
      return { glyph: g.failed, color: ink.error }
    case 'cancelled':
      return { glyph: g.stopped, color: ink.warn }
    case 'running':
    case 'waiting':
      return { glyph: g.running, color: ink.brand }
    default:
      return { glyph: g.pending, color: ink.dim }
  }
}

function Connector({ last }: { last: boolean }) {
  const g = glyphs()
  return <Text color={ink.border}>{`  ${last ? g.last : g.tee} `}</Text>
}

function ActionRow({ item, columns, now, last, nameCol }: { item: ActionItem; columns: number; now: number; last: boolean; nameCol: number }) {
  const { glyph, color } = statusGlyph(item)
  const end = item.completedAt ?? now
  const ms = item.createdAt ? end - item.createdAt : 0
  // Times show once an action has taken half a second.
  const timer = ms >= 500 ? formatDuration(ms) : ''
  const previewCols = Math.max(0, columns - 7 - nameCol - (timer ? width(timer) + 2 : 0))
  const preview = truncate(actionPreview(item), previewCols)
  const pad = Math.max(0, previewCols - width(preview))
  return (
    <Box>
      <Connector last={last} />
      <Text color={color}>{glyph} </Text>
      <Text color={item.status === 'pending' ? ink.dim : undefined}>{padEnd(displayActionName(item.name), nameCol)}</Text>
      <Text color={ink.muted}>{preview}</Text>
      {timer ? <Text color={ink.dim}>{' '.repeat(pad + 2) + timer}</Text> : null}
    </Box>
  )
}

export interface SubagentRow {
  id: string
  agentType: string
  actions: number
}

export interface WorkingBlockProps {
  startedAt: number
  stopping: boolean
  /** A question or choice waits on the user. */
  waiting?: boolean
  items: ActionItem[]
  /** Sub-agents this turn started that are still running. */
  subagents?: SubagentRow[]
  columns: number
}

/** The actions shown under the working row, and how many finished ones fold. */
export function shownActions(items: ActionItem[], subagents: number): { shown: ActionItem[]; folded: number } {
  const actions = items.filter(i => i.itemType === 'action')
  const room = Math.max(1, MAX_CHILD_ROWS - subagents)
  if (actions.length <= room) return { shown: actions, folded: 0 }
  const shown = actions.slice(-(room - 1))
  return { shown, folded: actions.length - shown.length }
}

export function WorkingBlock({ startedAt, stopping, waiting = false, items, subagents = [], columns }: WorkingBlockProps) {
  const { t } = useTranslation('tui')
  const g = glyphs()
  const tick = useTicker(100, !waiting)
  const now = Date.now()
  const frames = spinnerFrames()
  const elapsed = formatDuration(now - startedAt)
  const label = waiting ? t('working.waiting') : stopping ? t('working.stopping') : `${t('working.label')}${g.ellipsis}`
  const hint = stopping || waiting ? '' : t('working.stopHint')
  const { shown, folded } = shownActions(items, subagents.length)
  const nameCol = Math.min(18, Math.max(10, ...shown.map(i => width(displayActionName(i.name)))) + 2)
  const childCount = (folded > 0 ? 1 : 0) + shown.length + subagents.length
  let index = 0
  const isLast = () => ++index === childCount

  return (
    <Box flexDirection="column">
      <Box>
        <Text color={waiting ? ink.warn : ink.brand}>{`${waiting ? g.warn : frames[tick % frames.length]} `}</Text>
        <Text bold>{truncate(label, Math.max(4, columns - 4))}</Text>
        {columns >= 36 ? <Text color={ink.muted}>{` ${elapsed}`}</Text> : null}
        {hint && columns >= 60 ? <Text color={ink.dim}>{` ${g.sep} ${hint}`}</Text> : null}
      </Box>
      {folded > 0 ? (
        <Box>
          <Connector last={isLast()} />
          <Text color={ink.success}>{g.done} </Text>
          <Text color={ink.muted}>{t('working.moreDone', { count: folded })}</Text>
        </Box>
      ) : null}
      {shown.map(item => (
        <ActionRow key={item.id} item={item} columns={columns} now={now} last={isLast()} nameCol={nameCol} />
      ))}
      {subagents.map(sub => (
        <Box key={sub.id}>
          <Connector last={isLast()} />
          <Text color={ink.brand}>{g.running} </Text>
          <Text color={ink.muted}>{truncate(t('working.subagent', { name: sub.agentType, count: sub.actions }), Math.max(4, columns - 7))}</Text>
        </Box>
      ))}
    </Box>
  )
}

/** Rows the block takes, for the live region's height budget. */
export function workingBlockHeight(items: ActionItem[], subagents: number): number {
  const { shown, folded } = shownActions(items, subagents)
  return 1 + (folded > 0 ? 1 : 0) + shown.length + subagents
}
