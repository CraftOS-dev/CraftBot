/**
 * Copy text to the user's clipboard from the terminal. The value always
 * travels on the child's stdin, never on a command line (secrets must not
 * show up in a process list), and is never logged.
 *
 * Order: over SSH the clipboard that matters is the local terminal's, so
 * OSC 52 goes first. Otherwise the OS tool: PowerShell Set-Clipboard on
 * Windows (and from WSL), pbcopy on macOS, wl-copy / xclip / xsel on Linux.
 * OSC 52 is the last resort wherever stdout is a terminal.
 */
import { spawn } from 'node:child_process'

export type ClipboardMethod =
  | { kind: 'command'; name: string; command: string; args: string[]; encode: 'utf8' | 'base64' }
  | { kind: 'osc52' }

// The text arrives base64-encoded so the console code page cannot mangle it.
const POWERSHELL_SCRIPT =
  '$b=[Console]::In.ReadToEnd();Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b.Trim())))'

function powershell(command: string): ClipboardMethod {
  return {
    kind: 'command',
    name: 'Set-Clipboard',
    command,
    args: ['-NoProfile', '-NonInteractive', '-Command', POWERSHELL_SCRIPT],
    encode: 'base64',
  }
}

/** The clipboard methods to try, in order, for this environment. */
export function clipboardPlan(env: NodeJS.ProcessEnv, platform: NodeJS.Platform, isTTY: boolean): ClipboardMethod[] {
  const plan: ClipboardMethod[] = []
  const ssh = !!(env.SSH_CONNECTION || env.SSH_CLIENT || env.SSH_TTY)
  if (ssh && isTTY) plan.push({ kind: 'osc52' })
  if (!ssh) {
    if (platform === 'win32') plan.push(powershell('powershell.exe'))
    else if (platform === 'darwin') plan.push({ kind: 'command', name: 'pbcopy', command: 'pbcopy', args: [], encode: 'utf8' })
    else {
      if (env.WSL_DISTRO_NAME) plan.push(powershell('powershell.exe'))
      if (env.WAYLAND_DISPLAY) plan.push({ kind: 'command', name: 'wl-copy', command: 'wl-copy', args: [], encode: 'utf8' })
      if (env.DISPLAY) {
        plan.push({ kind: 'command', name: 'xclip', command: 'xclip', args: ['-selection', 'clipboard'], encode: 'utf8' })
        plan.push({ kind: 'command', name: 'xsel', command: 'xsel', args: ['--clipboard', '--input'], encode: 'utf8' })
      }
    }
    if (isTTY) plan.push({ kind: 'osc52' })
  }
  return plan
}

/** The OSC 52 "set clipboard" sequence, wrapped for tmux when inside it. */
export function osc52Sequence(text: string, env: NodeJS.ProcessEnv): string {
  const body = `\u001B]52;c;${Buffer.from(text, 'utf8').toString('base64')}\u0007`
  if (env.TMUX) return `\u001BPtmux;${body.replace(/\u001B/g, '\u001B\u001B')}\u001B\\`
  if ((env.TERM ?? '').startsWith('screen')) return `\u001BP${body}\u001B\\`
  return body
}

function runCopy(method: Extract<ClipboardMethod, { kind: 'command' }>, text: string): Promise<boolean> {
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
      child = spawn(method.command, method.args, {
        stdio: ['pipe', 'ignore', 'ignore'],
        windowsHide: true,
        env: method.name === 'pbcopy' ? { ...process.env, LANG: process.env.LANG || 'en_US.UTF-8' } : process.env,
      })
    } catch {
      resolve(false)
      return
    }
    const timer = setTimeout(() => {
      child.kill()
      done(false)
    }, 8000)
    child.on('error', () => done(false))
    child.on('exit', code => done(code === 0))
    child.stdin?.on('error', () => done(false))
    child.stdin?.end(method.encode === 'base64' ? Buffer.from(text, 'utf8').toString('base64') : text)
  })
}

export interface CopyResult {
  ok: boolean
  /** Which method copied: a tool name, or 'osc52' (the terminal; unconfirmed). */
  via: string | null
}

/** Copy `text`, trying each method of the plan until one works. */
export async function copyToClipboard(text: string): Promise<CopyResult> {
  const plan = clipboardPlan(process.env, process.platform, !!process.stdout.isTTY)
  for (const method of plan) {
    if (method.kind === 'osc52') {
      process.stdout.write(osc52Sequence(text, process.env))
      return { ok: true, via: 'osc52' }
    }
    if (await runCopy(method, text)) return { ok: true, via: method.name }
  }
  return { ok: false, via: null }
}
