// Build and run the Agent App screen harness (see appScreen.tsx).
//   node test/harness/run-app-screen.mjs <projectDir> <appPort> [width] [height]
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { bundle } from '../../build.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, 'dist', 'app-screen.mjs')
await bundle(join(here, 'appScreen.tsx'), out, { devBuild: true })
const [dir, port, w = '100', h = '30'] = process.argv.slice(2)
const state = mkdtempSync(join(tmpdir(), 'cb-harness-'))
const res = spawnSync(process.execPath, [out, '--port', '1', '--state-dir', state], {
  env: { ...process.env, HARNESS_ARGS: [dir, port, w, h].join('|'), FORCE_COLOR: '0' },
  stdio: 'inherit',
})
process.exit(res.status ?? 1)
