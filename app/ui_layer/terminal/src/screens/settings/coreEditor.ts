/**
 * Long text is edited in the user's own editor through the shared helper
 * (screens/viewEditor.ts: $VISUAL, then $EDITOR, else Notepad on Windows and
 * vi elsewhere, with the terminal handed over while it runs). This module
 * reads the edited file back with the original line endings, and opens links
 * in the system browser.
 */
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { editorCommand, openInEditor, type Suspend } from '../viewEditor'
import { normalizeEdited, openUrlCommand } from './coreLogic'

export type { Suspend }

export interface EditResult {
  /** The edited text, or null when the editor could not run or failed. */
  text: string | null
  error?: string
  editor: string
}

/** The editor command that will run, for messages. */
export function currentEditor(): string {
  return editorCommand(process.env, process.platform)
}

/**
 * Edit `text` in the external editor; `filename` names the temp file
 * (e.g. USER.md becomes craftbot-USER-<time>.md).
 */
export async function editInEditor(suspend: Suspend, text: string, filename: string): Promise<EditResult> {
  const name = filename.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_-]/g, '_') || 'text'
  try {
    const { path, editor } = await openInEditor(text, name, suspend)
    return { text: normalizeEdited(text, readFileSync(path, 'utf8')), editor }
  } catch (err) {
    return { text: null, error: err instanceof Error ? err.message : String(err), editor: currentEditor() }
  }
}

/** Open `url` in the system's default browser. Resolves false when it could not start. */
export function openInBrowser(url: string): Promise<boolean> {
  if (!/^https?:\/\//i.test(url)) return Promise.resolve(false)
  const { command, args, shell } = openUrlCommand(url, process.platform)
  return new Promise(resolve => {
    try {
      const child = spawn(command, args, { stdio: 'ignore', detached: true, shell, windowsHide: true, windowsVerbatimArguments: process.platform === 'win32' })
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
