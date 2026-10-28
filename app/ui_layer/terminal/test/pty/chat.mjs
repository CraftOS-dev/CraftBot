// Live chat round trip against a running backend (uses the configured model).
//   node test/pty/chat.mjs <port> <stateDir> [message]
// Without a message it answers the pinned question with its first option.
import { startTui, KEYS } from './driver.mjs'

const port = Number(process.argv[2] ?? 7946)
const stateDir = process.argv[3]
const message = process.argv[4]
const tui = await startTui({ port, cols: 100, rows: 30, stateDir })
const show = label => console.log(`\n===== ${label} =====\n${tui.screen()}`)

try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(1200)
  show('start')
  if (message) {
    tui.type(message)
    await tui.settle(300)
    show('typed')
    tui.type(KEYS.enter)
  } else {
    tui.type(KEYS.tab)
    await tui.settle(300)
    show('question focused')
    tui.type(KEYS.enter)
  }
  await tui.waitFor('Working', { timeout: 15000, all: false })
  await tui.settle(2500)
  show('working')
  const deadline = Date.now() + 180000
  while (Date.now() < deadline && tui.screen().includes('Working')) await tui.settle(1000)
  await tui.settle(1500)
  show('done')
  console.log('\n===== scrollback tail =====\n' + tui.all().split('\n').filter(l => l.trim()).slice(-40).join('\n'))
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
