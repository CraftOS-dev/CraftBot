/**
 * Pure helpers of the workspace screen: workspace paths ("/" separated,
 * relative to the workspace root), the browser's "_copy" naming for pastes,
 * sizes, local paths typed by the user, and safe text previews.
 */
import { isAbsolute, join, resolve } from 'node:path'
import { wrap } from '../text/width'

/** The folder of a workspace path ("" for the root). */
export function parentPath(path: string): string {
  const clean = path.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  const slash = clean.lastIndexOf('/')
  return slash === -1 ? '' : clean.slice(0, slash)
}

export function joinPath(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name
}

export function baseName(path: string): string {
  return path.split(/[/\\]/).pop() ?? path
}

/**
 * A name that does not collide with `existing` (lowercased names), the way
 * the browser pastes: "a.txt", then "a_copy.txt", "a_copy2.txt", ...
 */
export function uniqueName(name: string, existing: ReadonlySet<string>): string {
  if (!existing.has(name.toLowerCase())) return name
  const dot = name.lastIndexOf('.')
  const hasExt = dot > 0
  const base = hasExt ? name.slice(0, dot) : name
  const ext = hasExt ? name.slice(dot) : ''
  let candidate = `${base}_copy${ext}`
  let counter = 2
  while (existing.has(candidate.toLowerCase())) {
    candidate = `${base}_copy${counter}${ext}`
    counter++
  }
  return candidate
}

/** Where the caret starts when renaming: before the extension, as the browser keeps it. */
export function renameCaret(name: string): number {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? dot : name.length
}

/** "512 B", "1.5 KB", "12.0 MB", "1.2 GB". */
export function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes === null || !Number.isFinite(bytes)) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/**
 * A local path as the user typed or dropped it: surrounding quotes removed
 * (Windows Terminal quotes dropped paths), a leading ~ expanded, relative
 * paths resolved against `cwd`.
 */
export function resolveLocalPath(input: string, cwd: string, home: string): string {
  let p = input.trim()
  if (p.length >= 2 && ((p.startsWith('"') && p.endsWith('"')) || (p.startsWith("'") && p.endsWith("'")))) {
    p = p.slice(1, -1).trim()
  }
  if (!p) return ''
  if (p === '~') return home
  if (p.startsWith('~/') || p.startsWith('~\\')) p = join(home, p.slice(2))
  return isAbsolute(p) ? resolve(p) : resolve(cwd, p)
}

/**
 * File text made safe to draw: escape sequences and other control
 * characters removed (a file must never drive the terminal), tabs expanded,
 * line endings normalized.
 */
export function sanitizeText(text: string, tabWidth = 4): string {
  return text
    .replace(/\r\n?/g, '\n')
    .replace(/\u001B\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\u001B[\]PX^_][\s\S]*?(?:\u0007|\u001B\\)/g, '')
    .replace(/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/g, '')
    .replace(/\t/g, ' '.repeat(tabWidth))
}

/**
 * Preview lines of a text file wrapped to `width` cells. A line's own
 * indentation is kept; the space a wrap breaks at is not carried onto the
 * continuation.
 */
export function previewLines(text: string, width: number): string[] {
  const lines = sanitizeText(text).split('\n')
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop()
  return lines.flatMap(line =>
    line === '' ? [''] : wrap(line, Math.max(1, width)).map((piece, i) => (i > 0 ? piece.replace(/^ /, '') : piece)),
  )
}
