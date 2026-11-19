// Chat layout at small sizes: node test/pty/narrow.mjs <port> <stateDir> [cols] [rows]
import { startTui } from './driver.mjs'

const [port, stateDir, cols = '80', rows = '24'] = process.argv.slice(2)
const tui = await startTui({ port: Number(port), cols: Number(cols), rows: Number(rows), stateDir })
try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.settle(1200)
  console.log(`===== ${cols}x${rows} =====\n${tui.screen()}`)
  tui.resize(60, 20)
  await tui.settle(1200)
  console.log(`===== resized to 60x20 =====\n${tui.screen()}`)
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
