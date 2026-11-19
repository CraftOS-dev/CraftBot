/**
 * Display-width helpers. Terminals lay text out in cells: CJK characters take
 * two, combining marks none, and an emoji sequence is one grapheme. Every
 * measurement goes through string-width (East Asian Width aware, ambiguous
 * characters narrow) and every split through Intl.Segmenter, so a line never
 * overflows its width and a cursor never lands inside a grapheme.
 */
import stringWidth from 'string-width'
import cliTruncate from 'cli-truncate'
import wrapAnsi from 'wrap-ansi'

const graphemes = new Intl.Segmenter(undefined, { granularity: 'grapheme' })

export function width(text: string): number {
  return stringWidth(text)
}

/** Split into graphemes (user-perceived characters). */
export function splitGraphemes(text: string): string[] {
  return Array.from(graphemes.segment(text), s => s.segment)
}

/** Truncate to `max` cells with an ellipsis, ANSI-safe. */
export function truncate(text: string, max: number, position: 'end' | 'middle' | 'start' = 'end'): string {
  if (max <= 0) return ''
  if (width(text) <= max) return text
  return cliTruncate(text, max, { position })
}

/** Pad on the right to exactly `size` cells (truncating if longer). */
export function padEnd(text: string, size: number): string {
  const t = truncate(text, size)
  return t + ' '.repeat(Math.max(0, size - width(t)))
}

export function padStart(text: string, size: number): string {
  const t = truncate(text, size)
  return ' '.repeat(Math.max(0, size - width(t))) + t
}

/**
 * Hard-wrap to `columns` cells (ANSI-safe, words kept whole when they fit).
 * A piece that continues a wrapped line drops the space it broke at; the
 * line's own indentation (code, nested lists) stays on its first piece.
 */
export function wrap(text: string, columns: number): string[] {
  if (columns <= 0) return [text]
  return wrapAnsi(text, columns, { hard: true, trim: false })
    .split('\n')
    .map((piece, i) => (i === 0 ? piece : piece.replace(/^((?:\u001B\[[0-9;]*m)*) /, '$1')))
}

/** Hard-wrap every line of a block (screens lay text out themselves). */
export function wrapLines(lines: string[], columns: number): string[] {
  return lines.flatMap(line => (line === '' ? [''] : wrap(line, columns)))
}

/** Collapse whitespace and newlines into one line (previews). */
export function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}
