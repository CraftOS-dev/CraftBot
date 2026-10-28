/**
 * Colors and glyphs of the terminal client.
 *
 * Palette roles (accent, text, muted, dim, border, status colors) follow the
 * browser's tokens: neutral grays, with the brand orange for the agent's
 * marker, the prompt, focus and the active row. Meaning never travels in
 * color alone: every state also has a glyph or a word. Color depth follows
 * the terminal (truecolor, 256, 16, none); NO_COLOR is honored.
 *
 * Glyphs never include emoji, and never a character the terminal's font may
 * lack: a terminal without font fallback draws that as a box with a
 * question mark. Three sets:
 *   modern   terminals with font fallback (Windows Terminal, VS Code, macOS,
 *            Linux): rounded corners, braille spinner, check marks.
 *   console  the classic Windows console: only characters its stock fonts
 *            (Lucida Console, Consolas) draw, see text/consoleCharset.ts.
 *   ascii    plain ASCII, for fonts that draw box drawing double-width.
 * CRAFTBOT_GLYPHS=modern|console|ascii overrides the choice (CRAFTBOT_ASCII=1
 * still means ascii).
 */
import chalk, { Chalk, type ChalkInstance } from 'chalk'
import { terminalCaps } from '../caps/terminal'

export const BRAND = '#FF4F18'

const noColor = 'NO_COLOR' in process.env && process.env.NO_COLOR !== ''

export const paint: ChalkInstance = noColor ? new Chalk({ level: 0 }) : chalk

const PALETTE = {
  accent: BRAND,
  muted: '#8C8C8C',
  dim: '#666666',
  border: '#5A5A5A',
  success: '#5FB96B',
  error: '#F0605A',
  warn: '#E5A93B',
  info: '#5AA2E0',
  code: '#D8A657',
}

/** Ink `color` props: undefined disables color entirely. */
export const ink = {
  brand: noColor ? undefined : PALETTE.accent,
  focus: noColor ? undefined : PALETTE.accent,
  muted: noColor ? undefined : PALETTE.muted,
  dim: noColor ? undefined : PALETTE.dim,
  border: noColor ? undefined : PALETTE.border,
  error: noColor ? undefined : PALETTE.error,
  success: noColor ? undefined : PALETTE.success,
  warn: noColor ? undefined : PALETTE.warn,
  info: noColor ? undefined : PALETTE.info,
} as const

/**
 * The selection chip: the one painted background, on the selected row's text
 * only. Light text on a dark warm tint reads on dark and light terminals
 * alike; with 16 colors or fewer there is no chip and the pointer and bold
 * carry the selection.
 */
const chipOk = !noColor && chalk.level >= 2
export const chip = {
  bg: chipOk ? '#3E1F15' : undefined,
  fg: chipOk ? '#F2F2F2' : undefined,
} as const

export const tone = {
  brand: (s: string) => paint.hex(PALETTE.accent)(s),
  brandBold: (s: string) => paint.bold.hex(PALETTE.accent)(s),
  muted: (s: string) => paint.hex(PALETTE.muted)(s),
  dim: (s: string) => paint.hex(PALETTE.dim)(s),
  border: (s: string) => paint.hex(PALETTE.border)(s),
  bold: (s: string) => paint.bold(s),
  italic: (s: string) => paint.italic(s),
  error: (s: string) => paint.hex(PALETTE.error)(s),
  success: (s: string) => paint.hex(PALETTE.success)(s),
  warn: (s: string) => paint.hex(PALETTE.warn)(s),
  info: (s: string) => paint.hex(PALETTE.info)(s),
  code: (s: string) => paint.hex(PALETTE.code)(s),
  link: (s: string) => paint.underline.hex(PALETTE.info)(s),
  heading: (s: string) => paint.bold(s),
}

export interface GlyphSet {
  /** Marks an agent message and a finished group of actions. */
  agent: string
  /** Marks a system notice. */
  notice: string
  running: string
  done: string
  failed: string
  /** An action or task stopped before it finished. */
  stopped: string
  pending: string
  warn: string
  busy: string
  unread: string
  idle: string
  /** A collapsed group (actions, a folder). */
  chunk: string
  expanded: string
  /** The composer's prompt and the user's messages. */
  prompt: string
  bullet: string
  /** Separator between short facts on one line. */
  sep: string
  ellipsis: string
  rule: string
  vbar: string
  /** Tree connectors under a row: a middle child, the last child, a continuing line. */
  tee: string
  last: string
  pipe: string
  artifact: string
  /** The selected row of a list. */
  pointer: string
  checked: string
  unchecked: string
  radioOn: string
  radioOff: string
  meterFull: string
  meterEmpty: string
  scrollThumb: string
  /** Sparkline marks, lowest first. */
  spark: string[]
  /** Partial bar tops, one to seven eighths (index 0 unused). */
  eighths: string[]
  boxTopLeft: string
  boxTopRight: string
  boxBottomLeft: string
  boxBottomRight: string
  boxH: string
  boxV: string
  tableTop: [string, string, string]
  tableMid: [string, string, string]
  tableBottom: [string, string, string]
}

export type GlyphMode = 'modern' | 'console' | 'ascii'

const MODERN: GlyphSet = {
  agent: '●',
  notice: '·',
  running: '◐',
  done: '✓',
  failed: '✗',
  stopped: '■',
  pending: '○',
  warn: '▲',
  busy: '◐',
  unread: '●',
  idle: '○',
  chunk: '▸',
  expanded: '▾',
  prompt: '❯',
  bullet: '•',
  sep: '·',
  ellipsis: '…',
  rule: '─',
  vbar: '│',
  tee: '├',
  last: '└',
  pipe: '│',
  artifact: '▣',
  pointer: '❯',
  checked: '■',
  unchecked: '□',
  radioOn: '●',
  radioOff: '○',
  meterFull: '█',
  meterEmpty: '░',
  scrollThumb: '█',
  spark: ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'],
  eighths: ['', '▁', '▂', '▃', '▄', '▅', '▆', '▇'],
  boxTopLeft: '╭',
  boxTopRight: '╮',
  boxBottomLeft: '╰',
  boxBottomRight: '╯',
  boxH: '─',
  boxV: '│',
  tableTop: ['┌', '┬', '┐'],
  tableMid: ['├', '┼', '┤'],
  tableBottom: ['└', '┴', '┘'],
}

/** Every character here is in text/consoleCharset.ts (a unit test holds it to that). */
const CONSOLE: GlyphSet = {
  agent: '•',
  notice: '·',
  running: '►',
  done: '√',
  failed: '×',
  stopped: '■',
  pending: '○',
  warn: '▲',
  busy: '►',
  unread: '•',
  idle: '○',
  chunk: '►',
  expanded: '▼',
  prompt: '>',
  bullet: '•',
  sep: '·',
  ellipsis: '…',
  rule: '─',
  vbar: '│',
  tee: '├',
  last: '└',
  pipe: '│',
  artifact: '■',
  pointer: '>',
  checked: '■',
  unchecked: '○',
  radioOn: '•',
  radioOff: '○',
  meterFull: '█',
  meterEmpty: '░',
  scrollThumb: '█',
  spark: ['_', '_', '▄', '▄', '▄', '█', '█', '█'],
  eighths: ['', '▄', '▄', '▄', '▄', '▄', '█', '█'],
  boxTopLeft: '┌',
  boxTopRight: '┐',
  boxBottomLeft: '└',
  boxBottomRight: '┘',
  boxH: '─',
  boxV: '│',
  tableTop: ['┌', '┬', '┐'],
  tableMid: ['├', '┼', '┤'],
  tableBottom: ['└', '┴', '┘'],
}

const ASCII: GlyphSet = {
  agent: '*',
  notice: '-',
  running: '*',
  done: '+',
  failed: 'x',
  stopped: '#',
  pending: 'o',
  warn: '!',
  busy: '*',
  unread: '#',
  idle: 'o',
  chunk: '>',
  expanded: 'v',
  prompt: '>',
  bullet: '-',
  sep: '-',
  ellipsis: '...',
  rule: '-',
  vbar: '|',
  tee: '|',
  last: '`',
  pipe: '|',
  artifact: '#',
  pointer: '>',
  checked: '[x]',
  unchecked: '[ ]',
  radioOn: '*',
  radioOff: 'o',
  meterFull: '#',
  meterEmpty: '.',
  scrollThumb: '#',
  spark: ['_', '.', ',', ':', '-', '=', '+', '#'],
  eighths: ['', '.', '.', '.', '#', '#', '#', '#'],
  boxTopLeft: '+',
  boxTopRight: '+',
  boxBottomLeft: '+',
  boxBottomRight: '+',
  boxH: '-',
  boxV: '|',
  tableTop: ['+', '+', '+'],
  tableMid: ['+', '+', '+'],
  tableBottom: ['+', '+', '+'],
}

const SETS: Record<GlyphMode, GlyphSet> = { modern: MODERN, console: CONSOLE, ascii: ASCII }

function initialMode(env: NodeJS.ProcessEnv): GlyphMode {
  const forced = env.CRAFTBOT_GLYPHS
  if (forced === 'modern' || forced === 'console' || forced === 'ascii') return forced
  if (env.CRAFTBOT_ASCII === '1') return 'ascii'
  return terminalCaps().fontFallback ? 'modern' : 'console'
}

let mode: GlyphMode = initialMode(process.env)

export function glyphMode(): GlyphMode {
  return mode
}

export function setGlyphMode(next: GlyphMode): void {
  mode = next
}

export function glyphs(): GlyphSet {
  return SETS[mode]
}

/** The set for a mode, for tests. */
export function glyphSetFor(which: GlyphMode): GlyphSet {
  return SETS[which]
}

/** Marks for the Agent App view engine (agent-app/view render options). */
export function viewMarks(): { pointer: string; bullet: string; spark: string[]; barFull: string; barEmpty: string } {
  const g = SETS[mode]
  return { pointer: g.pointer, bullet: g.bullet, spark: g.spark, barFull: g.meterFull, barEmpty: g.meterEmpty }
}

/** Ink border style matching the glyph set. */
export function borderStyle(): 'round' | 'single' | 'classic' {
  return mode === 'modern' ? 'round' : mode === 'console' ? 'single' : 'classic'
}

/** Spinner frames for "working": braille dots, a shade pulse on the console, or a bar. */
export function spinnerFrames(): string[] {
  if (mode === 'modern') return ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
  if (mode === 'console') return ['░', '▒', '▓', '█', '▓', '▒']
  return ['|', '/', '-', '\\']
}
