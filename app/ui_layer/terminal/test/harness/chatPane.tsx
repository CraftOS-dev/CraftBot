// Render the chat pane of an Agent App screen with a seeded conversation and
// print the frames: node test/harness/run-chat-pane.mjs [width] [height] [glyphs] [app]
// With "app" the whole Agent App screen renders (a stand-in project with no
// folder) and the pane opens with c. The client store points at a closed
// port, so nothing reaches any backend; no key sends anything.
import '../../src/boot'
import { useRef } from 'react'
import { PassThrough, Writable } from 'node:stream'
import { Provider } from 'react-redux'
import { render } from 'ink'
import { store } from '../../src/state/store'
import { prependMany } from '../../../browser/frontend/src/store/slices/messagesSlice'
import { addOrUpdate } from '../../../browser/frontend/src/store/slices/activitySlice'
import { setSessionRunState } from '../../../browser/frontend/src/store/slices/agentSlice'
import { setProjects } from '../../../browser/frontend/src/store/slices/agentAppSlice'
import { ChatPane, type ChatPaneKeys } from '../../src/chat/ChatPane'
import { ScreenContext } from '../../src/screens/context'
import { FRAME_SIDES } from '../../src/ui/Frame'
import { AppScreen } from '../../src/screens/apps/AppScreen'
import type { ActionItem, AgentAppProject, ChatMessage } from '../../../browser/frontend/src/types'

const [w, h, mode] = (process.env.HARNESS_ARGS ?? '').split('|')
const columns = Number(w || 60)
const rows = Number(h || 24)
const session = 'app-session'
const now = Date.now()
const at = (secondsAgo: number) => Math.floor(now / 1000) - secondsAgo

const msg = (id: string, style: ChatMessage['style'], content: string, ago: number, extra: Partial<ChatMessage> = {}): ChatMessage =>
  ({ messageId: id, sessionId: session, sender: style === 'user' ? 'You' : 'CraftBot', style, content, timestamp: at(ago), ...extra }) as ChatMessage
const act = (id: string, name: string, status: ActionItem['status'], ago: number, took: number, input: object, extra: Partial<ActionItem> = {}): ActionItem =>
  ({ id, name, status, itemType: 'action', sessionId: session, createdAt: (at(ago)) * 1000, completedAt: status === 'running' ? undefined : at(ago) * 1000 + took, input: JSON.stringify(input), ...extra }) as ActionItem

store.dispatch(prependMany({
  sessionId: session,
  hasMore: false,
  messages: [
    msg('m1', 'system', "'Advance Life OS' fired trigger 'evening_review'", 300),
    msg('m2', 'agent', "Tham, today you verified Fukuoka's **¥121,800** booking. Tomorrow's candidates:\n\n- clarify CIMB cash\n- book the dentist\n\nCheck-out opens at 23:00 on Command.", 290),
    msg('m3', 'user', 'I DO NOT NEED to check my CIMB again, I already sent it.', 200),
    msg('m5', 'agent', "You're right, you already sent it. I removed the CIMB recheck from your plan.", 150),
    msg('m6', 'user', 'What is on my plan for tomorrow morning?', 20),
  ],
}))
for (const item of [
  act('a1', 'run_op', 'completed', 196, 900, { op: 'plan.get' }),
  act('a2', 'run_op', 'completed', 194, 1200, { op: 'plan.remove', id: 'cimb' }),
  act('a3', 'run_op', 'completed', 18, 700, { op: 'today.get' }),
  act('a4', 'run_op', 'running', 3, 0, { op: 'calendar.list', day: 'tomorrow' }),
]) store.dispatch(addOrUpdate(item))
store.dispatch(setSessionRunState({ sessionId: session, state: 'running' }))

let last = ''
const out = new Writable({
  write(chunk, _enc, cb) {
    // Frames only; the caret's escape sequences arrive as their own writes.
    const text = String(chunk).replace(/\u001B\[\?25[hl]|\u001B\[\d*;?\d*H|\u001B\[\d+[ABCDG]/g, '')
    if (text.trim()) last = text
    cb()
  },
})
Object.assign(out, { columns, rows, isTTY: false })
// A terminal-like input: the paste hook turns on raw mode.
const input = Object.assign(new PassThrough(), { isTTY: true, setRawMode: () => input, ref: () => input, unref: () => input })

const keys: { ref: { current: ChatPaneKeys | null } | null } = { ref: null }
const screenKeys: { fn: ((input: string, key: never) => boolean) | null } = { fn: null }
function Host() {
  const ref = useRef<ChatPaneKeys | null>(null)
  keys.ref = ref
  if (mode === 'app') {
    return (
      <ScreenContext.Provider value={{ setHandler: fn => { screenKeys.fn = fn as never }, columns: columns - FRAME_SIDES, rows: rows - 1, setTextFocus: () => {} }}>
        <AppScreen arg="harness" />
      </ScreenContext.Provider>
    )
  }
  return <ChatPane sessionId={session} columns={columns} rows={rows} focused keysRef={ref} placeholder="Ask your AI agent about this app" emptyText="No messages yet" />
}
if (mode === 'app') {
  store.dispatch(setProjects([
    { id: 'harness', name: 'Advance Life OS', description: '', status: 'running', port: 3115, sessionId: session, createdAt: 0 } as AgentAppProject,
  ]))
}
const app = render(
  <Provider store={store}>
    <Host />
  </Provider>,
  { stdout: out as unknown as NodeJS.WriteStream, stdin: input as unknown as NodeJS.ReadStream, debug: true, patchConsole: false, exitOnCtrlC: false },
)

const key = (over: Record<string, boolean> = {}) => ({ upArrow: false, downArrow: false, leftArrow: false, rightArrow: false, pageDown: false, pageUp: false, home: false, end: false, return: false, escape: false, ctrl: false, shift: false, tab: false, backspace: false, delete: false, meta: false, super: false, hyper: false, capsLock: false, numLock: false, ...over }) as never
const press = (input: string, over?: Record<string, boolean>) => (mode === 'app' ? screenKeys.fn?.(input, key(over)) : keys.ref?.current?.(input, key(over)))
const wait = (ms: number) => new Promise(r => setTimeout(r, ms))
const show = (label: string) => process.stdout.write(`\n===== ${label} =====\n${last}\n`)

await wait(600)
if (mode === 'app') {
  press('c')
  await wait(400)
}
show('working')
press('what about lunch')
await wait(200)
show('typing')
// The turn ends with a question.
store.dispatch(addOrUpdate(act('a4', 'run_op', 'completed', 3, 1500, { op: 'calendar.list', day: 'tomorrow' })))
store.dispatch(prependMany({ sessionId: session, hasMore: false, messages: [
  msg('m7', 'agent', 'Tomorrow morning: 09:15 dentist, 10:30 deep work. Should I move deep work to the afternoon?', 1, {
    isQuestion: true, options: [{ label: 'Move it', value: 'move' }, { label: 'Keep it', value: 'keep' }],
  }),
] }))
store.dispatch(setSessionRunState({ sessionId: session, state: 'idle' }))
await wait(400)
show('question')
press('', { tab: true })
await wait(200)
show('question focused')
press('', { pageUp: true })
await wait(200)
app.unmount()
process.exit(0)
