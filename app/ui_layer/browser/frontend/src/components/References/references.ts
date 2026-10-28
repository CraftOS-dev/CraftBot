import type { ReferenceInput, SessionInfo, AgentAppProject } from '../../types'

export interface ReferenceCandidate extends ReferenceInput {
  label: string
  description: string
  updatedAt: string
}

export const referenceKey = (r: ReferenceInput) => `${r.kind}:${r.targetId}`

export function referenceCatalog(sessions: SessionInfo[], apps: AgentAppProject[], destination: string): ReferenceCandidate[] {
  return [
    ...sessions.filter(s => s.id !== destination && (s.type === 'main' || s.type === 'chat')).map(s => ({
      kind: 'session' as const, targetId: s.id, label: s.title || 'Main chat',
      description: s.type, updatedAt: s.lastActiveAt || s.createdAt,
    })),
    ...apps.map(a => ({ kind: 'agent_app' as const, targetId: a.id, label: a.name,
      description: a.description || '', updatedAt: new Date(a.createdAt).toISOString() })),
  ]
}

export function searchReferences(items: ReferenceCandidate[], query: string): ReferenceCandidate[] {
  const q = query.trim().toLocaleLowerCase()
  const rank = (r: ReferenceCandidate) => r.label.toLocaleLowerCase() === q ? 0
    : r.label.toLocaleLowerCase().startsWith(q) ? 1 : 2
  return items.filter(r => `${r.label} ${r.description}`.toLocaleLowerCase().includes(q))
    .sort((a, b) => rank(a) - rank(b) || b.updatedAt.localeCompare(a.updatedAt) || referenceKey(a).localeCompare(referenceKey(b)))
}

export interface ReferenceQuery { start: number; end: number; query: string }
export function referenceQuery(text: string, start: number, end = start): ReferenceQuery | null {
  if (start !== end) return null
  const before = text.slice(0, start)
  // "@" then a space is prose ("see you @ 5pm"), not a mention.
  const match = /(?:^|\s)@((?:\S[^@\n]*)?)$/.exec(before)
  if (!match) return null
  return { start: start - match[1].length - 1, end: start, query: match[1] }
}
