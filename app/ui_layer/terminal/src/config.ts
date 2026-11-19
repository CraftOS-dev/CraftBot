/**
 * Command-line options of the terminal client.
 *
 *   --port N         backend port (default 7926)
 *   --owner          this client owns the backend: quitting stops CraftBot
 *   --state-dir DIR  CraftBot's state directory (remembered UI state lives here)
 *   --log FILE       the backend's log file, shown when it fails to start
 *   --plain          numbered menus and labeled lines, never the alternate screen
 */
import { homedir } from 'node:os'
import { join } from 'node:path'

export interface ClientConfig {
  port: number
  owner: boolean
  stateDir: string
  logFile: string | null
  plain: boolean
}

function valueOf(argv: string[], flag: string): string | undefined {
  const index = argv.indexOf(flag)
  if (index !== -1 && index + 1 < argv.length) return argv[index + 1]
  const inline = argv.find(a => a.startsWith(`${flag}=`))
  return inline ? inline.slice(flag.length + 1) : undefined
}

export function parseConfig(argv: string[], env: NodeJS.ProcessEnv): ClientConfig {
  const port = Number(valueOf(argv, '--port') ?? env.BROWSER_PORT ?? 7926)
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`--port must be a TCP port, got ${valueOf(argv, '--port')}`)
  }
  const plain = argv.includes('--plain')
    || env.INK_SCREEN_READER === 'true'
    || env.TERM === 'dumb'
    || !process.stdout.isTTY
  return {
    port,
    owner: argv.includes('--owner'),
    stateDir: valueOf(argv, '--state-dir') ?? env.CRAFTBOT_HOME ?? join(homedir(), '.craftbot'),
    logFile: valueOf(argv, '--log') ?? null,
    plain,
  }
}

let current: ClientConfig | null = null

export function setConfig(config: ClientConfig): void {
  current = config
}

export function config(): ClientConfig {
  if (!current) throw new Error('client config read before it was parsed')
  return current
}
