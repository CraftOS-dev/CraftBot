/**
 * Open text in the user's editor ($VISUAL, then $EDITOR; Notepad on
 * Windows and vi elsewhere when neither is set). The text goes to a
 * Markdown file in the temp folder, which is left in place so a GUI editor
 * that returns at once still finds it. The terminal is handed to the editor
 * for as long as it runs (Ink's suspendTerminal) and taken back after.
 */
import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export type Suspend = (run: () => Promise<void>) => Promise<void>

/** The editor command line to run (may carry arguments, e.g. "code --wait"). */
export function editorCommand(env: NodeJS.ProcessEnv, platform: NodeJS.Platform): string {
  const chosen = (env.VISUAL || env.EDITOR || '').trim()
  if (chosen) return chosen
  return platform === 'win32' ? 'notepad' : 'vi'
}

/** The command line for one file, the path quoted for the platform's shell. */
export function editorCommandLine(editor: string, path: string, platform: NodeJS.Platform): string {
  const quoted = platform === 'win32' ? `"${path.replace(/"/g, '')}"` : `'${path.replace(/'/g, `'\\''`)}'`
  return `${editor} ${quoted}`
}

/** A temp file name: craftbot-<name>-<time>.<extension> (Markdown unless told otherwise). */
export function editorFilePath(name: string, now = Date.now(), dir = tmpdir(), extension = 'md'): string {
  return join(dir, `craftbot-${name}-${now}.${extension}`)
}

function runEditor(commandLine: string): Promise<number | null> {
  return new Promise((resolve, reject) => {
    const child = spawn(commandLine, { shell: true, stdio: 'inherit' })
    child.on('error', reject)
    child.on('exit', code => resolve(code))
  })
}

interface ReadHandle {
  reading?: boolean
  readStop?: () => number
  readStart?: () => number
}

/**
 * Stop reading the console before the terminal is handed over; returns the
 * function that starts reading again once Ink has taken it back.
 *
 * Ink's suspend turns raw mode off but leaves the console read running, and
 * turning raw mode off during a read restarts it as a line read. On Windows
 * that line read blocks inside the console, and stdin then waits forever on
 * a read that never returns: no key arrives after the editor exits.
 * Elsewhere the running read would take the editor's keystrokes. So the read
 * stops here, while raw mode is still on (where stopping is clean), and
 * starts again in raw mode after the resume. The stream itself still counts
 * that read as pending, so nothing else would restart it.
 */
function holdConsoleRead(): () => void {
  const handle = (process.stdin as unknown as { _handle?: ReadHandle })._handle
  if (!process.stdin.isTTY || !handle?.readStop || !handle.readStart) return () => {}
  handle.readStop()
  handle.reading = false
  return () => {
    if (handle.reading) return
    handle.reading = true
    handle.readStart?.()
  }
}

/**
 * Write `text` to a temp file and open it in the editor while the terminal
 * is suspended. Resolves the file path and the editor that ran; rejects when
 * the editor could not be started or exited with an error.
 */
export async function openInEditor(
  text: string,
  name: string,
  suspend: Suspend,
  extension = 'md',
): Promise<{ path: string; editor: string }> {
  // Leave Ink's key dispatch first: after a key handler returns it reads
  // stdin once more, which must happen while raw mode is still on.
  await new Promise(resolve => setTimeout(resolve, 0))
  const path = editorFilePath(name, Date.now(), tmpdir(), extension)
  writeFileSync(path, text, 'utf8')
  const editor = editorCommand(process.env, process.platform)
  let failure: unknown = null
  const readAgain = holdConsoleRead()
  try {
    await suspend(async () => {
      try {
        const code = await runEditor(editorCommandLine(editor, path, process.platform))
        if (code !== 0 && code !== null) failure = new Error(`${editor} exited with code ${code}`)
      } catch (err) {
        failure = err
      }
    })
  } finally {
    readAgain()
  }
  if (failure) throw failure
  return { path, editor }
}
