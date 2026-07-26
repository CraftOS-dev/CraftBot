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

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Server,
  PanelsTopLeft,
  FlaskConical,
  FileText,
  Package,
  Rocket,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type { LivingUIProject, LivingUIBuildEvent } from '../../types'
import type { LivingUITodo } from '../../store/slices/livingUiSlice'
import styles from './LivingUIPage.module.css'

interface Props {
  project: LivingUIProject
  todos: LivingUITodo[] | undefined
  events: LivingUIBuildEvent[]
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
  stepLabel: string
  indeterminate: boolean
}

function deriveProgress(todos: LivingUITodo[] | undefined): ProgressView {
  const list = todos ?? []
  if (list.length === 0) {
    return { progress: 0, todoLabel: '', stepLabel: 'Planning', indeterminate: true }
  }
  const completed = list.filter(t => t.status === 'completed').length
  const inProgress = list.find(t => t.status === 'in_progress') ?? null
  const currentIdx = inProgress ? list.findIndex(t => t.id === inProgress.id) : completed
  return {
    progress: (completed / list.length) * 100,
    todoLabel: cleanLabel(inProgress?.active_form) || cleanLabel(inProgress?.content),
    stepLabel: `Step ${Math.min(currentIdx + 1, list.length)} of ${list.length}`,
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

function coalesce(events: LivingUIBuildEvent[]): FeedRow[] {
  const rows: FeedRow[] = []
  for (const e of events) {
    const last = rows[rows.length - 1]
    const key = `${e.kind}:${e.file ?? e.area}`
    const lastKey = last ? `${last.event.kind}:${last.event.file ?? last.event.area}` : null
    if (last && key === lastKey) {
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

function eventIcon(e: LivingUIBuildEvent): JSX.Element {
  if (e.kind === 'test_run') {
    return e.tests && e.tests.failed > 0 ? (
      <XCircle size={13} className={styles.feedIconFail} />
    ) : (
      <CheckCircle2 size={13} className={styles.feedIconPass} />
    )
  }
  return AREA_ICONS[e.area] ?? AREA_ICONS.other
}

// ── main view ───────────────────────────────────────────────────────────────

export function ConstructionDock({ project, todos, events }: Props) {
  const displayed = usePacedEvents(events)
  const view = useMemo(() => deriveProgress(todos), [todos])
  const [collapsed, setCollapsed] = useState(false)
  const isLaunching = project.status !== 'creating'
  const stepLabel = view.stepLabel

  // Built-so-far chips, aggregated over the revealed feed.
  const summary = useMemo(() => {
    const models = new Set<string>()
    const routes = new Set<string>()
    const components = new Set<string>()
    let tests: { passed: number; failed: number } | null = null
    for (const e of displayed) {
      e.entities?.models?.forEach(m => models.add(m))
      e.entities?.routes?.forEach(r => routes.add(r))
      e.entities?.components?.forEach(c => components.add(c))
      if (e.kind === 'test_run' && e.tests) tests = e.tests
    }
    return { models, routes, components, tests }
  }, [displayed])

  const latestSnippet = useMemo(() => {
    for (let i = displayed.length - 1; i >= 0; i--) {
      const e = displayed[i]
      if (e.snippet && e.file) return { file: e.file, snippet: e.snippet }
    }
    return null
  }, [displayed])

  const feed = useMemo(() => coalesce(displayed).slice(-3).reverse(), [displayed])

  const activityLabel =
    view.todoLabel ||
    (isLaunching ? 'Final checks…' : 'Preparing your workspace…')

  const hasSummary =
    summary.models.size > 0 ||
    summary.routes.size > 0 ||
    summary.components.size > 0 ||
    !!summary.tests

  return (
    <div className={styles.constructionDockCenter}>
      <div className={`${styles.dock} ${collapsed ? styles.dockCollapsed : ''}`}>
        {collapsed ? (
          <button
            type="button"
            className={styles.dockPill}
            onClick={() => setCollapsed(false)}
            title="Show build progress"
          >
            <span className={styles.dockPillBar}>
              <span
                className={`${styles.progressFill} ${view.indeterminate ? styles.indeterminate : ''}`}
                style={view.indeterminate ? undefined : { width: `${view.progress}%` }}
              />
            </span>
            <span className={styles.dockPillLabel}>
              {isLaunching ? 'Launching…' : stepLabel}
            </span>
            <ChevronUp size={14} />
          </button>
        ) : (
          <>
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
              <span className={styles.dockStep}>
                {isLaunching ? 'Final checks' : stepLabel}
              </span>
              <span className={styles.dockButtons}>
                <button
                  type="button"
                  className={styles.dockIconBtn}
                  onClick={() => setCollapsed(true)}
                  title="Minimize"
                >
                  <ChevronDown size={14} />
                </button>
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
                {summary.components.size > 0 && (
                  <span className={styles.railChip}>
                    <PanelsTopLeft size={11} /> {summary.components.size} component{summary.components.size > 1 ? 's' : ''}
                  </span>
                )}
                {summary.models.size > 0 && (
                  <span className={styles.railChip}>
                    <Server size={11} /> {summary.models.size} collection{summary.models.size > 1 ? 's' : ''}
                  </span>
                )}
                {summary.routes.size > 0 && (
                  <span className={styles.railChip}>
                    <Package size={11} /> {summary.routes.size} route{summary.routes.size > 1 ? 's' : ''}
                  </span>
                )}
                {summary.tests && (
                  <span
                    className={`${styles.railChip} ${summary.tests.failed ? styles.railChipFail : styles.railChipPass}`}
                  >
                    <FlaskConical size={11} /> {summary.tests.passed} passed
                    {summary.tests.failed ? `, ${summary.tests.failed} failed` : ''}
                  </span>
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
          </>
        )}
      </div>
    </div>
  )
}
