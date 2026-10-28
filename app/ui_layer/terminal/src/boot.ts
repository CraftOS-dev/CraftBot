/**
 * First module the entry point imports, so it runs before anything else:
 * parse the command line, route console output to a log file (a stray
 * console line would corrupt the terminal frame), and install the browser
 * globals the shared store expects. ES modules evaluate their imports in
 * order, so every later import already sees all of this.
 */
import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { format } from 'node:util'
import { parseConfig, setConfig } from './config'
import { installBrowserGlobals } from './platform/globals'
import { blankEmoji } from './text/emoji'
import { consoleSafe } from './text/glyphSafe'
import { glyphMode } from './theme/theme'

const cfg = parseConfig(process.argv.slice(2), process.env)
setConfig(cfg)

const logDir = join(cfg.stateDir, 'logs')
const logFile = join(logDir, 'terminal.log')
try {
  mkdirSync(logDir, { recursive: true })
} catch {
  // Logging is best effort.
}

export function logLine(level: string, args: unknown[]): void {
  try {
    appendFileSync(logFile, `${new Date().toISOString()} ${level} ${format(...args)}\n`, 'utf8')
  } catch {
    // Never let logging break the UI.
  }
}

for (const level of ['log', 'info', 'warn', 'error', 'debug'] as const) {
  console[level] = (...args: unknown[]) => logLine(level.toUpperCase(), args)
}

installBrowserGlobals(cfg.stateDir, cfg.port)

// No emoji reach the terminal (src/text/emoji.ts): text is cleaned before it
// is laid out; this last pass blanks any that slipped through, keeping the
// width the renderer measured so nothing on screen moves. On a terminal
// without font fallback it also swaps characters the font cannot draw for
// look-alikes of the same width (src/text/glyphSafe.ts).
const safe = glyphMode() === 'modern' ? blankEmoji : (text: string) => consoleSafe(blankEmoji(text))
const writeOut = process.stdout.write.bind(process.stdout) as (...args: unknown[]) => boolean
process.stdout.write = ((chunk: unknown, ...rest: unknown[]) =>
  writeOut(typeof chunk === 'string' ? safe(chunk) : chunk, ...rest)) as typeof process.stdout.write
