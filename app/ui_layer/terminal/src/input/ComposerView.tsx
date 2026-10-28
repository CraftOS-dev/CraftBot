/**
 * The composer's view: a rule across the width, then the prompt marker and
 * the text in visual rows (scrolled to keep the caret in view), with the real
 * terminal cursor placed at the caret so IME preedit and candidate windows
 * appear where the user types. Rows scrolled out of view are counted in the
 * rule's right end.
 *
 *   ──────────────────────────────────────────── ↑ 2 more ──
 *   ❯ Find a table for two at 7 tonight
 */
import { useEffect, useRef } from 'react'
import { Box, Text, useBoxMetrics, useCursor, type DOMElement } from 'ink'
import { useTranslation } from 'react-i18next'
import * as TB from './TextBuffer'
import { glyphs, ink } from '../theme/theme'
import { truncate, width } from '../text/width'

export interface ComposerViewProps {
  buffer: TB.Buffer
  columns: number
  placeholder: string
  maxRows: number
  /** Whether the caret is shown (false while another box has focus). */
  focused: boolean
  /** Rows of the live region above this box (for the cursor's absolute row). */
  offsetTop: number
}

export const PROMPT_WIDTH = 2

/** Cells a composer row of text gets at this terminal width. */
export function composerTextColumns(columns: number): number {
  return Math.max(4, columns - PROMPT_WIDTH - 1)
}

/** Rows the composer takes besides its text rows (the rule). */
export const COMPOSER_CHROME_ROWS = 1

/** A laid-out element's position on screen: its own and its ancestors' offsets. */
function screenOrigin(node: DOMElement | null): { x: number; y: number } {
  let x = 0
  let y = 0
  for (let n: DOMElement | undefined = node ?? undefined; n; n = n.parentNode) {
    const layout = n.yogaNode?.getComputedLayout()
    if (layout) {
      x += layout.left
      y += layout.top
    }
  }
  return { x, y }
}

export function ComposerView({ buffer, columns, placeholder, maxRows, focused, offsetTop }: ComposerViewProps) {
  const { t } = useTranslation('tui')
  const ref = useRef<DOMElement | null>(null)
  const metrics = useBoxMetrics(ref)
  const { setCursorPosition } = useCursor()
  const lay = TB.layout(buffer, composerTextColumns(columns))

  // Keep the caret's row inside the visible window.
  const total = lay.rows.length
  const visible = Math.min(total, maxRows)
  const firstRow = Math.min(Math.max(0, lay.cursorRow - visible + 1), Math.max(0, total - visible))
  const rows = lay.rows.slice(firstRow, firstRow + visible)
  const empty = buffer.text.length === 0

  useEffect(() => {
    if (!focused) {
      setCursorPosition(undefined)
      return
    }
    // Where the box sits on screen: its offsets summed up to the root, so
    // the caret lands right inside a nested panel too.
    const origin = metrics.hasMeasured ? screenOrigin(ref.current) : { x: 0, y: offsetTop }
    setCursorPosition({ x: origin.x + PROMPT_WIDTH + lay.cursorCol, y: origin.y + 1 + (lay.cursorRow - firstRow) })
  })

  const g = glyphs()
  const above = firstRow
  const below = total - firstRow - rows.length
  const tags = [
    above > 0 ? t('composer.moreAbove', { count: above }) : '',
    below > 0 ? t('composer.moreBelow', { count: below }) : '',
  ].filter(Boolean)
  const tag = tags.length ? truncate(tags.join(` ${g.sep} `), Math.max(0, columns - 8)) : ''
  const ruleWidth = Math.max(0, columns - 1)
  const promptColor = focused ? ink.brand : ink.muted

  return (
    <Box ref={ref} flexDirection="column" width={columns}>
      <Text>
        <Text color={ink.border}>{g.rule.repeat(Math.max(0, ruleWidth - (tag ? width(tag) + 5 : 0)))}</Text>
        {tag ? (
          <>
            <Text color={ink.dim}>{` ${tag} `}</Text>
            <Text color={ink.border}>{g.rule.repeat(3)}</Text>
          </>
        ) : null}
      </Text>
      {empty ? (
        <Box>
          <Text color={promptColor} bold>{g.prompt} </Text>
          <Text color={ink.dim}>{truncate(placeholder, composerTextColumns(columns))}</Text>
        </Box>
      ) : (
        rows.map((row, i) => (
          <Box key={firstRow + i}>
            <Text color={promptColor} bold>{firstRow + i === 0 ? `${g.prompt} ` : '  '}</Text>
            <Text>{row.text}</Text>
          </Box>
        ))
      )}
    </Box>
  )
}
