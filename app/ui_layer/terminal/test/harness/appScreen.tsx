// Render the Agent App screen for one running app's folder, read-only, and
// print the frames: node test/harness/run-app-screen.mjs <appDir> [width] [height]
// It never sends a key that runs an operation; it only reads (the app's
// read-only ops and records). The client store points at a closed port, so
// nothing reaches any CraftBot backend.
import '../../src/boot'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { Writable } from 'node:stream'
import { Provider } from 'react-redux'
import { render } from 'ink'
import { store } from '../../src/state/store'
import { frameworkAppKey, receiveFrameworkList } from '../../../browser/frontend/src/store/slices/agentAppSlice'
import { ScreenContext } from '../../src/screens/context'
import { FRAME_SIDES } from '../../src/ui/Frame'
import { AppScreen } from '../../src/screens/apps/AppScreen'
const [dir, w, h] = (process.env.HARNESS_ARGS ?? '').split('|')
const columns = Number(w || 100)
const rows = Number(h || 30)

// The app as the registry lists it: the manifest's id, name and port.
const manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8')) as { id: string; name: string; port?: number }
store.dispatch(receiveFrameworkList({
  status: 'success',
  data: { apps: [{ id: manifest.id, name: manifest.name, path: dir, status: 'running', port: manifest.port ?? 8090 }], connected: [] },
}))
const arg = frameworkAppKey(dir, manifest.id)

let last = ''
const out = new Writable({
  write(chunk, _enc, cb) {
    last = String(chunk)
    cb()
  },
})
Object.assign(out, { columns, rows, isTTY: false })

const handlers: { fn: ((input: string, key: never) => boolean) | null } = { fn: null }
const app = render(
  <Provider store={store}>
    <ScreenContext.Provider value={{ setHandler: fn => { handlers.fn = fn as never }, columns: columns - FRAME_SIDES, rows, setTextFocus: () => {} }}>
      <AppScreen arg={arg} />
    </ScreenContext.Provider>
  </Provider>,
  { stdout: out as unknown as NodeJS.WriteStream, debug: true, patchConsole: false, exitOnCtrlC: false },
)

const key = (over: Record<string, boolean> = {}) => ({ upArrow: false, downArrow: false, leftArrow: false, rightArrow: false, pageDown: false, pageUp: false, home: false, end: false, return: false, escape: false, ctrl: false, shift: false, tab: false, backspace: false, delete: false, meta: false, super: false, hyper: false, capsLock: false, numLock: false, ...over }) as never
const press = (input: string, over?: Record<string, boolean>) => handlers.fn?.(input, key(over))
const wait = (ms: number) => new Promise(r => setTimeout(r, ms))

const show = (label: string) => process.stdout.write(`\n===== ${label} =====\n${last}\n`)
await wait(2500)
show('home')
press('', { tab: true })
await wait(1500)
show('next screen (Tab)')
press('j')
await wait(300)
show('row selected (j)')
press(':')
await wait(300)
show('op palette (:)')
press('', { escape: true })
for (let i = 0; i < 40; i++) press('', { tab: true })
await wait(300)
app.unmount()
process.exit(0)
