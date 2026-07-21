import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { ChevronRight, XCircle, CheckCircle, ArrowLeft, Reply, Plus, Loader2, RotateCw, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { StatusIndicator, Badge, Button, IconButton, SkillCreatorModal } from '../../components/ui'
import type { ActionItem } from '../../types'
import { useSkillCreator } from './useSkillCreator'
import { getActivePlaceholder, type ActivePlaceholder } from '../../utils/taskPlaceholder'
import { isEndedStatus } from '../../utils/taskStatus'
import { useTaskListAutoScroll, useTaskListFLIP } from '../../hooks'
import { getActionRenderer, parseIO } from './actionRenderers/renderers'
import styles from './TasksPage.module.css'

function isInternalWorkflowTask(
  item: ActionItem,
  internalWorkflowIds: Set<string>,
  internalSkillNames: Set<string>,
): boolean {
  if (item.workflowId && internalWorkflowIds.has(item.workflowId)) return true
  for (const s of item.selectedSkills ?? []) {
    if (internalSkillNames.has(s)) return true
  }
  return false
}

// Expandable value component for long text
const MAX_VALUE_LENGTH = 80

function ExpandableValue({ value }: { value: string }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = value.length > MAX_VALUE_LENGTH

  if (!isLong) {
    return <>{value}</>
  }

  return (
    <span className={styles.expandableValue}>
      <span>{expanded ? value : value.substring(0, MAX_VALUE_LENGTH) + '...'}</span>
      <button
        className={styles.expandButton}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? 'Show less' : 'Show more'}
      </button>
    </span>
  )
}

// JSON Viewer Component - displays data in Details-style grid layout
interface JsonViewerProps {
  data: unknown
  depth?: number
}

function JsonViewer({ data, depth = 0 }: JsonViewerProps) {
  // Format a primitive value for display
  const formatValue = (value: unknown): string => {
    if (value === null) return 'null'
    if (value === undefined) return 'undefined'
    if (typeof value === 'boolean') return value.toString()
    if (typeof value === 'number') return value.toString()
    if (typeof value === 'string') return value
    return String(value)
  }

  // Check if value is an object or array
  const isComplex = (value: unknown): boolean => {
    return value !== null && typeof value === 'object'
  }

  // Render a value (with expandable support for long strings)
  const renderValue = (value: unknown) => {
    const strValue = formatValue(value)
    return <ExpandableValue value={strValue} />
  }

  // Render array items
  if (Array.isArray(data)) {
    if (data.length === 0) {
      return (
        <>
          <dt>items</dt>
          <dd>Empty list</dd>
        </>
      )
    }

    return (
      <>
        {data.map((item, index) => {
          const isItemComplex = isComplex(item)
          return (
            <React.Fragment key={index}>
              <dt>[{index}]</dt>
              {isItemComplex ? (
                <dd>
                  <dl className={styles.nestedList}>
                    <JsonViewer data={item} depth={depth + 1} />
                  </dl>
                </dd>
              ) : (
                <dd>{renderValue(item)}</dd>
              )}
            </React.Fragment>
          )
        })}
      </>
    )
  }

  // Render object entries
  if (typeof data === 'object' && data !== null) {
    const entries = Object.entries(data)
    if (entries.length === 0) {
      return (
        <>
          <dt>data</dt>
          <dd>Empty object</dd>
        </>
      )
    }

    return (
      <>
        {entries.map(([key, value]) => {
          const isValueComplex = isComplex(value)
          return (
            <React.Fragment key={key}>
              <dt>{key}</dt>
              {isValueComplex ? (
                <dd>
                  <dl className={styles.nestedList}>
                    <JsonViewer data={value} depth={depth + 1} />
                  </dl>
                </dd>
              ) : (
                <dd>{renderValue(value)}</dd>
              )}
            </React.Fragment>
          )
        })}
      </>
    )
  }

  // Primitive value at root level
  return (
    <>
      <dt>value</dt>
      <dd>{renderValue(data)}</dd>
    </>
  )
}

// Parse Python dict string to object
function parsePythonDict(content: string): Record<string, unknown> {
  // Try JSON first
  try {
    return JSON.parse(content)
  } catch {
    // Parse Python dict syntax
  }

  const result: Record<string, unknown> = {}

  // Remove outer braces and trim
  let inner = content.trim()
  if (inner.startsWith('{') && inner.endsWith('}')) {
    inner = inner.slice(1, -1).trim()
  }

  // Parse key-value pairs
  // Handle: 'key': 'value', 'key2': "value2", 'key3': 123, 'key4': True
  let i = 0
  while (i < inner.length) {
    // Skip whitespace and commas
    while (i < inner.length && (inner[i] === ' ' || inner[i] === ',' || inner[i] === '\n')) i++
    if (i >= inner.length) break

    // Find key (single or double quoted)
    const keyQuote = inner[i]
    if (keyQuote !== "'" && keyQuote !== '"') {
      i++
      continue
    }
    i++ // skip opening quote

    let key = ''
    while (i < inner.length && inner[i] !== keyQuote) {
      if (inner[i] === '\\' && i + 1 < inner.length) {
        key += inner[i + 1]
        i += 2
      } else {
        key += inner[i]
        i++
      }
    }
    i++ // skip closing quote

    // Skip colon and whitespace
    while (i < inner.length && (inner[i] === ':' || inner[i] === ' ')) i++

    // Parse value
    if (i >= inner.length) break

    let value: unknown
    const valueStart = inner[i]

    if (valueStart === "'" || valueStart === '"') {
      // String value
      i++ // skip opening quote
      let strValue = ''
      while (i < inner.length && inner[i] !== valueStart) {
        if (inner[i] === '\\' && i + 1 < inner.length) {
          const nextChar = inner[i + 1]
          if (nextChar === 'n') strValue += '\n'
          else if (nextChar === 't') strValue += '\t'
          else if (nextChar === 'r') strValue += '\r'
          else strValue += nextChar
          i += 2
        } else {
          strValue += inner[i]
          i++
        }
      }
      i++ // skip closing quote
      value = strValue
    } else if (valueStart === '{') {
      // Nested dict - find matching brace
      let braceCount = 1
      let start = i
      i++
      while (i < inner.length && braceCount > 0) {
        if (inner[i] === '{') braceCount++
        else if (inner[i] === '}') braceCount--
        i++
      }
      value = parsePythonDict(inner.slice(start, i))
    } else if (valueStart === '[') {
      // Array - find matching bracket
      let bracketCount = 1
      let start = i
      i++
      while (i < inner.length && bracketCount > 0) {
        if (inner[i] === '[') bracketCount++
        else if (inner[i] === ']') bracketCount--
        i++
      }
      // Simple array parsing - just store as string for now
      value = inner.slice(start, i)
    } else {
      // Number, boolean, None
      let rawValue = ''
      while (i < inner.length && inner[i] !== ',' && inner[i] !== '}') {
        rawValue += inner[i]
        i++
      }
      rawValue = rawValue.trim()
      if (rawValue === 'True') value = true
      else if (rawValue === 'False') value = false
      else if (rawValue === 'None') value = null
      else if (!isNaN(Number(rawValue))) value = Number(rawValue)
      else value = rawValue
    }

    if (key) {
      result[key] = value
    }
  }

  return result
}

// Parse content and render as a detail list (always grid format)
function JsonDisplay({ content }: { content: string }) {
  const parsed = parsePythonDict(content)

  return (
    <dl className={styles.detailList}>
      <JsonViewer data={parsed} />
    </dl>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

function formatDuration(ms?: number): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  return `${minutes}m ${seconds}s`
}

function formatTimestamp(ts?: number): string {
  if (!ts) return '-'
  return new Date(ts).toLocaleString()
}

// Returns the duration to display: the completed duration if available,
// otherwise the live elapsed time since createdAt for running items.
function getElapsedMs(item: ActionItem): number | undefined {
  if (item.duration != null) return item.duration
  if ((item.status === 'running' || item.status === 'waiting') && item.createdAt) {
    return Date.now() - item.createdAt
  }
  return undefined
}

// Heuristic: does the content look like a structured dict/array?
function looksStructured(content: string): boolean {
  const trimmed = content.trim()
  return (
    (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
    (trimmed.startsWith('[') && trimmed.endsWith(']'))
  )
}

// Renders streamed input/output. Structured content gets the JsonDisplay grid;
// plain text falls back to a code block so partial streams stay readable.
function ContentDisplay({ content }: { content: string }) {
  if (looksStructured(content)) return <JsonDisplay content={content} />
  return <pre className={styles.contentText}>{content}</pre>
}

// ─────────────────────────────────────────────────────────────────────
// Transcript blocks
// ─────────────────────────────────────────────────────────────────────

function ReasoningBlock({ item }: { item: ActionItem }) {
  return (
    <div id={`transcript-item-${item.id}`} className={styles.transcriptItem}>
      <div className={styles.gutter}>
        <div className={styles.gutterIcon}>
          <div className={styles.reasoningCircle} aria-hidden="true" />
        </div>
      </div>
      <div className={styles.reasoningContent}>
        {item.output
          ? item.output
          : <span className={styles.reasoningPlaceholder}>Thinking…</span>}
      </div>
    </div>
  )
}

interface ActionBlockProps {
  item: ActionItem
  expanded: boolean
  onToggleDetail: () => void
}

function ActionBlock({ item, expanded, onToggleDetail }: ActionBlockProps) {
  const { openFile } = useWebSocket()
  const elapsed = getElapsedMs(item)

  // Look up a custom renderer for this action. If one is registered it
  // replaces the generic Input/Output sections with a tailored view (diff
  // for stream_edit, terminal for run_python, image grid for generate_image,
  // …); otherwise we fall back to the structured JSON / plain-text display.
  const Renderer = getActionRenderer(item.name)
  const { inputObj, outputObj } = Renderer ? parseIO(item) : { inputObj: null, outputObj: null }

  return (
    <div id={`transcript-item-${item.id}`} className={styles.transcriptItem}>
      <div className={styles.gutter}>
        <div className={styles.gutterIcon}>
          <StatusIndicator status={item.status} size="sm" />
        </div>
      </div>
      <div className={styles.actionContent}>
        <div className={styles.actionHeader}>
          <span className={styles.actionName}>{item.name}</span>
          {elapsed != null && (
            <span className={styles.actionDuration}>
              {formatDuration(elapsed)}
            </span>
          )}
        </div>

        <div className={styles.actionBox}>
          {Renderer ? (
            <Renderer
              item={item}
              inputObj={inputObj}
              outputObj={outputObj}
              onOpenFile={openFile}
            />
          ) : (
            <>
              {item.input && (
                <div className={styles.actionSection}>
                  <div className={styles.ioLabel}>Input</div>
                  <ContentDisplay content={item.input} />
                </div>
              )}

              {item.output && (
                <div className={styles.actionSection}>
                  <div className={styles.ioLabel}>Output</div>
                  <ContentDisplay content={item.output} />
                </div>
              )}
            </>
          )}

          {item.error && (
            <div className={styles.actionSection}>
              <div className={styles.ioLabel}>Error</div>
              <pre className={`${styles.codeBlock} ${styles.errorBlock}`}>{item.error}</pre>
            </div>
          )}

          <div className={styles.actionMoreRow}>
            <button
              className={styles.moreDetailBtn}
              onClick={onToggleDetail}
              aria-expanded={expanded}
            >
              <ChevronRight
                size={12}
                className={`${styles.moreDetailChevron} ${expanded ? styles.expanded : ''}`}
              />
              {expanded ? 'Hide details' : 'More detail'}
            </button>
          </div>

          {expanded && (
            <div className={styles.actionSection}>
              <dl className={`${styles.detailList} ${styles.actionDetailList}`}>
                <dt>Type</dt>
                <dd>{item.itemType}</dd>
                <dt>ID</dt>
                <dd className={styles.mono}>{item.id}</dd>
                <dt>Started</dt>
                <dd>{formatTimestamp(item.createdAt)}</dd>
                <dt>Duration</dt>
                <dd>{formatDuration(item.duration)}</dd>
              </dl>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Trailing placeholder rendered at the end of the transcript while the task
// is still active (Thinking / Waiting for reply / Paused). Shows an
// always-visible reply icon-button when the task is awaiting a user reply.
interface TranscriptPlaceholderProps {
  placeholder: ActivePlaceholder
  showReply: boolean
  onReply: () => void
}

function TranscriptPlaceholder({ placeholder, showReply, onReply }: TranscriptPlaceholderProps) {
  return (
    <div className={styles.transcriptItem}>
      <div className={styles.gutter}>
        <div className={styles.gutterIcon}>
          <StatusIndicator status={placeholder.status} size="sm" />
        </div>
      </div>
      <div className={`${styles.reasoningContent} ${styles.placeholderRow}`}>
        <span className={styles.reasoningPlaceholder}>{placeholder.label}</span>
        {showReply && (
          <IconButton
            size="sm"
            variant="ghost"
            className={styles.placeholderReplyBtn}
            onClick={onReply}
            title="Reply to Task"
            icon={<Reply size={12} />}
          />
        )}
      </div>
    </div>
  )
}

// Scrollable body of the detail panel: chronological list of reasoning +
// action items, with a trailing active-state placeholder while the task is
// still running/waiting/paused.
interface TaskTranscriptProps {
  task: ActionItem
  items: ActionItem[]
  expandedDetailIds: Set<string>
  onToggleDetail: (id: string) => void
  tasksAwaitingOption: Set<string>
  onTaskReply: (task: ActionItem) => void
}

function TaskTranscript({
  task,
  items,
  expandedDetailIds,
  onToggleDetail,
  tasksAwaitingOption,
  onTaskReply,
}: TaskTranscriptProps) {
  const placeholder = getActivePlaceholder(task.status, items)

  if (items.length === 0 && !placeholder) {
    return (
      <div className={styles.emptyTranscript}>
        No actions or reasoning recorded.
      </div>
    )
  }

  const showReply =
    placeholder?.status === 'waiting' && !tasksAwaitingOption.has(task.id)

  return (
    <div className={styles.transcript}>
      {items.map(item =>
        item.itemType === 'reasoning' ? (
          <ReasoningBlock key={item.id} item={item} />
        ) : (
          <ActionBlock
            key={item.id}
            item={item}
            expanded={expandedDetailIds.has(item.id)}
            onToggleDetail={() => onToggleDetail(item.id)}
          />
        )
      )}
      {placeholder && (
        <TranscriptPlaceholder
          placeholder={placeholder}
          showReply={showReply}
          onReply={() => onTaskReply(task)}
        />
      )}
    </div>
  )
}

// Panel width limits (1:3 ratio default)
const DEFAULT_PANEL_WIDTH = 350
const MIN_PANEL_WIDTH = 200
const MAX_PANEL_WIDTH = 600

export function TasksPage() {
  const { actions, messages, cancelTask, cancellingTaskId, completeTask, completingTaskId, resumeTask, resumingTaskId, deleteTask, deletingTaskId, setReplyTarget, loadOlderActions, hasMoreActions, loadingOlderActions, skillMeta } = useWebSocket()
  const internalWorkflowIds = useMemo(() => new Set(skillMeta.internalWorkflowIds), [skillMeta.internalWorkflowIds])
  const internalSkillNames = useMemo(() => new Set(skillMeta.internalSkillNames), [skillMeta.internalSkillNames])
  const reservedSkillNames = useMemo(() => new Set(skillMeta.reservedSkillNames), [skillMeta.reservedSkillNames])
  const navigate = useNavigate()

  // Body navigation state:
  //   selectedTaskId  — which task's transcript is shown in the body
  //   scrollTargetId  — child action/reasoning to scroll to; null = scroll to latest
  //   expandedDetailIds — action ids whose "More detail" panel is open
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [scrollTargetId, setScrollTargetId] = useState<string | null>(null)
  const [expandedDetailIds, setExpandedDetailIds] = useState<Set<string>>(new Set())
  const [mobileShowDetail, setMobileShowDetail] = useState(false)
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768
  )
  const skillCreator = useSkillCreator()

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Resizable panel state
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const listContentRef = useRef<HTMLDivElement>(null)
  // Tracks whether the user is currently following along near the bottom of
  // the transcript. Updated by the scroll listener; consulted by auto-follow.
  // Same pattern as the chat panel's wasNearBottomRef. (The list on the left
  // has its own copy of this state hidden inside useTaskListAutoScroll.)
  const wasNearBottomRef = useRef(true)
  // A counter we bump every second to re-render live durations for running items.
  const [, forceTick] = useState(0)

  // Split tasks into "in-progress" (running / waiting / paused / pending) and
  // "ended" (completed / error / cancelled). The active group is sorted
  // newest-first by createdAt so a freshly-started task appears at the top of
  // its section; the ended group is sorted newest-first by completedAt
  // (falling back to createdAt for rows persisted before that field existed)
  // so a task that just ended pops to the top of the ended section. The
  // combined `tasks` array keeps active-then-ended order so pagination counts
  // and selection lookups work unchanged.
  const { tasks, activeTasks, endedTasks } = useMemo(() => {
    const taskItems = actions.filter(a => a.itemType === 'task')
    const byNewestFirst = (a: ActionItem, b: ActionItem) => (b.createdAt ?? 0) - (a.createdAt ?? 0)
    const byNewestEnded = (a: ActionItem, b: ActionItem) =>
      (b.completedAt ?? b.createdAt ?? 0) - (a.completedAt ?? a.createdAt ?? 0)
    const active = taskItems.filter(t => !isEndedStatus(t.status)).sort(byNewestFirst)
    const ended = taskItems.filter(t => isEndedStatus(t.status)).sort(byNewestEnded)
    return { tasks: [...active, ...ended], activeTasks: active, endedTasks: ended }
  }, [actions])

  // Scroll behavior + scroll-to-top pagination for the All Tasks list.
  // Same hook as ChatPage's Tasks & Actions sidebar so the two behave
  // identically: initial jump to latest, auto-follow only while near the
  // bottom, and anchor-preserving prepend when older tasks load.
  useTaskListAutoScroll(listContentRef, tasks.length, {
    hasMore: hasMoreActions,
    loading: loadingOlderActions,
    loadMore: loadOlderActions,
  })

  // FLIP animates a task sliding from active → ended (or vice-versa) and the
  // surrounding rows shifting up/down to accommodate. Operates on whatever
  // <div> each row registers via `flipRef(task.id)`.
  const flipRef = useTaskListFLIP()

  const selectedTask = useMemo(
    () => tasks.find(t => t.id === selectedTaskId) ?? null,
    [tasks, selectedTaskId],
  )

  const transcriptItems = useMemo(() => {
    if (!selectedTaskId) return []
    return actions
      .filter(a => a.parentId === selectedTaskId && (a.itemType === 'action' || a.itemType === 'reasoning'))
      .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))
  }, [actions, selectedTaskId])

  // Tasks whose latest UX gate is an unanswered option prompt — the user
  // must click an option, so suppress the reply affordance for these.
  const tasksAwaitingOption = useMemo(() => {
    const ids = new Set<string>()
    for (const m of messages) {
      if (m.taskSessionId && m.options && m.options.length > 0 && !m.optionSelected) {
        ids.add(m.taskSessionId)
      }
    }
    return ids
  }, [messages])

  // Handle reply to task - set reply target and navigate to chat
  const handleTaskReply = useCallback((task: ActionItem) => {
    setReplyTarget({
      type: 'task',
      sessionId: task.id,
      displayName: task.name,
      originalContent: `Task: ${task.name}`,
    })
    navigate('/chat')
  }, [setReplyTarget, navigate])

  // Items shown inline beneath a task in the left list (actions + reasoning)
  const getItemsForTask = useCallback(
    (taskId: string) =>
      actions.filter(a => (a.itemType === 'action' || a.itemType === 'reasoning') && a.parentId === taskId),
    [actions],
  )

  // Action count per task (excludes reasoning) — used for the badge
  const getActionCountForTask = useCallback(
    (taskId: string) =>
      actions.filter(a => a.itemType === 'action' && a.parentId === taskId).length,
    [actions],
  )

  // Clicking a task or action in the left list drives the body's view.
  // Tasks → show that task, scroll to latest progress.
  // Actions/reasoning → show their parent task, scroll to the clicked item.
  const handleSelectFromList = useCallback((item: ActionItem) => {
    if (item.itemType === 'task') {
      // Desktop: tapping the already-selected task collapses its inline
      // actions. On mobile, list & detail are separate views, so a second
      // tap after returning from detail should re-open detail — not toggle
      // off, which would leave the user stranded on the empty state with
      // no way back to the list.
      if (selectedTaskId === item.id && !isMobile) {
        setSelectedTaskId(null)
        setScrollTargetId(null)
      } else {
        setSelectedTaskId(item.id)
        setScrollTargetId(null)
      }
    } else {
      setSelectedTaskId(item.parentId ?? null)
      setScrollTargetId(item.id)
    }
    setMobileShowDetail(true)
  }, [selectedTaskId, isMobile])

  const toggleDetailExpansion = useCallback((id: string) => {
    setExpandedDetailIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Scroll-position tracker (mirrors Chat.tsx). Maintains wasNearBottomRef so
  // auto-follow can tell at a glance whether the user is still "following
  // along" at the bottom or has scrolled up to inspect previous activity.
  useEffect(() => {
    const body = bodyRef.current
    if (!body) return
    const handleScroll = () => {
      const distFromBottom = body.scrollHeight - body.scrollTop - body.clientHeight
      wasNearBottomRef.current = distFromBottom < 100
    }
    body.addEventListener('scroll', handleScroll)
    return () => body.removeEventListener('scroll', handleScroll)
  }, [selectedTaskId])

  // Scroll to the target item (or to latest) when selection changes.
  useEffect(() => {
    if (!selectedTaskId) return
    const body = bodyRef.current
    if (!body) return
    // Wait a tick so the new transcript has rendered before measuring.
    const timer = setTimeout(() => {
      if (scrollTargetId) {
        const el = document.getElementById(`transcript-item-${scrollTargetId}`)
        if (el && bodyRef.current) {
          const bodyEl = bodyRef.current
          const bodyRect = bodyEl.getBoundingClientRect()
          const elRect = el.getBoundingClientRect()
          const offset = elRect.top - bodyRect.top + bodyEl.scrollTop - 16
          bodyEl.scrollTo({ top: offset, behavior: 'smooth' })
        }
        // Jumping mid-transcript counts as "not following the tail."
        wasNearBottomRef.current = false
      } else {
        body.scrollTo({ top: body.scrollHeight, behavior: 'smooth' })
        wasNearBottomRef.current = true
      }
    }, 60)
    return () => clearTimeout(timer)
  }, [selectedTaskId, scrollTargetId])

  // Auto-follow: when new transcript items arrive on an active task, stick to
  // the bottom only if the user was near the bottom. If they scrolled up to
  // look at previous activity, leave them where they are.
  useEffect(() => {
    if (!selectedTask) return
    if (selectedTask.status !== 'running' && selectedTask.status !== 'waiting') return
    if (!wasNearBottomRef.current) return
    const body = bodyRef.current
    if (!body) return
    body.scrollTo({ top: body.scrollHeight })
  }, [transcriptItems, selectedTask])

  // Live ticker for running item durations. 100ms keeps the "X.Xs" decimal
  // updating smoothly instead of jumping a second at a time.
  useEffect(() => {
    const hasRunning =
      (selectedTask?.status === 'running' || selectedTask?.status === 'waiting') ||
      transcriptItems.some(i => i.status === 'running' || i.status === 'waiting')
    if (!hasRunning) return
    const interval = setInterval(() => forceTick(t => t + 1), 100)
    return () => clearInterval(interval)
  }, [transcriptItems, selectedTask])

  // Handle back button on mobile
  const handleMobileBack = useCallback(() => {
    setMobileShowDetail(false)
  }, [])

  // Continue Task — mirrors the chat sidebar's resume icon: fire-and-forget,
  // no message input, then redirect back to chat so the user can watch the
  // task resume in the live transcript (same pattern as Reply to Task).
  const handleResumeTask = useCallback((task: ActionItem) => {
    resumeTask(task.id)
    navigate('/chat')
  }, [resumeTask, navigate])

  // Handle resize drag
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const containerRect = containerRef.current.getBoundingClientRect()
      // Calculate width from right edge (since panel is on the right)
      const newWidth = containerRect.right - e.clientX
      // Clamp to min/max limits
      const clampedWidth = Math.min(Math.max(newWidth, MIN_PANEL_WIDTH), MAX_PANEL_WIDTH)
      setPanelWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  const canCreateSkill =
    selectedTask?.status === 'completed' &&
    !isInternalWorkflowTask(selectedTask, internalWorkflowIds, internalSkillNames)

  return (
    <div className={`${styles.tasksPage} ${isResizing ? styles.resizing : ''}`} ref={containerRef}>
      {/* Task List - Right Side (resizable)
          Row rendering is its own implementation (drives a detail panel with
          scroll-target nav, action-count badges, action + reasoning
          children — ChatPage's sidebar is a stripped-down live view).
          Scroll + pagination behavior is shared via useTaskListAutoScroll
          so the two stay in sync.
          Visually positioned on the right via CSS `order` in the module — JSX
          order is preserved to keep the file readable. */}
      <div className={`${styles.taskList} ${mobileShowDetail ? styles.mobileHidden : ''}`} style={{ width: panelWidth, flexShrink: 0 }}>
        <div className={styles.listHeader}>
          <h3>All Tasks</h3>
          <Badge variant="default">{tasks.length}</Badge>
        </div>

        <div className={styles.listContent} ref={listContentRef}>
          {loadingOlderActions && (
            <div className={styles.loadingOlder}>
              <Loader2 size={14} className={styles.spinning} /> Loading older tasks...
            </div>
          )}
          {tasks.length === 0 ? (
            <div className={styles.emptyState}>
              <p>No tasks yet</p>
            </div>
          ) : (
            (() => {
              const renderTaskRow = (task: ActionItem) => {
                const taskItems = getItemsForTask(task.id)
                const actionCount = getActionCountForTask(task.id)
                const isCurrentTask = selectedTaskId === task.id
                const listPlaceholder = isCurrentTask
                  ? getActivePlaceholder(task.status, taskItems)
                  : null
                const showListReply =
                  listPlaceholder?.status === 'waiting' && !tasksAwaitingOption.has(task.id)

                return (
                  <div ref={flipRef(task.id)} className={styles.taskGroup}>
                    <button
                      className={`${styles.taskItem} ${isCurrentTask ? styles.selected : ''}`}
                      onClick={() => handleSelectFromList(task)}
                    >
                      <ChevronRight
                        size={14}
                        className={`${styles.chevron} ${isCurrentTask ? styles.expanded : ''}`}
                      />
                      <StatusIndicator status={task.status} size="sm" />
                      <span className={styles.itemName}>{task.name}</span>
                      {(task.status === 'running' || task.status === 'waiting') && !tasksAwaitingOption.has(task.id) && (
                        <IconButton
                          size="sm"
                          variant="ghost"
                          className={styles.taskReplyBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleTaskReply(task)
                          }}
                          title="Reply to Task"
                          icon={<Reply size={12} />}
                        />
                      )}
                      {(task.status === 'completed' || task.status === 'cancelled' || task.status === 'error') && (
                        <IconButton
                          size="sm"
                          variant="ghost"
                          className={styles.taskDeleteBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            deleteTask(task.id)
                          }}
                          disabled={deletingTaskId === task.id}
                          title="Delete Task"
                          icon={
                            deletingTaskId === task.id ? (
                              <Loader2 size={12} className={styles.spinning} />
                            ) : (
                              <Trash2 size={12} />
                            )
                          }
                        />
                      )}
                      <Badge variant="default">
                        {actionCount} actions
                      </Badge>
                    </button>

                    {isCurrentTask && (
                      <div className={styles.actionsList}>
                        {taskItems.map(action => (
                          <button
                            key={action.id}
                            className={`${styles.actionItem} ${action.itemType === 'reasoning' ? styles.reasoningItem : ''} ${scrollTargetId === action.id ? styles.selected : ''}`}
                            onClick={() => handleSelectFromList(action)}
                          >
                            {action.itemType !== 'reasoning' && (
                              <StatusIndicator status={action.status} size="sm" />
                            )}
                            <span className={styles.itemName}>{action.name}</span>
                          </button>
                        ))}
                        {listPlaceholder && (
                          <div className={styles.placeholderItem}>
                            <StatusIndicator status={listPlaceholder.status} size="sm" />
                            <span className={styles.itemName}>{listPlaceholder.label}</span>
                            {showListReply && (
                              <IconButton
                                size="sm"
                                variant="ghost"
                                className={styles.placeholderReplyBtn}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleTaskReply(task)
                                }}
                                title="Reply to Task"
                                icon={<Reply size={12} />}
                              />
                            )}
                          </div>
                        )}
                        {taskItems.length === 0 && !listPlaceholder && (
                          <div className={styles.noActions}>No actions yet</div>
                        )}
                      </div>
                    )}
                  </div>
                )
              }

              return (
                <>
                  {activeTasks.length === 0 && endedTasks.length > 0 && (
                    <div className={styles.emptyActiveSection}>No active task now...</div>
                  )}
                  {tasks.map((task, i) => {
                    // Divider sits above the first ended row whenever the
                    // ended section has rows — when active is empty, it sits
                    // below the "No active tasks" placeholder.
                    const showDivider = i === activeTasks.length
                    return (
                      <React.Fragment key={task.id}>
                        {showDivider && <div className={styles.sectionDivider} />}
                        {renderTaskRow(task)}
                      </React.Fragment>
                    )
                  })}
                </>
              )
            })()
          )}
        </div>
      </div>

      {/* Resize Handle */}
      <div className={styles.resizeHandle} onMouseDown={handleMouseDown} />

      {/* Detail Panel - Left Side */}
      <div className={`${styles.detailPanel} ${mobileShowDetail ? styles.mobileVisible : ''}`}>
        {selectedTask ? (
          <>
            {/* Header — task name + status + task-level actions */}
            <div className={styles.detailHeader}>
              <div className={styles.detailTitle}>
                <IconButton
                  icon={<ArrowLeft size={18} />}
                  variant="ghost"
                  className={styles.mobileBackBtn}
                  onClick={handleMobileBack}
                  tooltip="Back to list"
                />
                <StatusIndicator status={selectedTask.status} size="md" />
                <h2>{selectedTask.name}</h2>
              </div>
              <div className={styles.headerActions}>
                {(selectedTask.status === 'running' || selectedTask.status === 'waiting') ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<CheckCircle size={14} />}
                      loading={completingTaskId === selectedTask.id}
                      disabled={cancellingTaskId === selectedTask.id}
                      onClick={() => completeTask(selectedTask.id)}
                      className={styles.completeButton}
                    >
                      {completingTaskId === selectedTask.id ? 'Completing…' : 'Mark Complete'}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<XCircle size={14} />}
                      loading={cancellingTaskId === selectedTask.id}
                      disabled={completingTaskId === selectedTask.id}
                      onClick={() => cancelTask(selectedTask.id)}
                      className={styles.cancelButton}
                    >
                      {cancellingTaskId === selectedTask.id ? 'Cancelling…' : 'Cancel Task'}
                    </Button>
                  </>
                ) : (selectedTask.status === 'completed' || selectedTask.status === 'cancelled' || selectedTask.status === 'error') ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={
                        resumingTaskId === selectedTask.id ? (
                          <Loader2 size={14} className={styles.spinning} />
                        ) : (
                          <RotateCw size={14} />
                        )
                      }
                      loading={resumingTaskId === selectedTask.id}
                      disabled={resumingTaskId === selectedTask.id}
                      onClick={() => handleResumeTask(selectedTask)}
                      className={styles.resumeButton}
                    >
                      {resumingTaskId === selectedTask.id ? 'Resuming…' : 'Continue Task'}
                    </Button>
                    {canCreateSkill && (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Plus size={14} />}
                        onClick={() => skillCreator.open(selectedTask)}
                      >
                        Create Skill
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={
                        deletingTaskId === selectedTask.id ? (
                          <Loader2 size={14} className={styles.spinning} />
                        ) : (
                          <Trash2 size={14} />
                        )
                      }
                      loading={deletingTaskId === selectedTask.id}
                      disabled={deletingTaskId === selectedTask.id}
                      onClick={() => deleteTask(selectedTask.id)}
                      className={styles.deleteButton}
                    >
                      {deletingTaskId === selectedTask.id ? 'Deleting…' : 'Delete Task'}
                    </Button>
                  </>
                ) : null}
              </div>
            </div>

            {/* Body — scrollable transcript */}
            <div className={styles.detailContent} ref={bodyRef}>
              {/* Task details card sits at the top of the body */}
              <div className={styles.taskDetailsCard}>
                <h4 className={styles.taskDetailsLabel}>Task Details</h4>
                <dl className={styles.detailList}>
                  <dt>Started</dt>
                  <dd>{formatTimestamp(selectedTask.createdAt)}</dd>
                  <dt>Duration</dt>
                  <dd>{formatDuration(getElapsedMs(selectedTask))}</dd>
                  {selectedTask.inputTokens != null && (
                    <>
                      <dt>Input Tokens</dt>
                      <dd>{selectedTask.inputTokens.toLocaleString()}</dd>
                    </>
                  )}
                  {selectedTask.outputTokens != null && (
                    <>
                      <dt>Output Tokens</dt>
                      <dd>{selectedTask.outputTokens.toLocaleString()}</dd>
                    </>
                  )}
                  {selectedTask.cacheTokens != null && (
                    <>
                      <dt>Cache Tokens</dt>
                      <dd>{selectedTask.cacheTokens.toLocaleString()}</dd>
                    </>
                  )}
                </dl>
              </div>

              <TaskTranscript
                task={selectedTask}
                items={transcriptItems}
                expandedDetailIds={expandedDetailIds}
                onToggleDetail={toggleDetailExpansion}
                tasksAwaitingOption={tasksAwaitingOption}
                onTaskReply={handleTaskReply}
              />

              {selectedTask.error && (
                <div className={styles.taskErrorSection}>
                  <h4>Task Error</h4>
                  <pre className={`${styles.codeBlock} ${styles.errorBlock}`}>
                    {selectedTask.error}
                  </pre>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className={styles.emptyDetail}>
            {isMobile && (
              <Button
                variant="ghost"
                size="sm"
                icon={<ArrowLeft size={14} />}
                onClick={handleMobileBack}
              >
                Back to All Tasks
              </Button>
            )}
            <p>Select a task to view its progress</p>
          </div>
        )}
      </div>

      <SkillCreatorModal
        isOpen={skillCreator.isOpen}
        sourceSkills={skillCreator.sourceSkills}
        reservedNames={reservedSkillNames}
        status={skillCreator.status}
        serverError={skillCreator.serverError}
        successInfo={skillCreator.successInfo}
        onClose={skillCreator.close}
        onSubmit={skillCreator.submit}
      />
    </div>
  )
}
