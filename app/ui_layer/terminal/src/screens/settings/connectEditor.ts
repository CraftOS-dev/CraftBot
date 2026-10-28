/**
 * Long text (an MCP server's JSON, a SKILL.md, a multi-line integration
 * setting) is edited in the user's own editor through the shared
 * `openInEditor` (src/screens/viewEditor.ts), which hands the terminal over
 * with Ink's suspendTerminal and keeps stdin working on Windows afterwards.
 * These helpers read the result back and remove the temporary file, which
 * may hold secrets (an MCP server's env).
 */
import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import { editorCommand, openInEditor, type Suspend } from '../viewEditor'

export interface EditResult {
  /** The text after the editor exited; null when the editor could not run or failed. */
  text: string | null
  changed: boolean
}

/** The editor that runs, for messages. */
export function editorName(): string {
  return editorCommand(process.env, process.platform)
}

/** Edit `initial` in the editor (`name` becomes part of the temporary file's name; `extension` picks the editor's language). */
export async function editText(suspend: Suspend, initial: string, name: string, extension = 'md'): Promise<EditResult> {
  let path: string | null = null
  try {
    path = (await openInEditor(initial, name, suspend, extension)).path
    const text = readFileSync(path, 'utf8')
    return { text, changed: text !== initial }
  } catch {
    return { text: null, changed: false }
  } finally {
    if (path) rmSync(path, { force: true })
  }
}

/** Edit an existing file: through a temporary copy, written back only when it changed. */
export async function editFile(suspend: Suspend, file: string, name: string): Promise<{ ok: boolean; changed: boolean }> {
  let before: string
  try {
    before = readFileSync(file, 'utf8')
  } catch {
    return { ok: false, changed: false }
  }
  const result = await editText(suspend, before, name)
  if (result.text === null) return { ok: false, changed: false }
  if (!result.changed) return { ok: true, changed: false }
  try {
    writeFileSync(file, result.text, 'utf8')
  } catch {
    return { ok: false, changed: false }
  }
  return { ok: true, changed: true }
}
