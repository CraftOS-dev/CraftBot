/**
 * ConstructionDock — the read-only build visualizer shown while a Living UI is
 * being created.
 *
 * It is a pure presentational surface driven by two inputs the platform
 * already produces: the agent's todos (progress bar + "Step N of M") and the
 * build-event feed derived read-only by the backend observer
 * (construction_events.py). It shows built-so-far chips, a paced + coalesced
 * feed of what's happening, and a live CodePeek of the code being written.
 *
 * It observes only — nothing here touches or drives the build. There is no app
 * preview behind it (the dock is the whole view); when the build completes and
 * the app launches, LivingUIPage swaps this out for the running app iframe.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Server,
  PanelsTopLeft,
  FlaskConical,
  FileText,
  Package,
  Rocket,
  CheckCircle2,
  XCircle,
  Eye,
  Search,
  Terminal,
  MonitorPlay,
  ListChecks,
} from 'lucide-react'
import { DraftMascot } from '@mascot'
import type { LivingUIProject, LivingUIBuildEvent } from '../../types'
import type { LivingUITodo, LivingUISnapshot } from '../../store/slices/livingUiSlice'
import styles from './LivingUIPage.module.css'

interface Props {
  project: LivingUIProject
  todos: LivingUITodo[] | undefined
  events: LivingUIBuildEvent[]
  snapshot: LivingUISnapshot | null
}

// ── progress derived from the agent's todos ────────────────────────────────

const WORKFLOW_PREFIX = /^\s*(acknowledge|collect|execute|verify|confirm|cleanup)\s*:\s*/i

function cleanLabel(text: string | undefined | null): string {
  if (!text) return ''
  const stripped = text.replace(WORKFLOW_PREFIX, '').trim()
  if (!stripped) return ''
  return stripped.charAt(0).toUpperCase() + stripped.slice(1)
}

interface ProgressView {
  progress: number
  todoLabel: string
  indeterminate: boolean
}

function deriveProgress(todos: LivingUITodo[] | undefined): ProgressView {
  const list = todos ?? []
  if (list.length === 0) {
    return { progress: 0, todoLabel: '', indeterminate: true }
  }
  const completed = list.filter(t => t.status === 'completed').length
  const inProgress = list.find(t => t.status === 'in_progress') ?? null
  return {
    progress: (completed / list.length) * 100,
    todoLabel: cleanLabel(inProgress?.active_form) || cleanLabel(inProgress?.content),
    indeterminate: false,
  }
}

// ── pacing ──────────────────────────────────────────────────────────────────
// Events arrive in bursts; reveal them one at a time so the dock is always
// moving instead of jumping.

function usePacedEvents(events: LivingUIBuildEvent[]): LivingUIBuildEvent[] {
  const [count, setCount] = useState(0)

  useEffect(() => {
    if (count > events.length) {
      setCount(events.length)
      return
    }
    if (count === events.length) return
    // First fill after a page refresh: land on "almost caught up".
    if (count === 0 && events.length > 8) {
      setCount(events.length - 3)
      return
    }
    const backlog = events.length - count
    const delay = backlog > 4 ? 220 : 750
    const t = setTimeout(() => setCount(c => Math.min(c + 1, events.length)), delay)
    return () => clearTimeout(t)
  }, [count, events.length])

  return useMemo(() => events.slice(0, count), [events, count])
}

// ── coalescing ──────────────────────────────────────────────────────────────
// Twelve consecutive edits to one file read as noise; one row ×12 reads as work.

interface FeedRow {
  event: LivingUIBuildEvent
  count: number
}

// Only collapse repeated writes/edits to the SAME file — reads, searches,
// runs, verifies and todo milestones are distinct steps and each gets its
// own row so the feed reads as a running narrative.
const COALESCE_KINDS = new Set(['file_write', 'file_edit'])

function coalesce(events: LivingUIBuildEvent[]): FeedRow[] {
  const rows: FeedRow[] = []
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

// ── code peek ───────────────────────────────────────────────────────────────

function CodePeek({ file, snippet }: { file: string; snippet: string }) {
  const [chars, setChars] = useState(0)
  const preRef = useRef<HTMLPreElement>(null)

  useEffect(() => setChars(0), [snippet])
  useEffect(() => {
    if (chars >= snippet.length) return
    const t = setTimeout(() => setChars(c => Math.min(c + 4, snippet.length)), 16)
    return () => clearTimeout(t)
  }, [chars, snippet])
  useEffect(() => {
    if (preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight
  }, [chars])

  return (
    <div className={styles.codePeek}>
      <div className={styles.codePeekFile}>{file}</div>
      <pre ref={preRef} className={styles.codePeekBody}>
        {snippet.slice(0, chars)}
        {chars < snippet.length && <span className={styles.codePeekCursor}>▌</span>}
      </pre>
    </div>
  )
}

// ── feed icons ──────────────────────────────────────────────────────────────

const AREA_ICONS: Record<LivingUIBuildEvent['area'], JSX.Element> = {
  backend: <Server size={13} />,
  frontend: <PanelsTopLeft size={13} />,
  tests: <FlaskConical size={13} />,
  docs: <FileText size={13} />,
  config: <Package size={13} />,
  other: <Package size={13} />,
}

// Kind-specific icons for the activity events; file writes/edits fall back to
// the area icon (backend/frontend/…).
const KIND_ICONS: Partial<Record<LivingUIBuildEvent['kind'], JSX.Element>> = {
  read: <Eye size={13} />,
  search: <Search size={13} />,
  run: <Terminal size={13} />,
  verify: <MonitorPlay size={13} />,
  todo: <ListChecks size={13} />,
}

function eventIcon(e: LivingUIBuildEvent): JSX.Element {
  if (e.kind === 'test_run') {
    return e.tests && e.tests.failed > 0 ? (
      <XCircle size={13} className={styles.feedIconFail} />
    ) : (
      <CheckCircle2 size={13} className={styles.feedIconPass} />
    )
  }
  return KIND_ICONS[e.kind] ?? AREA_ICONS[e.area] ?? AREA_ICONS.other
}

// ── summary chip with a game-style "+N" pop on increase ─────────────────────

function PoppingChip({
  value,
  className,
  children,
}: {
  value: number
  className?: string
  children: ReactNode
}) {
  const prev = useRef(0) // starts at 0 so the first appearance also pops
  const idRef = useRef(0)
  const timers = useRef<number[]>([])
  const [pops, setPops] = useState<{ id: number; delta: number }[]>([])
  const [bump, setBump] = useState(false)

  useEffect(() => () => { timers.current.forEach(t => clearTimeout(t)) }, [])

  useEffect(() => {
    if (value <= prev.current) {
      prev.current = value
      return
    }
    const delta = value - prev.current
    prev.current = value
    const id = ++idRef.current
    setPops(p => [...p, { id, delta }])
    setBump(true)
    timers.current.push(
      window.setTimeout(() => setPops(p => p.filter(x => x.id !== id)), 1500),
      window.setTimeout(() => setBump(false), 300),
    )
  }, [value])

  return (
    <span className={`${styles.railChip} ${styles.chipPoppable} ${bump ? styles.chipBump : ''} ${className ?? ''}`}>
      {children}
      {pops.map(p => (
        <span key={p.id} className={styles.chipPop}>+{p.delta}</span>
      ))}
    </span>
  )
}

// ── main view ───────────────────────────────────────────────────────────────

export function ConstructionDock({ project, todos, events, snapshot }: Props) {
  const displayed = usePacedEvents(events)
  const view = useMemo(() => deriveProgress(todos), [todos])
  const isLaunching = project.status !== 'creating'

  // Built-so-far chips: counts come from the persisted authoritative snapshot
  // (backend disk scan, stored in the slice so it survives event eviction).
  const summary = {
    components: snapshot?.components ?? 0,
    collections: snapshot?.collections ?? 0,
    routes: snapshot?.routes ?? 0,
  }

  const latestSnippet = useMemo(() => {
    for (let i = displayed.length - 1; i >= 0; i--) {
      const e = displayed[i]
      if (e.snippet && e.file) return { file: e.file, snippet: e.snippet }
    }
    return null
  }, [displayed])

  const feed = useMemo(() => coalesce(displayed).slice(-5).reverse(), [displayed])

  const activityLabel =
    view.todoLabel ||
    (isLaunching ? 'Final checks…' : 'Preparing your workspace…')

  const hasSummary =
    summary.collections > 0 ||
    summary.routes > 0 ||
    summary.components > 0

  return (
    <div className={styles.constructionDockCenter}>
      <div className={styles.dock}>
        <div className={styles.dockHeader}>
          <span className={styles.dockTitle}>
            {isLaunching ? (
              <>
                <Rocket size={13} /> Launching {project.name}
              </>
            ) : (
              <>Creating {project.name}</>
            )}
          </span>
        </div>

        <div className={styles.progressBar}>
          <div
            className={`${styles.progressFill} ${view.indeterminate ? styles.indeterminate : ''}`}
            style={view.indeterminate ? undefined : { width: `${view.progress}%` }}
          />
        </div>

        <p className={styles.dockCurrent}>{activityLabel}</p>

        {hasSummary && (
          <div className={styles.railChips}>
            {summary.components > 0 && (
              <PoppingChip value={summary.components}>
                <PanelsTopLeft size={11} /> {summary.components} component{summary.components > 1 ? 's' : ''}
              </PoppingChip>
            )}
            {summary.collections > 0 && (
              <PoppingChip value={summary.collections}>
                <Server size={11} /> {summary.collections} collection{summary.collections > 1 ? 's' : ''}
              </PoppingChip>
            )}
            {summary.routes > 0 && (
              <PoppingChip value={summary.routes}>
                <Package size={11} /> {summary.routes} route{summary.routes > 1 ? 's' : ''}
              </PoppingChip>
            )}
          </div>
        )}

        <div className={styles.dockSwapIn}>
          {feed.length > 0 && (
            <div className={styles.railFeed}>
              {feed.map(({ event: e, count }) => (
                <div key={e.id} className={styles.feedItem}>
                  <span className={styles.feedIcon}>{eventIcon(e)}</span>
                  <span className={styles.feedLabel}>{e.label}</span>
                  {count > 1 && <span className={styles.feedCount}>×{count}</span>}
                </div>
              ))}
            </div>
          )}

          {latestSnippet && (
            <CodePeek file={latestSnippet.file} snippet={latestSnippet.snippet} />
          )}
        </div>
      </div>

      {/* Mascot keeps the user company at the bottom of the page while the
          app is being built (same character as the New Chat hero). */}
      <div className={styles.dockMascot}>
        <DraftMascot size={60} />
      </div>
    </div>
  )
}
