/**
 * A tiny row model for screens that lay text out themselves (the dashboard's
 * columns, the memory detail pane): a row is a list of styled segments,
 * measured and cut in cells (text/width.ts), never in string length.
 */
import { truncate, width } from '../text/width'

export interface Seg {
  text: string
  color?: string
  bold?: boolean
  inverse?: boolean
}

export type Row = Seg[]

export function seg(text: string, color?: string, bold?: boolean): Seg {
  return { text, color, bold }
}

export function rowText(row: Row): string {
  return row.map(s => s.text).join('')
}

export function rowWidth(row: Row): number {
  return width(rowText(row))
}

/** Cut a row to `max` cells (an ellipsis where it is cut) and pad it to exactly `max`. */
export function fitRow(row: Row, max: number): Row {
  if (max <= 0) return []
  const out: Row = []
  let used = 0
  for (let i = 0; i < row.length; i++) {
    const s = row[i]
    const w = width(s.text)
    if (used + w <= max) {
      out.push(s)
      used += w
      continue
    }
    const room = max - used
    if (room > 0) {
      const text = truncate(s.text, room)
      out.push({ ...s, text })
      used += width(text)
    }
    break
  }
  if (used < max) out.push({ text: ' '.repeat(max - used) })
  return out
}

/**
 * Lay two stacks of rows side by side: the left fitted to `leftWidth`, then
 * `gap` spaces, then the right fitted to `rightWidth`. The shorter side is
 * padded with blank rows.
 */
export function joinColumns(left: Row[], right: Row[], leftWidth: number, gap: number, rightWidth: number): Row[] {
  const count = Math.max(left.length, right.length)
  const rows: Row[] = []
  for (let i = 0; i < count; i++) {
    rows.push([
      ...fitRow(left[i] ?? [], leftWidth),
      { text: ' '.repeat(Math.max(0, gap)) },
      ...fitRow(right[i] ?? [], rightWidth),
    ])
  }
  return rows
}

/** Stack sections with one blank row between them. */
export function stackSections(sections: Row[][]): Row[] {
  const rows: Row[] = []
  sections.forEach((section, i) => {
    if (i > 0 && section.length) rows.push([])
    rows.push(...section)
  })
  return rows
}
