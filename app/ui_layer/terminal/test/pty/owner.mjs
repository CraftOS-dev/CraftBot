// The foreground terminal edition, end to end:
//   CRAFTBOT_HOME=<scratch home> node test/pty/owner.mjs <python> <repo> <port>
// run.py starts a hidden backend and the client in this terminal; Ctrl+C
// twice quits, which must stop the backend cleanly and free the port.
import { createConnection } from 'node:net'
import { join } from 'node:path'
import { startTui, KEYS } from './driver.mjs'

const [python, repo, port] = process.argv.slice(2)
const portFree = () =>
  new Promise(resolve => {
    const socket = createConnection({ port: Number(port), host: '127.0.0.1' })
    socket.once('connect', () => {
      socket.destroy()
      resolve(false)
    })
    socket.once('error', () => resolve(true))
  })

const tui = await startTui({
  cols: 100,
  rows: 30,
  command: [python, [join(repo, 'run.py'), '--tui', '--backend-port', port, '--no-conda']],
  env: { PYTHONIOENCODING: 'utf-8' },
})
const started = Date.now()
try {
  await tui.waitFor(/Set up CraftBot|Ask anything/, { timeout: 300000 })
  console.log(`client up after ${Math.round((Date.now() - started) / 1000)}s`)
  await tui.settle(1500)
  console.log(tui.screen().split('\n').slice(0, 6).join('\n'))
  tui.type(KEYS.ctrl('c')) // leaves the onboarding screen
  await tui.settle(1200)
  tui.type(KEYS.ctrl('c'))
  await tui.settle(200)
  tui.type(KEYS.ctrl('c'))
  const deadline = Date.now() + 90000
  while (!tui.exited() && Date.now() < deadline) await tui.settle(500)
  console.log('launcher exited:', JSON.stringify(tui.exited()))
  for (let i = 0; i < 20 && !(await portFree()); i++) await tui.settle(500)
  console.log('backend port free:', await portFree())
} catch (err) {
  console.log(String(err))
} finally {
  await tui.stop()
  process.exit(0)
}
