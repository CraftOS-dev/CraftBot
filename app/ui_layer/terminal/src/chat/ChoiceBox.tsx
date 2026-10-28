/**
 * The pinned box above the composer for anything that waits on the user: an
 * agent question (oldest first, "1 of N") or a choice such as Continue / Stop
 * at a limit. It holds the whole question; the transcript records it, with
 * the answer, once answered. The first option of a question is the
 * recommended one. Typing a normal message answers a question; Tab moves
 * focus into the box to pick an option with digits or arrows and Enter. Esc
 * gives focus back without dismissing, so a question never swallows typing.
 *
 *   ╭─ Aria is asking · 1 of 2 ─────────────────────────╮
 *   │ Which time works for you?                          │
 *   │ ❯ 1. 19:00  recommended                            │
 *   │   2. 20:00                                         │
 *   ╰─ Type an answer, or Tab to choose an option ───────╯
 *
 * The title rides the top edge and the hint the bottom edge. The pointer and
 * the selection chip show only while the box has focus.
 */
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import type { ChatMessage } from '../../../browser/frontend/src/types'
import { borderStyle, chip, glyphs, ink } from '../theme/theme'
import { padEnd, truncate, width, wrapLines } from '../text/width'
import { renderMarkdown } from '../render/markdown'
import { stripEmoji } from '../text/emoji'
import { TitledBorder } from '../ui/TitledBorder'

const MAX_BODY_LINES = 8

function bodyLines(message: ChatMessage, inner: number, max: number): string[] {
  const lines = wrapLines(renderMarkdown(message.content ?? '', inner), inner)
  if (lines.length <= max) return lines
  return [...lines.slice(0, max - 1), `${lines[max - 1]} ${glyphs().ellipsis}`]
}

export interface ChoiceBoxProps {
  message: ChatMessage
  index: number
  total: number
  focused: boolean
  selected: number
  columns: number
  /** Most rows the question's text takes (the rest is cut with an ellipsis). */
  maxBodyLines?: number
}

export function ChoiceBox({ message, index, total, focused, selected, columns, maxBodyLines = MAX_BODY_LINES }: ChoiceBoxProps) {
  const { t } = useTranslation('tui')
  const g = glyphs()
  const options = message.options ?? []
  const inner = Math.max(10, columns - 4)
  const title = message.isQuestion
    ? t('question.title', { name: stripEmoji(message.sender), index: index + 1, total })
    : t('question.choiceTitle')
  const hint = focused
    ? message.isQuestion
      ? t('question.focusedHint')
      : t('question.focusedChoiceHint')
    : message.isQuestion
      ? t('question.hint')
      : t('question.choiceHint')
  const edge = focused ? ink.focus : ink.brand

  return (
    <Box flexDirection="column" width={columns}>
      <TitledBorder title={title} columns={columns} color={edge} titleColor={ink.brand} />
      <Box flexDirection="column" borderStyle={borderStyle()} borderTop={false} borderBottom={false} borderColor={edge} paddingX={1} width={columns}>
        {bodyLines(message, inner, maxBodyLines).map((line, i) => (
          <Text key={i} bold>{line}</Text>
        ))}
        {options.map((option, i) => {
          const active = focused && i === selected
          const recommended = i === 0 && message.isQuestion ? `  ${t('question.recommended')}` : ''
          const label = truncate(`${i + 1}. ${stripEmoji(option.label)}`, Math.max(8, inner - 2 - width(recommended)))
          // The chip spans the row; padding keeps its right edge straight.
          const rest = active && chip.bg ? padEnd(label + recommended, inner - 2).slice(label.length) : recommended
          return (
            <Text key={option.value}>
              <Text color={ink.focus} bold>{active ? `${g.pointer} ` : '  '}</Text>
              <Text color={active ? chip.fg : undefined} backgroundColor={active ? chip.bg : undefined} bold={active}>{label}</Text>
              <Text color={ink.muted} backgroundColor={active ? chip.bg : undefined}>{rest}</Text>
            </Text>
          )
        })}
      </Box>
      <TitledBorder title={hint} columns={columns} edge="bottom" color={edge} titleColor={ink.muted} titleBold={false} />
    </Box>
  )
}

/** Rows the box takes, for the live region's height budget. */
export function choiceBoxHeight(message: ChatMessage, columns: number, maxBodyLines = MAX_BODY_LINES): number {
  const inner = Math.max(10, columns - 4)
  // Top edge, the question, one row per option, bottom edge.
  return 1 + bodyLines(message, inner, maxBodyLines).length + (message.options ?? []).length + 1
}
