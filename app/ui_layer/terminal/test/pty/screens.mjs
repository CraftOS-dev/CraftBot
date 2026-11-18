// Open every screen once and come back: node test/pty/screens.mjs <port> <stateDir>
// Prints each screen's first lines, and fails loudly if the client exits.
import { startTui, KEYS } from './driver.mjs'

const tui = await startTui({ port: Number(process.argv[2] ?? 7946), cols: 100, rows: 30, stateDir: process.argv[3] })
const SCREENS = [
  ['s', 'Sessions'],
  ['a', 'Agent Apps'],
  ['m', 'Memory'],
  ['w', 'Workspace'],
  ['d', 'Dashboard'],
  ['b', 'Browser'],
  [',', 'Settings'],
]
let failures = 0
try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(800)
  for (const [key, title] of SCREENS) {
    tui.type(KEYS.ctrl('x'))
    await tui.settle(150)
    tui.type(key)
    try {
      await tui.waitFor(title, { timeout: 8000, all: false })
    } catch {
      failures++
      console.log(`!! ${title} did not open`)
    }
    await tui.settle(1200)
    console.log(`===== ${title} =====\n${tui.screen().split('\n').slice(0, 7).join('\n')}`)
    tui.type(KEYS.esc)
    await tui.settle(300)
    tui.type(KEYS.esc)
    await tui.settle(900)
    if (!tui.screen().includes('Ask anything') && !tui.screen().includes('Tab to choose')) {
      failures++
      console.log(`!! did not return to the chat after ${title}`)
    }
  }
  tui.type(KEYS.ctrl('o'))
  await tui.waitFor('Transcript', { timeout: 8000, all: false }).catch(() => {
    failures++
    console.log('!! transcript did not open')
  })
  await tui.settle(800)
  console.log(`===== Transcript =====\n${tui.screen().split('\n').slice(0, 7).join('\n')}`)
  tui.type(KEYS.esc)
  await tui.settle(900)
  console.log(failures ? `${failures} problem(s)` : 'all screens opened and returned to the chat')
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(failures ? 1 : 0)
}
