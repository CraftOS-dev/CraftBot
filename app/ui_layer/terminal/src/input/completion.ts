/**
 * Slash completion: while the composer holds a lone "/word", suggest the
 * backend's commands and the enabled skills, grouped "Commands" then
 * "Skills" like the browser. Matching is anchored to the start of a word
 * in the name, so "/sk" finds "/skill" and "/my-skill".
 */
export interface Suggestion {
  /** Text inserted on accept, e.g. "/help". */
  value: string
  description: string
  group: 'command' | 'skill'
}

export interface CommandLike {
  name: string
  description: string
}

export interface SkillLike {
  name: string
  description: string
  enabled: boolean
  user_invocable: boolean
}

const SLASH_QUERY = /^\/([^\s]*)$/

/** The query after "/", or null when the composer is not completing a command. */
export function slashQuery(text: string): string | null {
  const match = SLASH_QUERY.exec(text)
  return match ? match[1].toLowerCase() : null
}

function matches(name: string, query: string): boolean {
  if (!query) return true
  const lower = name.toLowerCase()
  if (lower.startsWith(query)) return true
  return lower.split(/[-_\s]/).some(part => part.startsWith(query))
}

export function suggestions(
  text: string,
  commands: CommandLike[],
  skills: SkillLike[],
  limit = 8,
): Suggestion[] {
  const query = slashQuery(text)
  if (query === null) return []
  const out: Suggestion[] = []
  const seen = new Set<string>()
  for (const command of commands) {
    const name = command.name.replace(/^\//, '')
    if (!matches(name, query) || seen.has(name)) continue
    seen.add(name)
    out.push({ value: `/${name}`, description: command.description, group: 'command' })
  }
  for (const skill of skills) {
    if (!skill.enabled || !skill.user_invocable) continue
    if (!matches(skill.name, query) || seen.has(skill.name)) continue
    seen.add(skill.name)
    out.push({ value: `/${skill.name}`, description: skill.description, group: 'skill' })
  }
  // Exact and prefix matches first, then word matches; groups stay ordered.
  const rank = (s: Suggestion) => (s.value.slice(1).toLowerCase().startsWith(query) ? 0 : 1)
  return out
    .map((s, i) => ({ s, i }))
    .sort((a, b) => (a.s.group === b.s.group ? rank(a.s) - rank(b.s) || a.i - b.i : a.s.group === 'command' ? -1 : 1))
    .slice(0, limit)
    .map(x => x.s)
}
