// Build and run the chat pane harness (see chatPane.tsx).
//   node test/harness/run-chat-pane.mjs [width] [height] [modern|console] [app]
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { bundle } from '../../build.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, 'dist', 'chat-pane.mjs')
await bundle(join(here, 'chatPane.tsx'), out, { devBuild: true })
const [w = '60', h = '24', glyphs = 'modern', mode = ''] = process.argv.slice(2)
const state = mkdtempSync(join(tmpdir(), 'cb-chat-pane-'))
const res = spawnSync(process.execPath, [out, '--port', '1', '--state-dir', state], {
  env: { ...process.env, HARNESS_ARGS: [w, h, mode].join('|'), FORCE_COLOR: '0', CRAFTBOT_GLYPHS: glyphs },
  stdio: 'inherit',
})
rmSync(state, { recursive: true, force: true })
process.exit(res.status ?? 1)
