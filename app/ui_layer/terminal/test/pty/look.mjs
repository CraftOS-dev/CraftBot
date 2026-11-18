// Print what the main surfaces look like, for a human or an agent to inspect:
//   node test/pty/look.mjs <port> <stateDir> [modern|console|ascii] [cols] [rows]
// Needs a backend past onboarding. Opens the chat, the slash popup, the
// sessions, settings and keys screens, then returns to the chat.
import { startTui, KEYS } from './driver.mjs'

const port = Number(process.argv[2] ?? 7946)
const stateDir = process.argv[3]
const glyphs = process.argv[4] ?? 'modern'
const cols = Number(process.argv[5] ?? 100)
const rows = Number(process.argv[6] ?? 30)
const tui = await startTui({ port, cols, rows, stateDir, env: { CRAFTBOT_GLYPHS: glyphs } })
const show = label => console.log(`\n===== ${label} (${glyphs}) =====\n${tui.screen()}`)

async function screen(key, text, label) {
  tui.type(KEYS.ctrl('x'))
  await tui.settle(150)
  tui.type(key)
  await tui.waitFor(text, { all: false, timeout: 15000 })
  await tui.settle(800)
  show(label)
  tui.type(KEYS.esc)
  await tui.waitFor('Ask anything', { all: false, timeout: 15000 })
  await tui.settle(400)
}

try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(1500)
  show('chat')
  tui.type('/se')
  await tui.settle(600)
  show('slash popup')
  tui.type(KEYS.ctrl('c'))
  await tui.settle(300)
  await screen('s', 'Sessions', 'sessions')
  await screen(',', 'Settings', 'settings')
  tui.type('?')
  await tui.waitFor('Keys', { all: false, timeout: 15000 })
  await tui.settle(800)
  show('keys')
  tui.type(KEYS.esc)
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
