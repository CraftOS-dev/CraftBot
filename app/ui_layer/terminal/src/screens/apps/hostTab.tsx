/**
 * Plumbing shared by the three tabs of Add Agent App (Marketplace, Create,
 * Import): the controller each tab hook returns to the screen, a labelled
 * form row and a wrapped multi-line text field for the app description.
 */
import type { ReactNode } from 'react'
import { Box, Text, type Key } from 'ink'
import type { KeyHint } from '../../ui/Frame'
import { fieldKey } from '../../ui/TextField'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, splitGraphemes, truncate, width, wrap } from '../../text/width'
import type { Tr } from './hostThemes'

/** What a tab hook hands the screen. */
export interface TabController {
  /** Route a key; false lets the screen use it (Esc then moves focus to the tab bar). */
  handleKey: (input: string, key: Key) => boolean
  /** A text field has focus: single letters belong to it. */
  textFocus: boolean
  hints: KeyHint[]
  body: ReactNode
  /** Leaving would lose typed input. */
  dirty: boolean
}

export interface TabProps {
  t: Tr
  columns: number
  /** Rows available to the tab's body. */
  height: number
  /** The tab is shown. */
  active: boolean
  /** Move on to the app screen of a new project. */
  onOpenProject: (projectId: string) => void
}

/** Prose wrapped to `cols`, without the leading space a wrap leaves on continuation lines. */
export function wrapProse(text: string, cols: number): string[] {
  return wrap(text, cols).map(line => line.trimStart())
}

/** A form row: pointer, fixed-width label, then the field. */
export function FormRow({ label, labelWidth, focused, error, children }: { label: string; labelWidth: number; focused: boolean; error?: boolean; children: ReactNode }) {
  const g = glyphs()
  return (
    <Box>
      <Text color={focused ? ink.focus : undefined}>{focused ? `${g.pointer} ` : '  '}</Text>
      <Text color={error ? ink.error : focused ? ink.focus : ink.muted} bold={focused}>{padEnd(truncate(label, labelWidth - 1), labelWidth)}</Text>
      {children}
    </Box>
  )
}

/** Split a row of text at display column `col`: before, the grapheme there, after. */
function splitAtColumn(text: string, col: number): [string, string, string] {
  let before = ''
  let used = 0
  const parts = splitGraphemes(text)
  let i = 0
  for (; i < parts.length; i++) {
    const w = width(parts[i])
    if (used + w > col) break
    before += parts[i]
    used += w
  }
  return [before, parts[i] ?? '', parts.slice(i + 1).join('')]
}

/**
 * A wrapped multi-line field showing up to `maxRows` rows around the caret.
 * The parent owns the buffer and routes keys through `multiLineKey`.
 */
export function MultiLineField({ buffer, focused, width: cols, maxRows, placeholder }: { buffer: TB.Buffer; focused: boolean; width: number; maxRows: number; placeholder?: string }) {
  const room = Math.max(4, cols - 1)
  if (!buffer.text) {
    return (
      <Text color={ink.muted}>
        {focused ? <Text inverse> </Text> : null}
        {truncate(placeholder ?? '', room - 1)}
      </Text>
    )
  }
  const lay = TB.layout(buffer, room)
  const count = Math.max(1, Math.min(maxRows, lay.rows.length))
  const start = focused ? Math.max(0, Math.min(lay.cursorRow - count + 1, lay.rows.length - count)) : 0
  const visible = lay.rows.slice(start, start + count)
  return (
    <Box flexDirection="column">
      {visible.map((row, i) => {
        const index = start + i
        const more = !focused && i === count - 1 && lay.rows.length > count ? ' …' : ''
        if (!focused || index !== lay.cursorRow) return <Text key={index}>{truncate(row.text, room - width(more)) + more}</Text>
        const [before, at, after] = splitAtColumn(row.text, lay.cursorCol)
        return (
          <Text key={index}>
            {before}
            <Text inverse>{at || ' '}</Text>
            {after}
          </Text>
        )
      })}
    </Box>
  )
}

/**
 * Editing keys of a multi-line field: Shift+Enter, Alt+Enter or Ctrl+J add a
 * line, Up/Down move by visual row (null at the edges, so the form moves to
 * the next field), pasted text keeps its line breaks. Null = not an edit.
 */
export function multiLineKey(buf: TB.Buffer, input: string, key: Key, cols: number): TB.Buffer | null {
  if (key.return && (key.shift || key.meta)) return TB.insert(buf, '\n')
  if (key.return) return null
  if (input === '\n' && !key.ctrl && !key.meta) return TB.insert(buf, '\n')
  if (key.upArrow || key.downArrow) return TB.verticalMove(buf, Math.max(4, cols - 1), key.upArrow ? -1 : 1)
  if (input.length > 1 && /[\r\n]/.test(input) && !key.ctrl && !key.meta) {
    const text = input.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0009\u000B-\u001F\u007F]/g, '')
    return text ? TB.insert(buf, text) : null
  }
  return fieldKey(buf, input, key)
}
