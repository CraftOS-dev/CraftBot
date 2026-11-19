/**
 * How a list shows its selected row: the pointer in the first two cells and
 * the selection chip (theme.ts) behind the row's text, both only while the
 * list has focus. An unfocused list keeps a muted pointer so the place is
 * not lost.
 *
 *   ❯ Sessions            screen    Every conversation      (chip behind)
 *     Settings            screen    Model, keys, skills
 */
import { Text } from 'ink'
import { chip, glyphs, ink } from '../theme/theme'

export function Pointer({ selected, focused = true }: { selected: boolean; focused?: boolean }) {
  const g = glyphs()
  return (
    <Text color={focused ? ink.focus : ink.muted} bold>
      {selected ? `${g.pointer} ` : '  '}
    </Text>
  )
}

/**
 * Text props for one run of a row: the chip when selected and focused (the
 * accent color stands in where there is no chip), else the run's own color.
 */
export function rowStyle(selected: boolean, focused = true, color?: string): { color?: string; backgroundColor?: string; bold?: boolean } {
  if (!selected) return { color }
  if (!focused) return { color, bold: true }
  return chip.bg ? { color: chip.fg, backgroundColor: chip.bg, bold: true } : { color: ink.focus, bold: true }
}

/** The chip behind a secondary run (meta, details) of the selected row. */
export function rowMetaStyle(selected: boolean, focused = true, color?: string): { color?: string; backgroundColor?: string } {
  if (!selected || !focused || !chip.bg) return { color }
  return { color: chip.fg, backgroundColor: chip.bg }
}
