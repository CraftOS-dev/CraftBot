// The chat shows one conversation at a time: a new chat, a switch back and a
// /clear each leave nothing of the previous conversation on screen or in the
// scrollback, and a new chat that becomes a real session prints once.
//   node test/pty/switch.mjs <port> <stateDir>
// Needs a backend past onboarding with something in Main (onboarding leaves
// "Onboarding workflow"). Sends one short message (calls the model).
import { startTui, KEYS } from './driver.mjs'

const port = Number(process.argv[2] ?? 7946)
const stateDir = process.argv[3]
const tui = await startTui({ port, cols: 100, rows: 30, stateDir })
const MAIN_MARK = 'Onboarding workflow'
const NEW_MARK = 'Reply with the single word pineapple'
let failures = 0
const check = (label, ok) => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`)
  if (!ok) failures++
}
const count = (text, needle) => text.split(needle).length - 1

try {
  await tui.waitFor('Ask anything', { timeout: 60000 })
  await tui.waitFor(MAIN_MARK, { timeout: 30000 })
  await tui.settle(800)
  check('Main shows its conversation', tui.all().includes(MAIN_MARK))

  // A new chat: Main's conversation leaves the screen and the scrollback.
  tui.type(KEYS.ctrl('n'))
  await tui.waitFor('── New chat', { timeout: 15000 })
  await tui.settle(800)
  check('new chat clears the previous conversation', !tui.all().includes(MAIN_MARK))

  // Its first message makes it a real session: still one divider.
  tui.type(NEW_MARK)
  await tui.settle(200)
  tui.type(KEYS.enter)
  await tui.waitFor('Working', { timeout: 20000, all: false })
  const deadline = Date.now() + 120000
  while (Date.now() < deadline && tui.screen().includes('Working')) await tui.settle(1000)
  await tui.settle(1500)
  const afterReply = tui.all()
  check('the new chat prints its divider once', count(afterReply, '── New chat') + count(afterReply, '── Untitled') <= 1)
  check('the message shows once', count(afterReply, NEW_MARK) === 1)
  console.log('\n--- new chat ---\n' + afterReply.split('\n').filter(l => l.trim()).slice(-14).join('\n'))

  // Back to Main: the new chat leaves.
  tui.type(KEYS.ctrl('x'))
  await tui.settle(150)
  tui.type('s')
  await tui.waitFor('Sessions', { all: false, timeout: 15000 })
  await tui.settle(600)
  tui.type('g')
  await tui.settle(200)
  tui.type(KEYS.enter)
  await tui.waitFor(MAIN_MARK, { timeout: 20000 })
  await tui.settle(1000)
  check('switching to Main clears the new chat', !tui.all().includes(NEW_MARK))

  // /clear in Main: the old conversation leaves, the notice stays.
  tui.type('/clear')
  await tui.settle(300)
  tui.type(KEYS.esc)
  await tui.settle(200)
  tui.type(KEYS.enter)
  await tui.waitFor('Conversation cleared', { timeout: 20000 })
  await tui.settle(1500)
  const cleared = tui.all()
  check('/clear removes the old conversation', !cleared.includes(MAIN_MARK))
  check('/clear leaves its notice', cleared.includes('Conversation cleared'))
  console.log('\n--- after /clear ---\n' + cleared.split('\n').filter(l => l.trim()).join('\n'))
} catch (err) {
  console.log(String(err))
  failures++
} finally {
  await tui.stop()
  console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed')
  process.exit(failures ? 1 : 0)
}
