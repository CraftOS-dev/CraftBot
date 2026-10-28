// Keyboard walk with no model calls: popups, screens, and back to the chat.
//   node test/pty/keys.mjs <port> <stateDir>
import { startTui, KEYS } from './driver.mjs'

const port = Number(process.argv[2] ?? 7946)
const stateDir = process.argv[3]
const tui = await startTui({ port, cols: 100, rows: 30, stateDir })
const show = label => console.log(`\n===== ${label} =====\n${tui.screen()}`)
const step = async (keys, label, ms = 500) => {
  tui.type(keys)
  await tui.settle(ms)
  show(label)
}

try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(1000)
  await step('/', 'slash popup')
  await step(KEYS.esc + KEYS.backspace, 'popup closed, slash removed')
  await step('look at @pack', '@ path popup')
  await step(KEYS.ctrl('u'), 'line cleared')
  tui.type(KEYS.ctrl('x'))
  await tui.settle(150)
  await step('s', 'sessions screen', 900)
  await step(KEYS.esc, 'back to chat', 900)
  await step('?', 'help screen', 900)
  await step(KEYS.esc, 'back to chat again', 900)
  tui.type(KEYS.ctrl('p'))
  await tui.settle(600)
  await step('set', 'palette filtered', 600)
  await step(KEYS.esc, 'chat after palette', 900)
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
