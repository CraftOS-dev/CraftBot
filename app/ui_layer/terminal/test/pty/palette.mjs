// Palette typing check: node test/pty/palette.mjs <port> <stateDir>
import { startTui, KEYS } from './driver.mjs'

const tui = await startTui({ port: Number(process.argv[2] ?? 7946), cols: 100, rows: 30, stateDir: process.argv[3] })
try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(800)
  tui.type(KEYS.ctrl('p'))
  await tui.waitFor('Command palette', { timeout: 5000 })
  await tui.settle(400)
  for (const ch of 'mem') {
    tui.type(ch)
    await tui.settle(150)
  }
  await tui.settle(400)
  console.log(tui.screen().split('\n').slice(0, 8).join('\n'))
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
