/**
 * The composer's input history: the last 50 sent inputs, newest last, kept
 * across launches in the remembered UI state file.
 */
const KEY = 'craftbot-terminal-history'
const LIMIT = 50

function read(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]') as unknown
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

let entries: string[] | null = null

export function history(): string[] {
  if (!entries) entries = read()
  return entries
}

export function remember(text: string): void {
  const value = text.trim()
  if (!value) return
  const list = history().filter(e => e !== value)
  list.push(value)
  entries = list.slice(-LIMIT)
  localStorage.setItem(KEY, JSON.stringify(entries))
}
