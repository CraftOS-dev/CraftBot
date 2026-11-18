/**
 * Copy text to the system clipboard from a terminal app.
 *
 * Windows: PowerShell Set-Clipboard (the text travels as base64 on stdin, so
 * the console code page cannot mangle it); macOS: pbcopy; Linux: wl-copy on
 * Wayland, xclip or xsel on X11. Over SSH, or when none of those works, the
 * text goes to the terminal itself as an OSC 52 sequence (the terminal puts
 * it on the clipboard of the machine the user sits at).
 */
import { spawn } from 'node:child_process'

export interface ClipboardCommand {
  command: string
  args: string[]
  /** How the text is written to the command's stdin. */
  input: 'utf8' | 'base64'
}

const POWERSHELL_SCRIPT =
  '$b=[Console]::In.ReadToEnd().Trim(); ' +
  'Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b)))'

/** The clipboard commands to try, in order (empty: use OSC 52). */
export function clipboardCommands(platform: NodeJS.Platform, env: NodeJS.ProcessEnv): ClipboardCommand[] {
  // Over SSH the local clipboard tools would copy on the remote machine.
  if (env.SSH_CONNECTION || env.SSH_TTY) return []
  if (platform === 'win32') {
    return [{ command: 'powershell.exe', args: ['-NoProfile', '-NonInteractive', '-Command', POWERSHELL_SCRIPT], input: 'base64' }]
  }
  if (platform === 'darwin') return [{ command: 'pbcopy', args: [], input: 'utf8' }]
  const out: ClipboardCommand[] = []
  if (env.WAYLAND_DISPLAY) out.push({ command: 'wl-copy', args: [], input: 'utf8' })
  if (env.DISPLAY) {
    out.push({ command: 'xclip', args: ['-selection', 'clipboard'], input: 'utf8' })
    out.push({ command: 'xsel', args: ['--clipboard', '--input'], input: 'utf8' })
  }
  return out
}

/** The OSC 52 "set clipboard" sequence, wrapped for tmux or screen when inside one. */
export function osc52Sequence(text: string, env: NodeJS.ProcessEnv): string {
  const osc = `\u001B]52;c;${Buffer.from(text, 'utf8').toString('base64')}\u0007`
  if (env.TMUX) return `\u001BPtmux;${osc.replace(/\u001B/g, '\u001B\u001B')}\u001B\\`
  if ((env.TERM ?? '').startsWith('screen')) return `\u001BP${osc}\u001B\\`
  return osc
}

const COMMAND_TIMEOUT_MS = 5000

function runCommand(cmd: ClipboardCommand, text: string): Promise<boolean> {
  return new Promise(resolve => {
    let settled = false
    const done = (ok: boolean) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(ok)
    }
    let child: ReturnType<typeof spawn>
    try {
      child = spawn(cmd.command, cmd.args, {
        stdio: ['pipe', 'ignore', 'ignore'],
        windowsHide: true,
        env: cmd.command === 'pbcopy' ? { ...process.env, LANG: process.env.LANG || 'en_US.UTF-8' } : process.env,
      })
    } catch {
      resolve(false)
      return
    }
    const timer = setTimeout(() => {
      child.kill()
      done(false)
    }, COMMAND_TIMEOUT_MS)
    child.on('error', () => done(false))
    child.on('close', code => done(code === 0))
    child.stdin?.on('error', () => done(false))
    child.stdin?.end(cmd.input === 'base64' ? Buffer.from(text, 'utf8').toString('base64') : text, 'utf8')
  })
}

/**
 * Put text on the clipboard. Resolves 'system' when a clipboard command took
 * it, 'terminal' when it was handed to the terminal through OSC 52 (which the
 * terminal may or may not honor).
 */
export async function copyToClipboard(
  text: string,
  platform: NodeJS.Platform = process.platform,
  env: NodeJS.ProcessEnv = process.env,
): Promise<'system' | 'terminal'> {
  for (const cmd of clipboardCommands(platform, env)) {
    if (await runCommand(cmd, text)) return 'system'
  }
  if (process.stdout.isTTY) process.stdout.write(osc52Sequence(text, env))
  return 'terminal'
}
