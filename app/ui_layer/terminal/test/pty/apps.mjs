// Walk the Agent Apps screens against a backend with at least one running
// app, read-only: the list, the app's own screens, its operations, its
// records, the chat pane, its settings, and Add Agent App's four tabs.
//   node test/pty/apps.mjs <port> <stateDir>
// No operation is run and nothing is installed, started or stopped.
import { startTui, KEYS } from './driver.mjs'

const tui = await startTui({ port: Number(process.argv[2] ?? 7946), cols: 110, rows: 34, stateDir: process.argv[3] })
const show = (label, lines = 16) => console.log(`===== ${label} =====\n${tui.screen().split('\n').slice(0, lines).join('\n')}`)
let failures = 0
const expect = async (text, label, timeout = 15000) => {
  try {
    await tui.waitFor(text, { timeout, all: false })
  } catch {
    failures++
    console.log(`!! ${label}: did not see ${text}`)
  }
}

try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(800)
  tui.type(KEYS.ctrl('x'))
  await tui.settle(150)
  tui.type('a')
  await expect('Agent Apps', 'apps list')
  await tui.settle(1500)
  show('Agent Apps')

  // The first app: its screen, generated from its operations.
  tui.type(KEYS.enter)
  await expect(/running|stopped|being built/, 'app screen')
  await tui.settle(3500)
  show('app screen', 24)
  tui.type(KEYS.tab)
  await tui.settle(800)
  show('next tab', 20)

  // Every operation, then the palette, closed without running anything.
  for (let i = 0; i < 6 && !/\[Ops\]/.test(tui.screen()); i++) {
    tui.type(KEYS.tab)
    await tui.settle(400)
  }
  show('ops tab', 20)
  tui.type(':')
  await tui.settle(500)
  show('op palette', 14)
  tui.type(KEYS.esc)
  await tui.settle(400)

  // Records: the first entity's list.
  tui.type('o')
  await tui.settle(600)
  show('records tab', 14)
  tui.type(KEYS.enter)
  await tui.settle(1500)
  show('records list', 20)
  tui.type(KEYS.esc)
  await tui.settle(400)

  // The chat with your AI agent, opened and closed.
  tui.type('c')
  await tui.settle(800)
  show('chat pane', 30)
  tui.type(KEYS.esc)
  await tui.settle(400)

  // Settings, the last tab.
  for (let i = 0; i < 8 && !/\[Settings\]/.test(tui.screen()); i++) {
    tui.type(KEYS.tab)
    await tui.settle(400)
  }
  await tui.settle(1500)
  show('settings tab', 30)

  // Back to the list (Esc leaves the app), then Add Agent App and its tabs.
  tui.type(KEYS.esc)
  await tui.settle(800)
  if (!tui.screen().includes('Agent Apps')) {
    failures++
    console.log('!! did not return to the apps list')
  }
  tui.type('a')
  await expect('Add Agent App', 'add screen')
  await tui.settle(3000)
  show('marketplace', 14)
  for (const tab of ['Build', 'Import', 'Connect']) {
    tui.type(']')
    await tui.settle(600)
    if (!tui.screen().includes(`[${tab}]`)) {
      // A focused text field takes ] as text: go through the tab bar instead.
      tui.type(KEYS.esc)
      await tui.settle(200)
      tui.type(KEYS.right)
      await tui.settle(200)
      tui.type(KEYS.enter)
      await tui.settle(400)
    }
    await expect(`[${tab}]`, `${tab} tab`, 4000)
    show(`${tab} tab`, 18)
  }
  console.log(failures ? `${failures} problem(s)` : 'agent apps walked')
} catch (err) {
  failures++
  console.log(String(err))
  console.log(tui.screen())
} finally {
  await tui.stop()
  process.exit(failures ? 1 : 0)
}
