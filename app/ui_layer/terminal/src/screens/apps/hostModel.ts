/**
 * Pure logic of the Agent App host screens (Apps list, Add, build view,
 * settings panel), kept free of React and the store so it is unit tested
 * (test/unit/appsHost.test.ts). Rules mirror the browser's host UI:
 * NavBar's app rows, ConstructionDock, CreateAgentAppModal and
 * CreateCustomWizard.
 */

// ── status ──────────────────────────────────────────────────────────────────

/** The six states the Apps screen shows (the store's `ready` reads as stopped). */
export type AppPhase = 'creating' | 'launching' | 'running' | 'stopping' | 'stopped' | 'error'

export function appPhase(status: string | undefined): AppPhase {
  switch (status) {
    case 'creating':
    case 'launching':
    case 'running':
    case 'stopping':
    case 'error':
      return status
    default:
      // 'stopped', 'ready' (built, not running) and anything unknown.
      return 'stopped'
  }
}

export function isTransitional(phase: AppPhase): boolean {
  return phase === 'creating' || phase === 'launching' || phase === 'stopping'
}

export const canLaunch = (phase: AppPhase): boolean => phase === 'stopped' || phase === 'error'
export const canStop = (phase: AppPhase): boolean => phase === 'running'
/** Deleting is offered only while the app is not running or changing state. */
export const canDelete = (phase: AppPhase): boolean => phase === 'stopped' || phase === 'error'

// ── build progress (ConstructionDock's rules) ───────────────────────────────

export interface TodoLike {
  content?: string
  active_form?: string
  status: string
}

const WORKFLOW_PREFIX = /^\s*(acknowledge|collect|execute|verify|confirm|cleanup)\s*:\s*/i

export function cleanTodoLabel(text: string | undefined | null): string {
  if (!text) return ''
  const stripped = text.replace(WORKFLOW_PREFIX, '').trim()
  if (!stripped) return ''
  return stripped.charAt(0).toUpperCase() + stripped.slice(1)
}

export interface BuildProgress {
  /** 0 to 100. */
  progress: number
  /** The step in progress, without its workflow prefix. */
  label: string
  /** No todos yet: the bar has nothing to measure. */
  indeterminate: boolean
  done: number
  total: number
}

export function deriveProgress(todos: TodoLike[] | undefined): BuildProgress {
  const list = todos ?? []
  if (list.length === 0) return { progress: 0, label: '', indeterminate: true, done: 0, total: 0 }
  const done = list.filter(t => t.status === 'completed').length
  const current = list.find(t => t.status === 'in_progress')
  return {
    progress: (done / list.length) * 100,
    label: cleanTodoLabel(current?.active_form) || cleanTodoLabel(current?.content),
    indeterminate: false,
    done,
    total: list.length,
  }
}

/** A text progress bar of exactly `cells` cells. */
export function progressBar(progress: number, cells: number, full: string, empty: string): string {
  const size = Math.max(0, cells)
  const filled = Math.max(0, Math.min(size, Math.round((progress / 100) * size)))
  return full.repeat(filled) + empty.repeat(size - filled)
}

/** The moving block of an indeterminate bar at animation step `tick`. */
export function indeterminateBar(tick: number, cells: number, full: string, empty: string, block = 4): string {
  const size = Math.max(0, cells)
  if (size === 0) return ''
  const span = size + block
  const start = (tick % span) - block
  let out = ''
  for (let i = 0; i < size; i++) out += i >= start && i < start + block ? full : empty
  return out
}

// ── build feed ──────────────────────────────────────────────────────────────

export interface FeedEventLike {
  id: string
  kind: string
  area: string
  file?: string
}

export interface FeedRow<E> {
  event: E
  count: number
}

const COALESCE_KINDS = new Set(['file_write', 'file_edit'])

/** Consecutive writes or edits of one file collapse into one row with a count. */
export function coalesceEvents<E extends FeedEventLike>(events: E[]): FeedRow<E>[] {
  const rows: FeedRow<E>[] = []
  for (const e of events) {
    const last = rows[rows.length - 1]
    const mergeable =
      last &&
      COALESCE_KINDS.has(e.kind) &&
      last.event.kind === e.kind &&
      (last.event.file ?? last.event.area) === (e.file ?? e.area)
    if (mergeable) {
      last.event = e
      last.count += 1
    } else {
      rows.push({ event: e, count: 1 })
    }
  }
  return rows
}

/**
 * Pacing: events arrive in bursts and are revealed one at a time. Returns the
 * next revealed count and the delay before it, or null when caught up.
 */
export function nextPaced(count: number, total: number): { count: number; delay: number } | null {
  if (count > total) return { count: total, delay: 0 }
  if (count === total) return null
  // First fill (a reopened screen): land almost caught up.
  if (count === 0 && total > 8) return { count: total - 3, delay: 0 }
  const backlog = total - count
  return { count: count + 1, delay: backlog > 4 ? 220 : 750 }
}

/** The last `rows` lines of a code snippet, tabs expanded and control characters dropped. */
export function snippetTail(snippet: string, rows: number): string[] {
  if (rows <= 0) return []
  const lines = snippet
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.replace(/\t/g, '  ').replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, ''))
  while (lines.length > 0 && lines[lines.length - 1].trim() === '') lines.pop()
  return lines.slice(-rows)
}

// ── ordering (the browser sidebar's saved drag order) ───────────────────────

export function orderApps<T extends { id: string }>(items: T[], order: string[]): T[] {
  if (order.length === 0) return items
  const rank = new Map(order.map((id, i) => [id, i]))
  const known: T[] = []
  const fresh: T[] = []
  for (const item of items) (rank.has(item.id) ? known : fresh).push(item)
  if (known.length === 0) return items
  known.sort((a, b) => rank.get(a.id)! - rank.get(b.id)!)
  return [...known, ...fresh]
}

/** Move `id` by `delta` places in `ids`; the same array when it cannot move. */
export function moveId(ids: string[], id: string, delta: -1 | 1): string[] {
  const from = ids.indexOf(id)
  const to = from + delta
  if (from === -1 || to < 0 || to >= ids.length) return ids
  const next = [...ids]
  next.splice(from, 1)
  next.splice(to, 0, id)
  return next
}

// ── marketplace ─────────────────────────────────────────────────────────────

export interface MarketplaceField {
  key: string
  label: string
  type?: string
  default?: string
  placeholder?: string
}

export interface MarketplaceApp {
  id: string
  name: string
  description: string
  preview?: string
  folder?: string
  tags?: string[]
  version?: string
  customizable?: MarketplaceField[]
}

/** The install key the backend expects (folder first, as the browser sends). */
export const marketKey = (app: MarketplaceApp): string => app.folder || app.id

/** Every tag, most used first, then alphabetical. */
export function tagsByFrequency(apps: MarketplaceApp[]): string[] {
  const counts = new Map<string, number>()
  for (const app of apps) for (const tag of app.tags ?? []) counts.set(tag, (counts.get(tag) ?? 0) + 1)
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([tag]) => tag)
}

/** Search name, description and tags; an app passes with ANY selected tag. */
export function filterMarketplace(apps: MarketplaceApp[], query: string, tags: ReadonlySet<string>): MarketplaceApp[] {
  const q = query.trim().toLowerCase()
  return apps.filter(app => {
    if (q) {
      const hay = `${app.name} ${app.description} ${(app.tags ?? []).join(' ')}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    if (tags.size > 0 && !(app.tags ?? []).some(tag => tags.has(tag))) return false
    return true
  })
}

export function defaultFieldValues(app: MarketplaceApp): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of app.customizable ?? []) values[field.key] = field.default ?? ''
  return values
}

// ── create wizard ───────────────────────────────────────────────────────────

export const MAX_NAME = 50
export const MAX_WORDS = 5000

export function countWords(text: string): number {
  const trimmed = text.trim()
  return trimmed ? trimmed.split(/\s+/).length : 0
}

export type ConfigError = 'nameRequired' | 'nameTooLong' | 'descRequired' | 'descTooShort' | 'descTooLong'

export function validateConfig(name: string, description: string): { name?: ConfigError; description?: ConfigError } {
  const errors: { name?: ConfigError; description?: ConfigError } = {}
  if (!name.trim()) errors.name = 'nameRequired'
  else if (name.length > MAX_NAME) errors.name = 'nameTooLong'
  if (!description.trim()) errors.description = 'descRequired'
  else if (description.trim().length < 10) errors.description = 'descTooShort'
  else if (countWords(description) > MAX_WORDS) errors.description = 'descTooLong'
  return errors
}

/** The browser's curated icon set (AgentAppIcon.tsx), by lucide name. */
export const CURATED_ICONS = [
  'LayoutDashboard', 'SquareKanban', 'ListTodo', 'Calendar', 'Clock', 'Newspaper',
  'BookOpen', 'BarChart3', 'PieChart', 'Wallet', 'ShoppingCart', 'Package', 'Users',
  'MessageSquare', 'Mail', 'Music', 'Camera', 'Gamepad2', 'Utensils', 'Dumbbell', 'Plane',
  'Home', 'Star', 'Heart', 'Zap', 'Globe', 'Briefcase',
] as const

/**
 * A typed icon name as a lucide component name: "shopping-cart" and
 * "shopping cart" become "ShoppingCart"; a curated name matches regardless of
 * case. Null for empty or invalid input.
 */
export function normalizeIconName(text: string): string | null {
  const raw = text.trim().replace(/^lucide:/i, '')
  if (!raw) return null
  const curated = CURATED_ICONS.find(name => name.toLowerCase() === raw.toLowerCase().replace(/[\s_-]+/g, ''))
  if (curated) return curated
  const parts = raw.split(/[\s_-]+/).filter(Boolean)
  const name = parts.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('')
  return /^[A-Za-z][A-Za-z0-9]*$/.test(name) ? name : null
}

/** Step through the curated icons from the current one (wrapping, with "none" before the first). */
export function cycleIcon(current: string | null, delta: -1 | 1): string | null {
  const list: (string | null)[] = [null, ...CURATED_ICONS]
  const index = Math.max(0, list.indexOf(current))
  return list[(index + delta + list.length) % list.length]
}

export function newWizardId(): string {
  return `w_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

export interface InterviewQuestion {
  id: string
  question: string
  why?: string
  multiSelect: boolean
  options: string[]
}

/** Select or toggle `option` for a question (radio for single, checkbox for multi). */
export function pickOption(question: InterviewQuestion, selected: string[], option: string): string[] {
  if (!question.multiSelect) return [option]
  return selected.includes(option) ? selected.filter(v => v !== option) : [...selected, option]
}

/**
 * The answer a Continue records: typed text joins the checked options of a
 * multi-select or replaces the choice of a single-select. Empty = nothing to send.
 */
export function composeAnswer(question: InterviewQuestion, selected: string[], freeText: string): string[] {
  const text = freeText.trim()
  if (text) return question.multiSelect ? [...selected, text] : [text]
  return selected
}

/** The answers finalize sends: answered questions only, options joined. */
export function answersPayload(
  questions: InterviewQuestion[],
  answers: Record<string, string[]>,
): { id: string; question: string; answer: string }[] {
  return questions
    .filter(q => (answers[q.id] ?? []).length > 0)
    .map(q => ({ id: q.id, question: q.question, answer: (answers[q.id] ?? []).join(', ') }))
}

// ── import ──────────────────────────────────────────────────────────────────

export function isZipPath(source: string): boolean {
  return /\.zip$/i.test(source.trim())
}

/** The project name an import gets: the last path or URL segment. */
export function importName(source: string, fallback: string): string {
  const trimmed = source.trim().replace(/[\\/]+$/, '')
  const last = trimmed.split(/[\\/]/).pop() ?? ''
  const name = last.replace(/\.git$/i, '').replace(/\.zip$/i, '').replace(/^agentapp_/, '').replace(/_[a-f0-9]+$/, '')
  return name || fallback
}

export function humanBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return i === 0 ? `${Math.round(v)} B` : `${v.toFixed(1)} ${units[i]}`
}

export interface ImportProgressEvent {
  phase?: string
  done?: number
  total?: number
  unit?: string
}

/** "1,200 / 5,000 (24%)" or "3.1 MB / 9.0 MB (34%)"; empty while starting. */
export function importAmount(event: ImportProgressEvent, locale?: string): string {
  const { phase = 'starting', done = 0, total = 0, unit } = event
  if (phase === 'starting' || (!done && !total)) return ''
  const fmt = (n: number) => n.toLocaleString(locale)
  const amount =
    unit === 'bytes'
      ? humanBytes(done) + (total ? ` / ${humanBytes(total)}` : '')
      : total
        ? `${fmt(done)} / ${fmt(total)}`
        : fmt(done)
  const pct = total ? ` (${Math.floor((done / total) * 100)}%)` : ''
  return amount + pct
}

/** Progress lines keep one line per phase: a repeated phase updates its line. */
export function pushProgressLine<L extends { phase: string }>(lines: L[], line: L, max = 8): L[] {
  const last = lines[lines.length - 1]
  const next = last && last.phase === line.phase ? [...lines.slice(0, -1), line] : [...lines, line]
  return next.slice(-max)
}

// ── settings panel ──────────────────────────────────────────────────────────

export const BACKUP_INTERVALS = ['hourly', '6h', 'daily', 'weekly'] as const
export type BackupInterval = (typeof BACKUP_INTERVALS)[number]

export function cycleValue<T>(values: readonly T[], current: T, delta: -1 | 1): T {
  const index = Math.max(0, values.indexOf(current))
  return values[(index + delta + values.length) % values.length]
}

export function clampKeep(value: number): number {
  return Math.max(1, Math.min(30, Math.round(value)))
}

/** A file name from a Content-Disposition header, made safe for any file system. */
export function dispositionFilename(header: string | null, fallback: string): string {
  const match = header?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)
  const raw = match ? decodeURIComponent(match[1]) : fallback
  const safe = raw.replace(/[<>:"/\\|?*\u0000-\u001F]/g, '_').trim()
  return safe || fallback
}
