/**
 * Pure helpers of the memory screen: the browser MemoryPage's graph filters
 * (hide default files, kind toggles), search, the node list order, the
 * neighbour tree that replaces the force graph, and the indexed-files tree.
 */
import type {
  IndexCandidate,
  IndexedFileInfo,
  MemoryGraph,
  MemoryGraphNode,
  MemoryItem,
} from '../../../browser/frontend/src/store/slices/memorySettingsSlice'

export const CATEGORY_OPTIONS = ['fact', 'preference', 'event', 'decision', 'learning', 'project', 'contact']

/** Default files whose sections stay visible when default files are hidden. */
const EXEMPT_CORE = new Set(['MEMORY.md', 'USER.md', 'ENTITIES.md'])

/**
 * The graph without the default (core) indexed files and their sections,
 * except MEMORY.md, USER.md and ENTITIES.md, exactly as the browser hides them.
 */
export function withoutCoreFiles(graph: MemoryGraph | null, files: IndexedFileInfo[], hide: boolean): MemoryGraph | null {
  if (!graph || !hide) return graph
  const hidden = new Set(files.filter(f => f.core && !EXEMPT_CORE.has(f.path)).map(f => f.path))
  if (hidden.size === 0) return graph
  const nodes = graph.nodes.filter(n => {
    if (n.kind === 'file' && hidden.has(n.label)) return false
    if (n.kind === 'item' && n.source === 'file' && hidden.has(n.file || '')) return false
    return true
  })
  const kept = new Set(nodes.map(n => n.id))
  return { ...graph, nodes, edges: graph.edges.filter(e => kept.has(e.source) && kept.has(e.target)) }
}

export interface KindToggles {
  memories: boolean
  entities: boolean
  files: boolean
}

export interface KindCounts {
  memories: number
  entities: number
  files: number
}

export function countKinds(graph: MemoryGraph | null): KindCounts {
  const counts = { memories: 0, entities: 0, files: 0 }
  for (const n of graph?.nodes ?? []) {
    if (n.kind === 'item') counts.memories++
    else if (n.kind === 'entity') counts.entities++
    else if (n.kind === 'file') counts.files++
  }
  return counts
}

export function kindVisible(node: MemoryGraphNode, toggles: KindToggles): boolean {
  if (node.kind === 'item') return toggles.memories
  if (node.kind === 'entity') return toggles.entities
  return toggles.files
}

/** Conversation memories (newest first), then entities (most mentioned), files, and file sections. */
function rank(node: MemoryGraphNode): number {
  if (node.kind === 'item') return node.source === 'file' ? 3 : 0
  return node.kind === 'entity' ? 1 : 2
}

export function sortNodes(nodes: MemoryGraphNode[]): MemoryGraphNode[] {
  return [...nodes].sort((a, b) => {
    const r = rank(a) - rank(b)
    if (r !== 0) return r
    if (rank(a) === 0) return (b.timestamp ?? '').localeCompare(a.timestamp ?? '')
    if (a.kind === 'entity') return (b.size ?? 0) - (a.size ?? 0) || a.label.localeCompare(b.label)
    if (rank(a) === 3) return (a.file ?? '').localeCompare(b.file ?? '') || (a.section ?? '').localeCompare(b.section ?? '')
    return a.label.localeCompare(b.label)
  })
}

/** The MemoryItem behind a conversation-memory node (`i:<id>`), if any. */
export function itemOfNode(node: MemoryGraphNode | null | undefined, items: MemoryItem[]): MemoryItem | null {
  if (!node || node.kind !== 'item' || node.source === 'file') return null
  return items.find(i => `i:${i.id}` === node.id) ?? null
}

/** Case-insensitive match on what the browser searches: text, category, linked names, file and section. */
export function matchesQuery(node: MemoryGraphNode, query: string, item: MemoryItem | null): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const hay = [node.label, node.category, node.section, node.file, item?.displayContent, item?.content, ...(item?.entities ?? [])]
  return hay.some(v => typeof v === 'string' && v.toLowerCase().includes(q))
}

export function adjacency(graph: MemoryGraph | null): Map<string, string[]> {
  const map = new Map<string, Set<string>>()
  const add = (a: string, b: string) => {
    let set = map.get(a)
    if (!set) map.set(a, (set = new Set()))
    set.add(b)
  }
  for (const e of graph?.edges ?? []) {
    if (e.source === e.target) continue
    add(e.source, e.target)
    add(e.target, e.source)
  }
  const out = new Map<string, string[]>()
  for (const [id, set] of map) out.set(id, Array.from(set))
  return out
}

export interface TreeRow {
  /** Unique: the ids from the root down to this row, joined. */
  key: string
  /** Node id, or null for a "+N more" row. */
  id: string | null
  depth: number
  /** Connector prefix drawn before the row ("│ ├ "). */
  prefix: string
  /** Neighbours this row could expand into (excluding its own ancestors). */
  childCount: number
  expanded: boolean
  /** For a "+N more" row: how many are not shown. */
  more?: number
}

/**
 * The neighbour tree of `rootId`: its neighbours, and under every expanded
 * row that node's own neighbours (never walking back up its path). Each
 * level shows at most `limit` children plus a "+N more" row.
 */
export function neighbourTree(
  rootId: string,
  adj: Map<string, string[]>,
  nodes: Map<string, MemoryGraphNode>,
  expanded: ReadonlySet<string>,
  limit = 40,
  connectors = { tee: '├ ', last: '└ ', pipe: '│ ', space: '  ' },
): TreeRow[] {
  const rows: TreeRow[] = []
  const childrenOf = (id: string, path: Set<string>) =>
    sortNodes((adj.get(id) ?? []).filter(n => !path.has(n) && nodes.has(n)).map(n => nodes.get(n) as MemoryGraphNode)).map(n => n.id)

  const walk = (id: string, path: Set<string>, keyPrefix: string, depth: number, indent: string) => {
    const kids = childrenOf(id, path)
    const shown = kids.slice(0, limit)
    shown.forEach((child, i) => {
      const last = i === shown.length - 1 && kids.length <= limit
      const key = `${keyPrefix}>${child}`
      const childPath = new Set(path).add(child)
      const grandKids = (adj.get(child) ?? []).filter(n => !childPath.has(n) && nodes.has(n)).length
      const isOpen = expanded.has(key) && grandKids > 0
      rows.push({ key, id: child, depth, prefix: indent + (last ? connectors.last : connectors.tee), childCount: grandKids, expanded: isOpen })
      if (isOpen) walk(child, childPath, key, depth + 1, indent + (last ? connectors.space : connectors.pipe))
    })
    if (kids.length > limit) {
      rows.push({ key: `${keyPrefix}>+more`, id: null, depth, prefix: indent + connectors.last, childCount: 0, expanded: false, more: kids.length - limit })
    }
  }
  walk(rootId, new Set([rootId]), rootId, 0, '')
  return rows
}

// ── Indexed files: indexed files and candidates merged into folders ──

export interface FileEntry {
  path: string
  name: string
  core: boolean
  indexed: boolean
  exists: boolean
  chunks: number
  size: number
}

export interface FileFolder {
  path: string
  name: string
  folders: FileFolder[]
  files: FileEntry[]
}

export function buildFileTree(indexed: IndexedFileInfo[], candidates: IndexCandidate[]): FileFolder {
  const root: FileFolder = { path: '', name: '', folders: [], files: [] }
  const folders = new Map<string, FileFolder>([['', root]])
  const ensure = (path: string): FileFolder => {
    const found = folders.get(path)
    if (found) return found
    const slash = path.lastIndexOf('/')
    const parent = ensure(slash === -1 ? '' : path.slice(0, slash))
    const folder: FileFolder = { path, name: slash === -1 ? path : path.slice(slash + 1), folders: [], files: [] }
    parent.folders.push(folder)
    folders.set(path, folder)
    return folder
  }
  const add = (entry: FileEntry) => {
    const slash = entry.path.lastIndexOf('/')
    ensure(slash === -1 ? '' : entry.path.slice(0, slash)).files.push(entry)
  }
  const name = (p: string) => p.slice(p.lastIndexOf('/') + 1)
  for (const f of indexed) {
    add({ path: f.path, name: name(f.path), core: f.core, indexed: true, exists: f.exists, chunks: f.chunk_count, size: 0 })
  }
  for (const c of candidates) {
    add({ path: c.path, name: name(c.path), core: false, indexed: false, exists: true, chunks: 0, size: c.size })
  }
  const sort = (folder: FileFolder) => {
    folder.folders.sort((a, b) => a.name.localeCompare(b.name))
    folder.files.sort((a, b) => a.name.localeCompare(b.name))
    folder.folders.forEach(sort)
  }
  sort(root)
  return root
}

export type FileTreeRow =
  | { type: 'folder'; path: string; name: string; depth: number; expanded: boolean; indexed: number; total: number }
  | { type: 'file'; depth: number; file: FileEntry }

function countFiles(folder: FileFolder): { indexed: number; total: number } {
  let indexed = folder.files.filter(f => f.indexed).length
  let total = folder.files.length
  for (const sub of folder.folders) {
    const c = countFiles(sub)
    indexed += c.indexed
    total += c.total
  }
  return { indexed, total }
}

/** Visible rows of the tree: folders collapsed unless their path is in `expanded`. */
export function flattenFileTree(root: FileFolder, expanded: ReadonlySet<string>): FileTreeRow[] {
  const rows: FileTreeRow[] = []
  const walk = (folder: FileFolder, depth: number) => {
    for (const sub of folder.folders) {
      const open = expanded.has(sub.path)
      rows.push({ type: 'folder', path: sub.path, name: sub.name, depth, expanded: open, ...countFiles(sub) })
      if (open) walk(sub, depth + 1)
    }
    for (const file of folder.files) rows.push({ type: 'file', depth, file })
  }
  walk(root, 0)
  return rows
}
