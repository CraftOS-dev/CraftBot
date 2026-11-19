// Build and run the Agent App screen harness (see appScreen.tsx).
//   node test/harness/run-app-screen.mjs <appDir> [width] [height]
// The app must be running. The framework package is the one CraftBot runs
// (CRAFTBOT_AGENT_APP_PACKAGE, else the repo's runtime/agent-app/<sha>).
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { bundle } from '../../build.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, 'dist', 'app-screen.mjs')
await bundle(join(here, 'appScreen.tsx'), out, { devBuild: true })
const [dir, w = '100', h = '30'] = process.argv.slice(2)
const repo = join(here, '..', '..', '..', '..', '..')
const pin = JSON.parse(readFileSync(join(repo, 'app', 'vendor', 'agent-app', 'source.json'), 'utf8'))
const pkg = process.env.CRAFTBOT_AGENT_APP_PACKAGE || join(repo, 'runtime', 'agent-app', pin.sha256)
const state = mkdtempSync(join(tmpdir(), 'cb-harness-'))
const res = spawnSync(process.execPath, [out, '--port', '1', '--state-dir', state], {
  env: { ...process.env, CRAFTBOT_AGENT_APP_PACKAGE: pkg, HARNESS_ARGS: [dir, w, h].join('|'), FORCE_COLOR: '0' },
  stdio: 'inherit',
})
process.exit(res.status ?? 1)
