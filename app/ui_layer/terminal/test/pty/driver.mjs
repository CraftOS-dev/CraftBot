// Drive the built terminal client inside a real pseudo-terminal (ConPTY on
// Windows) and read what a user would see through a headless xterm.
//
//   const tui = await startTui({ port: 7946, cols: 100, rows: 30 })
//   await tui.waitFor('Ask anything')
//   tui.type('hello\r')
//   console.log(tui.screen())
//   await tui.stop()
import pty from '@lydell/node-pty'
import xterm from '@xterm/headless'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const bundle = join(here, '..', '..', 'dist', 'craftbot-tui.mjs')

export const KEYS = {
  enter: '\r',
  esc: '\u001b',
  tab: '\t',
  backspace: '\u007f',
  up: '\u001b[A',
  down: '\u001b[B',
  right: '\u001b[C',
  left: '\u001b[D',
  ctrl: ch => String.fromCharCode(ch.toUpperCase().charCodeAt(0) - 64),
  paste: text => `\u001b[200~${text}\u001b[201~`,
}

export async function startTui({ port, cols = 100, rows = 30, stateDir, args = [], env = {}, command }) {
  const term = new xterm.Terminal({ cols, rows, allowProposedApi: true, scrollback: 2000 })
  // `command` runs something else in the terminal (e.g. run.py --tui).
  const [file, argv] = command ?? [process.execPath, [bundle, '--port', String(port), ...(stateDir ? ['--state-dir', stateDir] : []), ...args]]
  const proc = pty.spawn(file, argv, {
    name: 'xterm-256color',
    cols,
    rows,
    cwd: process.cwd(),
    // Glyphs follow the terminal; scripts pin a set (pass CRAFTBOT_GLYPHS to try another).
    env: { ...process.env, FORCE_COLOR: '0', CRAFTBOT_GLYPHS: 'modern', ...env },
  })
  let raw = ''
  let exited = null
  proc.onData(data => {
    raw += data
    term.write(data)
  })
  proc.onExit(e => {
    exited = e
  })

  const lines = (fromScrollback = false) => {
    const buf = term.buffer.active
    const out = []
    const start = fromScrollback ? 0 : buf.viewportY
    const end = fromScrollback ? buf.length : buf.viewportY + rows
    for (let i = start; i < end; i++) out.push(buf.getLine(i)?.translateToString(true) ?? '')
    return out
  }

  const api = {
    proc,
    term,
    raw: () => raw,
    exited: () => exited,
    /** The visible screen as text. */
    screen: () => lines(false).join('\n'),
    /** Everything: scrollback plus screen. */
    all: () => lines(true).join('\n'),
    type: text => proc.write(text),
    resize: (c, r) => {
      proc.resize(c, r)
      term.resize(c, r)
    },
    async waitFor(text, { timeout = 30000, all = true } = {}) {
      const deadline = Date.now() + timeout
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 100))
        const hay = all ? api.all() : api.screen()
        if (typeof text === 'string' ? hay.includes(text) : text.test(hay)) return true
        if (exited) throw new Error(`client exited (${JSON.stringify(exited)}) before showing ${text}\n${api.all()}`)
      }
      throw new Error(`timed out waiting for ${text}\n--- screen ---\n${api.screen()}`)
    },
    async settle(ms = 400) {
      await new Promise(r => setTimeout(r, ms))
    },
    async stop() {
      if (!exited) {
        try {
          proc.kill()
        } catch {
          // Already gone.
        }
      }
      await new Promise(r => setTimeout(r, 200))
    },
  }
  return api
}
