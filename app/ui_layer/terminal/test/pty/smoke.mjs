// Manual smoke run against a live backend: node test/pty/smoke.mjs <port> [stateDir]
// Prints the screen at each step so a human (or an agent) can inspect it.
import { startTui, KEYS } from './driver.mjs'

const port = Number(process.argv[2] ?? 7946)
const stateDir = process.argv[3]
const tui = await startTui({ port, cols: 100, rows: 30, stateDir })
const show = label => console.log(`\n===== ${label} =====\n${tui.screen()}`)
try {
  await tui.waitFor(/Set up CraftBot|Ask anything/, { timeout: 60000 })
  await tui.settle(800)
  show('first screen')
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
