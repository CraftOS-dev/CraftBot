// Render the Agent App screen for one project folder, read-only, and print
// the frames: node test/harness/run-app-screen.mjs <projectDir> <port> [width] [height]
// It never sends a key that runs an operation; it only reads (GET ops,
// describe, the live-changes feed). The client store points at a closed port,
// so nothing reaches any CraftBot backend.
import '../../src/boot'
import { Writable } from 'node:stream'
import { Provider } from 'react-redux'
import { render } from 'ink'
import { store } from '../../src/state/store'
import { setProjects } from '../../../browser/frontend/src/store/slices/agentAppSlice'
import { ScreenContext } from '../../src/screens/context'
import { FRAME_SIDES } from '../../src/ui/Frame'
import { AppScreen } from '../../src/screens/apps/AppScreen'
import type { AgentAppProject } from '../../../browser/frontend/src/types'

const [dir, port, w, h] = (process.env.HARNESS_ARGS ?? '').split('|')
const columns = Number(w || 100)
const rows = Number(h || 30)

store.dispatch(setProjects([
  { id: 'harness', name: 'Harness app', description: '', status: 'running', path: dir, port: Number(port), createdAt: 0 } as AgentAppProject,
]))

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
      <AppScreen arg="harness" />
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
