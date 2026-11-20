/**
 * A single-line text field for filters and forms, on the same grapheme-aware
 * buffer as the composer. The parent owns the value and routes keys through
 * `fieldKey`, so focus is explicit and testable.
 */
import { Box, Text } from 'ink'
import type { Key } from 'ink'
import * as TB from '../input/TextBuffer'
import { ink } from '../theme/theme'
import { truncate, width } from '../text/width'

/** Apply an editing key to a single-line buffer; null when the key is not an edit. */
export function fieldKey(buf: TB.Buffer, input: string, key: Key): TB.Buffer | null {
  if (key.backspace) return key.meta ? TB.deleteWordBack(buf) : TB.backspace(buf)
  if (key.delete) return TB.deleteForward(buf)
  if (key.leftArrow) return key.ctrl || key.meta ? TB.wordLeft(buf) : TB.left(buf)
  if (key.rightArrow) return key.ctrl || key.meta ? TB.wordRight(buf) : TB.right(buf)
  if (key.home || (key.ctrl && input === 'a')) return TB.home(buf)
  if (key.end || (key.ctrl && input === 'e')) return TB.end(buf)
  if (key.ctrl && input === 'u') return TB.killToLineStart(buf)
  if (key.ctrl && input === 'w') return TB.deleteWordBack(buf)
  if (key.ctrl || key.meta || key.return || key.escape || key.tab || key.upArrow || key.downArrow) return null
  if (!input) return null
  const text = input.replace(/[\r\n]+/g, ' ').replace(/[\u0000-\u001F\u007F]/g, '')
  return text ? TB.insert(buf, text) : null
}

export interface TextFieldProps {
  label?: string
  buffer: TB.Buffer
  focused: boolean
  width: number
  placeholder?: string
  /** Show dots instead of the text (API keys, passwords). */
  masked?: boolean
}

export function TextField({ label, buffer, focused, width: total, placeholder, masked }: TextFieldProps) {
  const labelText = label ? `${label} ` : ''
  const room = Math.max(4, total - width(labelText) - 1)
  const shown = masked ? '•'.repeat(Math.min(buffer.text.length, 64)) : buffer.text
  const caret = masked ? Math.min(buffer.cursor, 64) : width(buffer.text.slice(0, buffer.cursor))
  // Scroll horizontally to keep the caret visible.
  const start = Math.max(0, caret - room + 1)
  const visible = shown.length && start > 0 ? truncate(shown.slice(start), room) : truncate(shown, room)
  const caretCol = caret - start
  return (
    <Box>
      {labelText ? <Text color={focused ? ink.focus : ink.muted}>{labelText}</Text> : null}
      {buffer.text.length === 0 && placeholder ? (
        <Text color={ink.muted}>
          {focused ? <Text inverse> </Text> : null}
          {truncate(placeholder, room)}
        </Text>
      ) : focused ? (
        <Text>
          {visible.slice(0, caretCol)}
          <Text inverse>{visible.slice(caretCol, caretCol + 1) || ' '}</Text>
          {visible.slice(caretCol + 1)}
        </Text>
      ) : (
        <Text>{visible}</Text>
      )}
    </Box>
  )
}
