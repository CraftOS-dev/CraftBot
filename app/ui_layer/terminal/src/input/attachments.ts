/**
 * Files attached by mentioning them: "@report.pdf" or "@\"C:\My files\a.png\"".
 * Relative paths resolve from the directory the terminal was started in;
 * "~" is the home directory. While the word under the caret is an @mention,
 * the composer offers the matching entries of that directory.
 */
import { existsSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve, sep } from 'node:path'

const MENTION = /(^|\s)@("([^"]+)"|[^\s"]+)/g

export function expandPath(raw: string, cwd: string = process.cwd()): string {
  const path = raw.startsWith('~') ? join(homedir(), raw.slice(1)) : raw
  return isAbsolute(path) ? path : resolve(cwd, path)
}

/** Existing files mentioned in the text, in order, without duplicates. */
export function mentionedFiles(text: string, cwd?: string): string[] {
  const out: string[] = []
  for (const match of text.matchAll(MENTION)) {
    const raw = match[3] ?? match[2] ?? ''
    const path = expandPath(raw, cwd)
    try {
      if (statSync(path).isFile() && !out.includes(path)) out.push(path)
    } catch {
      // Not a file: an ordinary @word stays text.
    }
  }
  return out
}

/** The @mention the caret is in, if any: its start index and the path typed so far. */
export function mentionAt(text: string, cursor: number): { start: number; path: string } | null {
  const before = text.slice(0, cursor)
  const match = /(^|\s)@("?[^\s"]*)$/.exec(before)
  if (!match) return null
  const start = before.length - match[2].length - 1
  return { start, path: match[2].replace(/^"/, '') }
}

export interface PathSuggestion {
  /** Replaces the mention (including the @). */
  value: string
  label: string
  isDir: boolean
}

/** Entries of the mention's directory that start with what was typed. */
export function pathSuggestions(typed: string, cwd: string = process.cwd(), limit = 8): PathSuggestion[] {
  const endsWithSep = typed.endsWith('/') || typed.endsWith(sep)
  const dirPart = endsWithSep ? typed : dirname(typed) === '.' && !typed.includes('/') && !typed.includes(sep) ? '' : dirname(typed)
  const prefix = endsWithSep ? '' : basename(typed)
  const dir = expandPath(dirPart || '.', cwd)
  if (!existsSync(dir)) return []
  let entries: string[]
  try {
    entries = readdirSync(dir)
  } catch {
    return []
  }
  const shown: PathSuggestion[] = []
  for (const name of entries.sort((a, b) => a.localeCompare(b))) {
    if (!name.toLowerCase().startsWith(prefix.toLowerCase())) continue
    if (name.startsWith('.') && !prefix.startsWith('.')) continue
    let isDir = false
    try {
      isDir = statSync(join(dir, name)).isDirectory()
    } catch {
      continue
    }
    const rel = dirPart ? join(dirPart, name) : name
    const quoted = /\s/.test(rel) ? `"${rel}${isDir ? sep : ''}` : `${rel}${isDir ? sep : ''}`
    shown.push({ value: `@${quoted}${isDir ? '' : /\s/.test(rel) ? '" ' : ' '}`, label: name + (isDir ? sep : ''), isDir })
    if (shown.length >= limit) break
  }
  return shown
}
