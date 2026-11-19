/**
 * Terminal cell width without dependencies: wide and fullwidth characters
 * (CJK, Hangul, fullwidth forms) and emoji take two cells, combining marks
 * none. Split by grapheme so a cut never lands inside one.
 */
const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })

function isWide(cp: number): boolean {
  return (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0x303e) ||
    (cp >= 0x3041 && cp <= 0x33ff) ||
    (cp >= 0x3400 && cp <= 0x4dbf) ||
    (cp >= 0x4e00 && cp <= 0x9fff) ||
    (cp >= 0xa000 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x1f300 && cp <= 0x1f64f) ||
    (cp >= 0x1f900 && cp <= 0x1f9ff) ||
    (cp >= 0x20000 && cp <= 0x3fffd)
  )
}

function graphemeWidth(g: string): number {
  const cp = g.codePointAt(0) ?? 0
  if (cp < 0x20 || (cp >= 0x7f && cp < 0xa0)) return 0
  if (/\p{Extended_Pictographic}/u.test(g) && (g.includes('️') || cp >= 0x1f000)) return 2
  return isWide(cp) ? 2 : 1
}

export function cellWidth(text: string): number {
  let w = 0
  for (const { segment } of segmenter.segment(text)) w += graphemeWidth(segment)
  return w
}

/** Cut to at most `max` cells, ending with "..." when cut. */
export function fit(text: string, max: number): string {
  if (max <= 0) return ''
  if (cellWidth(text) <= max) return text
  const room = Math.max(0, max - 3)
  let out = ''
  let w = 0
  for (const { segment } of segmenter.segment(text)) {
    const gw = graphemeWidth(segment)
    if (w + gw > room) break
    out += segment
    w += gw
  }
  return max >= 3 ? `${out}...` : out
}

/** The longest prefix of whole graphemes that fits in `max` cells (at least one grapheme). */
export function takeCells(text: string, max: number): string {
  let out = ''
  let w = 0
  for (const { segment } of segmenter.segment(text)) {
    const gw = graphemeWidth(segment)
    if (w + gw > max && out) break
    out += segment
    w += gw
  }
  return out
}

export function pad(text: string, size: number, align: 'left' | 'right' = 'left'): string {
  const t = fit(text, size)
  const space = ' '.repeat(Math.max(0, size - cellWidth(t)))
  return align === 'right' ? space + t : t + space
}
