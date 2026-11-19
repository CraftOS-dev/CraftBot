/**
 * Open a link or a file with the system's default app: `cmd /c start "" x`
 * on Windows, `open` on macOS, `xdg-open` on Linux. Detached, so closing
 * the terminal does not close the browser or image viewer.
 */
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export interface OpenCommand {
  command: string
  args: string[]
  /** Windows: pass the arguments as written (cmd's own quoting). */
  verbatim: boolean
}

/** The command that opens `target`; null when it cannot be passed safely. */
export function openCommand(target: string, platform: NodeJS.Platform): OpenCommand | null {
  // A quote or a control character could break out of the argument.
  if (!target || /["\u0000-\u001F]/.test(target)) return null
  if (platform === 'win32') {
    // `start` takes the first quoted argument as a window title, hence "".
    return { command: 'cmd.exe', args: ['/d', '/s', '/c', `"start "" "${target}""`], verbatim: true }
  }
  if (platform === 'darwin') return { command: 'open', args: [target], verbatim: false }
  return { command: 'xdg-open', args: [target], verbatim: false }
}

/** Open `target`; resolves false when there was nothing to run it with. */
export function openExternal(target: string): Promise<boolean> {
  const cmd = openCommand(target, process.platform)
  if (!cmd) return Promise.resolve(false)
  return new Promise(resolve => {
    try {
      const child = spawn(cmd.command, cmd.args, {
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
        windowsVerbatimArguments: cmd.verbatim,
      })
      child.on('error', () => resolve(false))
      child.on('spawn', () => {
        child.unref()
        resolve(true)
      })
    } catch {
      resolve(false)
    }
  })
}

/** Write bytes to a fresh temporary file and return its path. */
export function writeTempFile(name: string, bytes: Buffer): string {
  const dir = mkdtempSync(join(tmpdir(), 'craftbot-'))
  const file = join(dir, name)
  writeFileSync(file, bytes)
  return file
}
