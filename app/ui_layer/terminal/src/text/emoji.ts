/**
 * The terminal shows no emoji. Many console fonts have no emoji glyphs and
 * draw a box with a question mark instead (the classic Windows console
 * among them), widths of emoji sequences differ between terminals, and
 * CraftBot's UI uses plain glyphs only. Backend and agent text can still
 * carry emoji (a system notice such as "⚙️ Memory processing workflow"), so
 * text is cleaned before it is laid out, and a last pass on the output
 * blanks anything that slipped through without shifting the layout.
 *
 * An emoji here is a grapheme drawn as a picture: emoji presentation by
 * default, or forced by the U+FE0F selector, a flag, or a pictographic
 * symbol (a lone ⚙, ☀, ⚠ or ✈ is still a picture). Text marks stay: ©, ™,
 * arrows, check marks (✓ ✔ ✗), stars used for ratings, and the client's own
 * glyphs. A keycap ("1️⃣") keeps its digit.
 */
import stringWidth from 'string-width'

const graphemes = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
const PICTURE = /\p{Emoji_Presentation}|️|\p{Regional_Indicator}/u
const PICTOGRAPHIC = /^\p{Extended_Pictographic}/u
/** Cheap check before segmenting a whole frame. */
const MAY_CONTAIN = /[←-⯿\u{1F000}-\u{1FFFF}️⃣]|\p{Emoji_Presentation}/u

/** Pictographic symbols that read as text marks, not pictures. */
const TEXT_MARKS: readonly (readonly [number, number])[] = [
  [0x2194, 0x2199], // ↔ ↕ ↖ ↗ ↘ ↙
  [0x21a9, 0x21aa], // ↩ ↪
  [0x25aa, 0x25ab], // ▪ ▫
  [0x25b6, 0x25b6], // ▶
  [0x25c0, 0x25c0], // ◀
  [0x25fb, 0x25fe], // ◻ ◼ ◽ ◾
  [0x2605, 0x2606], // ★ ☆
  [0x2713, 0x2718], // ✓ ✔ ✕ ✖ ✗ ✘
  [0x2b05, 0x2b07], // ⬅ ⬆ ⬇
]

function keycapBase(g: string): string | null {
  return g.includes('⃣') ? g.replace(/[️⃣]/g, '') : null
}

function isPicture(segment: string): boolean {
  if (PICTURE.test(segment)) return true
  if (!PICTOGRAPHIC.test(segment)) return false
  const cp = segment.codePointAt(0) ?? 0
  if (cp >= 0x1f000) return true
  if (cp < 0x2190 || cp > 0x2bff) return false
  return !TEXT_MARKS.some(([a, b]) => cp >= a && cp <= b)
}

export function isEmoji(grapheme: string): boolean {
  return keycapBase(grapheme) === null && isPicture(grapheme)
}

/**
 * Remove emoji from text, with the space that separated it, so
 * "⚙️ Memory processing" reads "Memory processing".
 */
export function stripEmoji(text: string): string {
  if (!MAY_CONTAIN.test(text)) return text
  let out = ''
  let dropSpace = false
  for (const { segment } of graphemes.segment(text)) {
    const base = keycapBase(segment)
    if (base !== null) {
      out += base
      dropSpace = false
      continue
    }
    if (isPicture(segment)) {
      // At the start of a line or after a space, the space after it goes too.
      dropSpace = out === '' || out.endsWith(' ') || out.endsWith('\n')
      continue
    }
    if (dropSpace && segment === ' ') {
      dropSpace = false
      continue
    }
    dropSpace = false
    out += segment
  }
  return out
}

/**
 * Replace emoji with spaces of the same width (the width the renderer
 * measured), for text that is already laid out: nothing moves.
 */
export function blankEmoji(text: string): string {
  if (!MAY_CONTAIN.test(text)) return text
  let out = ''
  for (const { segment } of graphemes.segment(text)) {
    const base = keycapBase(segment)
    if (base !== null) out += base + ' '.repeat(Math.max(0, stringWidth(segment) - stringWidth(base)))
    else out += isPicture(segment) ? ' '.repeat(stringWidth(segment)) : segment
  }
  return out
}
