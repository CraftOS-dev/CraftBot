/**
 * CraftBot terminal edition: entry point.
 *
 *   node dist/craftbot-tui.mjs --port 7926 [--owner] [--state-dir DIR] [--log FILE] [--plain]
 *
 * `./boot` must stay the first import: it parses the command line, sends
 * console output to a log file and installs the browser globals that the
 * shared store needs before any store module is evaluated.
 */
import './boot'
import { startClient } from './runtime/runtime'

startClient().then(
  () => process.exit(0),
  err => {
    console.error('terminal client failed:', err)
    process.stderr.write(`CraftBot terminal client failed: ${String((err as Error)?.stack ?? err)}\n`)
    process.exit(1)
  },
)
