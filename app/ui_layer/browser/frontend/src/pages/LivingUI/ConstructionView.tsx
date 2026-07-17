/**
 * ConstructionView — the Live Construction View shown while a Living UI is
 * being created (and through its launch).
 *
 * The app fills the whole pane, served from a Vite dev server whose Staged
 * Reveal Engine (template devBuildMode.ts) choreographs every new element
 * into view — layout blocks first, then buttons/inputs/headings fading in
 * one by one — regardless of how the agent wrote the code. Before the dev
 * server is up, a calm branded canvas holds the space.
 *
 * One progress surface: the floating dock (lower third). It shows step
 * progress, built-so-far chips, a paced+coalesced build feed, the live code
 * being written, and — via 'craftbot-dev-reveal' messages from the engine —
 * a narration line naming what is being placed on screen right now.
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
import type { LivingUIProject, LivingUIBuildEvent, LivingUITodo } from '../../types'
import { getOrCreateIframe, showIframe, hideIframe, getIframeWindow } from './iframePool'
import { getSocketClient } from '../../store/socket/socketInstance'
import styles from './LivingUIPage.module.css'

interface Props {
  project: LivingUIProject
  todos: LivingUITodo[] | undefined
  events: LivingUIBuildEvent[]
}

export function devIframeKey(projectId: string): string {
  return `${projectId}::dev`
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

const NARRATION_TTL_MS = 4000

// ── component showcase (dock stage) ─────────────────────────────────────────
// Rendered components arrive from the dev-iframe reveal engine
// ('craftbot-dev-component') and play sequentially in the dock, taking the
// place of the feed rows + code snippet. Components outrank code.

interface ShowcaseItem {
  id: number
  dataUrl: string
  width: number
  height: number
  /** On-screen size of the captured element — displayed at this size or
   * smaller (never zoomed). */
  cssWidth: number
  cssHeight: number
  label: string
}

// Each component stays on stage long enough to actually SEE it; a full
// burst (engine caps at 5) plays out in under ~45s.
const SHOWCASE_DISPLAY_MS = 8000
// Backlog cap — beyond this the oldest unshown drop (the live preview
// already contains them).
const SHOWCASE_QUEUE_MAX = 8

export function ConstructionView({ project, todos, events }: Props) {
  const displayed = usePacedEvents(events)

  // The todo list is THE progress display: bar fill and "Step N of M" —
  // requirements live in the task instruction now, not in a tracked ledger.
  const view = useMemo(() => deriveProgress(todos), [todos])
  const stepLabel = view.stepLabel
  const previewRef = useRef<HTMLDivElement>(null)
  const [hmrStatus, setHmrStatus] = useState<'ok' | 'updating' | 'error'>('ok')
  const [narration, setNarration] = useState<{ label: string; at: number } | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [showcase, setShowcase] = useState<ShowcaseItem | null>(null)
  const showcaseQueue = useRef<ShowcaseItem[]>([])
  const showcaseIdRef = useRef(0)
  const devKey = devIframeKey(project.id)
  const isLaunching = project.status !== 'creating'

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

  // Never show the untouched template scaffold: the live iframe appears only
  // once the agent's first frontend change exists (the wireframe is the
  // first frontend write, so the first thing ever shown is the styled app).
  // Uses the raw event list, not the paced one — a page refresh mid-build
  // must not re-hide a preview that was already visible.
  const frontendTouched = useMemo(
    () => events.some(e => e.area === 'frontend'),
    [events],
  )
  const showPreview = !!project.devUrl && (frontendTouched || isLaunching)

  // Activity line priority: what's being placed on screen right now
  // (engine narration) > the agent's current todo > waiting message.
  const [, forceTick] = useState(0)
  useEffect(() => {
    if (!narration) return
    const t = setTimeout(() => forceTick(x => x + 1), NARRATION_TTL_MS + 100)
    return () => clearTimeout(t)
  }, [narration])
  const narrationFresh = narration && Date.now() - narration.at < NARRATION_TTL_MS
  const activityLabel = narrationFresh
    ? narration!.label
    : view.todoLabel ||
      (showPreview ? 'Working…' : 'Preparing your workspace…')

  // Dev-preview iframe, pooled under a dev-specific key.
  useEffect(() => {
    if (!project.devUrl || !showPreview) {
      hideIframe(devKey)
      return
    }
    getOrCreateIframe(devKey, project.devUrl)
    const update = () => {
      if (previewRef.current) {
        showIframe(devKey, previewRef.current.getBoundingClientRect())
      }
    }
    const observer = new ResizeObserver(update)
    if (previewRef.current) observer.observe(previewRef.current)
    window.addEventListener('resize', update)
    update()
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
      hideIframe(devKey)
    }
  }, [devKey, project.devUrl, showPreview])

  // Showcase player: each component holds the stage for SHOWCASE_DISPLAY_MS,
  // then the next queued one takes over; empty queue → code snippet returns.
  useEffect(() => {
    if (!showcase) return
    const t = setTimeout(() => {
      setShowcase(showcaseQueue.current.shift() ?? null)
    }, SHOWCASE_DISPLAY_MS)
    return () => clearTimeout(t)
  }, [showcase])

  // Messages from the engine: HMR status (rebuild shimmer / error veil) and
  // reveal narration (activity line).
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.source !== getIframeWindow(devKey)) return
      if (e.data?.type === 'craftbot-dev-hmr') {
        const status = e.data.status
        if (status === 'ok' || status === 'updating' || status === 'error') {
          setHmrStatus(status)
        }
      } else if (e.data?.type === 'craftbot-dev-reveal') {
        if (typeof e.data.label === 'string' && e.data.label) {
          setNarration({ label: e.data.label, at: Date.now() })
        }
      } else if (e.data?.type === 'craftbot-dev-component') {
        // A freshly built component, rasterized by the reveal engine.
        if (
          typeof e.data.dataUrl === 'string' &&
          e.data.dataUrl.startsWith('data:image/')
        ) {
          const item: ShowcaseItem = {
            id: ++showcaseIdRef.current,
            dataUrl: e.data.dataUrl,
            width: Number(e.data.width) || 0,
            height: Number(e.data.height) || 0,
            cssWidth: Number(e.data.cssWidth) || Number(e.data.width) || 0,
            cssHeight: Number(e.data.cssHeight) || Number(e.data.height) || 0,
            label: typeof e.data.label === 'string' ? e.data.label : '',
          }
          showcaseQueue.current.push(item)
          if (showcaseQueue.current.length > SHOWCASE_QUEUE_MAX) {
            showcaseQueue.current.splice(
              0,
              showcaseQueue.current.length - SHOWCASE_QUEUE_MAX,
            )
          }
          // Start playing immediately if the stage is free.
          setShowcase(cur => cur ?? showcaseQueue.current.shift() ?? null)
        }
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [devKey, project.id])

  return (
    <div className={styles.construction}>
      <div className={styles.constructionPreview}>
        {showPreview ? (
          <>
            <div ref={previewRef} className={styles.constructionIframe} />
            {/* On build errors the iframe keeps showing the last working
                state (Vite overlay disabled, engine snapshot fallback) —
                never cover it, just show the same rebuild shimmer. */}
            {hmrStatus !== 'ok' && <div className={styles.rebuildBar} />}
          </>
        ) : (
          <div className={styles.waitingCanvas}>
            <span className={styles.waitingName}>{project.name}</span>
          </div>
        )}
      </div>

      {/* The single progress surface: floating dock, lower third */}
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

            {(summary.models.size > 0 ||
              summary.routes.size > 0 ||
              summary.components.size > 0 ||
              summary.tests) && (
              <div className={styles.railChips}>
                {summary.components.size > 0 && (
                  <span className={styles.railChip}>
                    <PanelsTopLeft size={11} /> {summary.components.size} component{summary.components.size > 1 ? 's' : ''}
                  </span>
                )}
                {summary.models.size > 0 && (
                  <span className={styles.railChip}>
                    <Server size={11} /> {summary.models.size} model{summary.models.size > 1 ? 's' : ''}
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

            {showcase ? (
              /* A freshly built component holds the stage — the feed rows and
                 code snippet step aside; key remount replays the entrance. */
              <div key={showcase.id} className={styles.showcasePane}>
                {/* Original on-screen size or smaller — the max-* rules in
                    CSS cap it to the stage; never zoomed up. */}
                <img
                  className={styles.showcaseImg}
                  src={showcase.dataUrl}
                  alt={showcase.label || 'New component'}
                  draggable={false}
                  style={
                    showcase.cssWidth > 0
                      ? { width: showcase.cssWidth }
                      : undefined
                  }
                />
                <span className={styles.showcaseCaption}>
                  {showcase.label ? `Built: ${showcase.label}` : 'New component'}
                </span>
              </div>
            ) : (
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
            )}
          </>
        )}
      </div>
    </div>
  )
}
