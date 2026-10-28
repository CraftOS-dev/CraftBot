// Walk first-run onboarding against a fresh backend, printing each screen.
//   CB_TEST_API_KEY=... node test/pty/onboard.mjs <port> <stateDir> <providerLabel>
// The key comes from the environment and is typed into the masked field; it
// is never printed.
import { startTui, KEYS } from './driver.mjs'

const port = Number(process.argv[2] ?? 7946)
const stateDir = process.argv[3]
const providerLabel = process.argv[4] ?? 'OpenAI'
const apiKey = process.env.CB_TEST_API_KEY ?? ''
const tui = await startTui({ port, cols: 100, rows: 30, stateDir })
const show = label => console.log(`\n===== ${label} =====\n${tui.screen().replaceAll(apiKey || '\u0000', '<key>')}`)

try {
  await tui.waitFor('Set up CraftBot', { timeout: 60000 })
  await tui.settle(500)
  show('intro')
  tui.type(KEYS.enter)
  await tui.waitFor('2/5')
  await tui.settle(500)
  show('provider')
  // Move down until the provider is selected.
  for (let i = 0; i < 15; i++) {
    const selected = tui.screen().split('\n').find(l => /^[│|]?\s*[❯›>] /.test(l))
    if (selected && selected.includes(providerLabel)) break
    tui.type(KEYS.down)
    await tui.settle(150)
  }
  show('provider selected')
  tui.type(KEYS.enter)
  await tui.waitFor('3/5')
  await tui.settle(400)
  show('api key')
  tui.type(apiKey)
  await tui.settle(300)
  show('api key typed (masked)')
  tui.type(KEYS.enter)
  await tui.waitFor('4/5', { timeout: 60000 })
  await tui.settle(500)
  show('profile')
  for (let i = 0; i < 12 && !tui.screen().includes('5/5'); i++) {
    tui.type(KEYS.enter)
    await tui.settle(400)
  }
  await tui.waitFor('5/5', { timeout: 30000 })
  show('agent name')
  tui.type('Aria')
  tui.type(KEYS.enter)
  await tui.waitFor(/Ask anything/, { timeout: 60000 })
  await tui.settle(1500)
  show('chat after onboarding')
} catch (err) {
  console.log(String(err).replaceAll(apiKey || '\u0000', '<key>'))
} finally {
  await tui.stop()
  process.exit(0)
}
