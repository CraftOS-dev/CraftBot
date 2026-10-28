/**
 * Output the terminal's font can draw.
 *
 * Outside the modern glyph set (theme.ts), the terminal may have no font
 * fallback: a character its font lacks is a box with a question mark. The
 * client's own glyphs already stay inside the safe set; text from the agent,
 * the backend and the web can carry anything. This last pass on the output
 * swaps each symbol or punctuation mark outside text/consoleCharset.ts for a
 * drawable look-alike of the same width (✓ to √, ● to •, ╭ to ┌, ▸ to ►),
 * or blanks it when there is none. Letters, digits and CJK text are left
 * alone: they are content, and the console links fonts for CJK itself.
 */
import stringWidth from 'string-width'
import { CONSOLE_RANGES } from './consoleCharset'

function inRanges(cp: number): boolean {
  let lo = 0
  let hi = CONSOLE_RANGES.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const [a, b] = CONSOLE_RANGES[mid]
    if (cp < a) hi = mid - 1
    else if (cp > b) lo = mid + 1
    else return true
  }
  return false
}

/** Whether the classic console's stock fonts draw this character. */
export function consoleDrawable(ch: string): boolean {
  const cp = ch.codePointAt(0) ?? 0
  return cp < 0x7f || inRanges(cp)
}

const LOOKALIKES: Record<string, string> = {}
function alias(from: string, to: string): void {
  for (const ch of from) LOOKALIKES[ch] = to
}
alias('✓✔☑🗸', '√')
alias('✗✘✕✖☒⨯', '×')
alias('●⬤◉◍⚫', '•')
alias('◦◌◯⭘⚪', '○')
alias('◐◑◒◓', '•')
alias('▸▶▹▷⏵⯈', '►')
alias('◂◀◃◁⏴⯇', '◄')
alias('▾▿▽⏷', '▼')
alias('▴▵△⏶', '▲')
alias('❯❱⟩〉', '›')
alias('❮❰⟨〈', '‹')
alias('➜➝➞➔➤⇒⟶⇾⬅', '→')
alias('⬆⇧⇑', '↑')
alias('⬇⇩⇓', '↓')
alias('⇐⟵', '←')
alias('⎿↳↪╰┗┕┖╘', '└')
alias('↩↵⏎', '←')
alias('╭┏┍┎╒', '┌')
alias('╮┓┑┒╕', '┐')
alias('╯┛┙┚╛', '┘')
alias('━┄┅┈┉╌╍╴╶╸╺╼╾', '─')
alias('┃┆┇┊┋╎╏╵╷╹╻╽╿', '│')
alias('┣┝┞┟┠┡┢', '├')
alias('┫┥┦┧┨┩┪', '┤')
alias('┳┯┰┱┲┭┮', '┬')
alias('┻┷┸┹┺┵┶', '┴')
alias('╋┿╀╁╂╃╄╅╆╇╈╉╊┽┾', '┼')
alias('▁▂▃', '▄')
alias('▅▆▇▉▊▋', '█')
alias('▍▎▏', '▌')
alias('▔', '▀')
alias('■□▢▣▤▥▦▧▨▩▪▫◻◼◽◾⬛⬜', '■')
alias('◆◇◈❖⬥⬦', '◊')
alias('★☆✦✧✩✪✫✬✭✮✯✰✱✲✳✴✵✶✷✸✹✺✻✼✽✾✿❀❁❂❃❄❅❆❇❈❉❊❋∗⁎', '*')
alias('‣⁃⦁⸰', '•')
alias('⋯⋮', '…')
alias('−‐‑⁻', '-')
alias('⇥⭾', '→')
alias('⌘', '#')

function substitute(ch: string, cp: number): string {
  const w = stringWidth(ch)
  // Braille: blank cells stay blank, any dots read as a small dot.
  let out = cp >= 0x2800 && cp <= 0x28ff ? (cp === 0x2800 ? ' ' : '∙') : (LOOKALIKES[ch] ?? '')
  if (stringWidth(out) > w) out = ''
  return out + ' '.repeat(Math.max(0, w - stringWidth(out)))
}

/** Content the pass never touches: letters, marks, digits, currency, CJK and wide forms. */
const CONTENT = /^[\p{L}\p{M}\p{N}\p{Sc}]/u
const SPACE = /^\p{Zs}/u
function isCjk(cp: number): boolean {
  return (
    (cp >= 0x2e80 && cp <= 0x9fff) ||
    (cp >= 0xa960 && cp <= 0xa97f) ||
    (cp >= 0xac00 && cp <= 0xd7ff) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe10 && cp <= 0xfe1f) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xffef) ||
    cp >= 0x20000
  )
}

const NON_ASCII = /[^\u0000-~]/

/**
 * Swap undrawable symbols for look-alikes of the same width. Escape
 * sequences pass through untouched (an OSC 8 link keeps its target).
 */
export function consoleSafe(text: string): string {
  if (!NON_ASCII.test(text)) return text
  let out = ''
  let i = 0
  while (i < text.length) {
    const cp = text.codePointAt(i) ?? 0
    const ch = String.fromCodePoint(cp)
    // OSC (ESC ]) runs to BEL or ESC \.
    if (cp === 0x1b && text[i + 1] === ']') {
      let end = i + 2
      while (end < text.length && text[end] !== '\u0007' && !(text[end] === '\u001B' && text[end + 1] === '\\')) end++
      end = end >= text.length ? end : text[end] === '\u0007' ? end + 1 : end + 2
      out += text.slice(i, end)
      i = end
      continue
    }
    i += ch.length
    if (cp < 0x7f || inRanges(cp) || isCjk(cp) || CONTENT.test(ch)) {
      out += ch
      continue
    }
    // Combining marks and selectors fold into what they follow.
    if (cp === 0xfe0e || cp === 0xfe0f || cp === 0x200d || cp === 0x20e3) continue
    out += SPACE.test(ch) ? ' '.repeat(Math.max(1, stringWidth(ch))) : substitute(ch, cp)
  }
  return out
}
