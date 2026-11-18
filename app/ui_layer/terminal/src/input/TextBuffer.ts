/**
 * The composer's editable text: an immutable value plus a caret.
 *
 * Every caret move and deletion steps over whole graphemes (so an emoji, a
 * CJK character or a letter with combining marks is one step), and word
 * motion uses Intl.Segmenter's word boundaries, which also segment Japanese
 * and Chinese. Layout splits logical lines (the user's newlines) into visual
 * rows by display width, so Up/Down move by what the user sees.
 */
import { width } from '../text/width'

const graphemeSegmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
const wordSegmenter = new Intl.Segmenter(undefined, { granularity: 'word' })

export interface Buffer {
  readonly text: string
  /** Caret as a UTF-16 index, always on a grapheme boundary. */
  readonly cursor: number
}

export const EMPTY: Buffer = { text: '', cursor: 0 }

export function fromText(text: string): Buffer {
  return { text, cursor: text.length }
}

function boundaries(text: string): number[] {
  const out = [0]
  for (const seg of graphemeSegmenter.segment(text)) out.push(seg.index + seg.segment.length)
  return out
}

function prevBoundary(text: string, index: number): number {
  let prev = 0
  for (const b of boundaries(text)) {
    if (b >= index) break
    prev = b
  }
  return prev
}

function nextBoundary(text: string, index: number): number {
  for (const b of boundaries(text)) if (b > index) return b
  return text.length
}

export function insert(buf: Buffer, value: string): Buffer {
  const text = buf.text.slice(0, buf.cursor) + value + buf.text.slice(buf.cursor)
  return { text, cursor: buf.cursor + value.length }
}

export function backspace(buf: Buffer): Buffer {
  if (buf.cursor === 0) return buf
  const start = prevBoundary(buf.text, buf.cursor)
  return { text: buf.text.slice(0, start) + buf.text.slice(buf.cursor), cursor: start }
}

export function deleteForward(buf: Buffer): Buffer {
  if (buf.cursor >= buf.text.length) return buf
  const end = nextBoundary(buf.text, buf.cursor)
  return { text: buf.text.slice(0, buf.cursor) + buf.text.slice(end), cursor: buf.cursor }
}

export function left(buf: Buffer): Buffer {
  return { ...buf, cursor: prevBoundary(buf.text, buf.cursor) }
}

export function right(buf: Buffer): Buffer {
  return { ...buf, cursor: nextBoundary(buf.text, buf.cursor) }
}

function wordStarts(text: string): number[] {
  const starts: number[] = []
  for (const seg of wordSegmenter.segment(text)) if (seg.isWordLike) starts.push(seg.index)
  return starts
}

function wordEnds(text: string): number[] {
  const ends: number[] = []
  for (const seg of wordSegmenter.segment(text)) if (seg.isWordLike) ends.push(seg.index + seg.segment.length)
  return ends
}

export function wordLeft(buf: Buffer): Buffer {
  const target = wordStarts(buf.text).filter(s => s < buf.cursor).pop() ?? 0
  return { ...buf, cursor: target }
}

export function wordRight(buf: Buffer): Buffer {
  const target = wordEnds(buf.text).find(e => e > buf.cursor) ?? buf.text.length
  return { ...buf, cursor: target }
}

/** Ctrl+W / Alt+Backspace: delete back to the start of the previous word. */
export function deleteWordBack(buf: Buffer): Buffer {
  const start = wordLeft(buf).cursor
  return { text: buf.text.slice(0, start) + buf.text.slice(buf.cursor), cursor: start }
}

function lineStart(text: string, index: number): number {
  return text.lastIndexOf('\n', index - 1) + 1
}

function lineEnd(text: string, index: number): number {
  const nl = text.indexOf('\n', index)
  return nl === -1 ? text.length : nl
}

export function home(buf: Buffer): Buffer {
  return { ...buf, cursor: lineStart(buf.text, buf.cursor) }
}

export function end(buf: Buffer): Buffer {
  return { ...buf, cursor: lineEnd(buf.text, buf.cursor) }
}

/** Ctrl+U: delete to the start of the current line. */
export function killToLineStart(buf: Buffer): Buffer {
  const start = lineStart(buf.text, buf.cursor)
  return { text: buf.text.slice(0, start) + buf.text.slice(buf.cursor), cursor: start }
}

/** Ctrl+K: delete to the end of the current line. */
export function killToLineEnd(buf: Buffer): Buffer {
  const stop = lineEnd(buf.text, buf.cursor)
  const cut = stop === buf.cursor && stop < buf.text.length ? stop + 1 : stop
  return { text: buf.text.slice(0, buf.cursor) + buf.text.slice(cut), cursor: buf.cursor }
}

// --- layout -----------------------------------------------------------------

export interface VisualRow {
  /** Text of the row (no newline). */
  text: string
  /** UTF-16 index of the row's first character. */
  start: number
  /** UTF-16 index just past the row's last character. */
  end: number
}

export interface Layout {
  rows: VisualRow[]
  cursorRow: number
  /** Caret column in display cells. */
  cursorCol: number
}

/** Split into visual rows of at most `columns` cells; locate the caret. */
export function layout(buf: Buffer, columns: number): Layout {
  const cols = Math.max(1, columns)
  const rows: VisualRow[] = []
  let offset = 0
  for (const line of buf.text.split('\n')) {
    let rowStart = offset
    let rowWidth = 0
    let rowText = ''
    for (const seg of graphemeSegmenter.segment(line)) {
      const w = width(seg.segment)
      if (rowWidth + w > cols && rowText) {
        rows.push({ text: rowText, start: rowStart, end: offset + seg.index })
        rowStart = offset + seg.index
        rowText = ''
        rowWidth = 0
      }
      rowText += seg.segment
      rowWidth += w
    }
    rows.push({ text: rowText, start: rowStart, end: offset + line.length })
    offset += line.length + 1
  }

  let cursorRow = rows.length - 1
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    const next = rows[i + 1]
    // The caret belongs to this row unless it sits exactly at a soft-wrap
    // boundary, where it shows at the start of the next row.
    if (buf.cursor >= row.start && buf.cursor <= row.end && !(next && next.start === buf.cursor && row.end === buf.cursor)) {
      cursorRow = i
      break
    }
  }
  const row = rows[cursorRow]
  const cursorCol = width(buf.text.slice(row.start, Math.min(buf.cursor, row.end)))
  return { rows, cursorRow, cursorCol }
}

/** Move the caret one visual row up or down, keeping its column. Null at the edge. */
export function verticalMove(buf: Buffer, columns: number, delta: -1 | 1): Buffer | null {
  const lay = layout(buf, columns)
  const target = lay.cursorRow + delta
  if (target < 0 || target >= lay.rows.length) return null
  const row = lay.rows[target]
  let col = 0
  let index = row.start
  for (const seg of graphemeSegmenter.segment(row.text)) {
    const w = width(seg.segment)
    if (col + w > lay.cursorCol) break
    col += w
    index = row.start + seg.index + seg.segment.length
  }
  return { ...buf, cursor: Math.min(index, row.end) }
}
