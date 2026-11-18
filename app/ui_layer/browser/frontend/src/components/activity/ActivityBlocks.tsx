import { useEffect, useState, type ComponentType } from 'react'
import * as LucideIcons from 'lucide-react'
import { ChevronRight, Wrench } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { StatusIndicator } from '../ui'
import { IntegrationIcon } from '../integrations/IntegrationIcon'
import type { ActionItem } from '../../types'
import type { StreamAction, StreamReasoning } from '../../store/slices/streamSlice'
import { normalizeActionName, extractTodos } from './actionNames'
import { parseDict } from './parse'
import styles from './ActivityBlocks.module.css'

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

// Start time of an in-flight action. The row only shows a timer while the
// action is running/waiting — finished actions (success or error) show no
// duration.
function getRunningSince(item: ActionItem): number | undefined {
  if ((item.status === 'running' || item.status === 'waiting') && item.createdAt) {
    return item.createdAt
  }
  return undefined
}

const ELAPSED_TICK_MS = 100

// Live elapsed time since `since` (epoch ms). Ticks itself while mounted, so
// only this text re-renders — not the row, and not the Chat around it. Rows
// mount it only while their action or run is in flight.
function Elapsed({ since }: { since: number }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), ELAPSED_TICK_MS)
    return () => clearInterval(id)
  }, [])
  return (
    <span className={styles.actionRowDuration}>
      {formatDuration(Math.max(0, Date.now() - since))}
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Rail: the line joining the status icons of an open work block. Each row
// draws its own share in the 32px status column: from its top down to its
// icon (up), and from its icon through the gap below to the next row
// (down). Which rows connect is the timeline's call (Chat.tsx).
// ─────────────────────────────────────────────────────────────────────

export interface Rail {
  up?: boolean
  down?: boolean
}

function RailLines({ rail, icon }: { rail?: Rail; icon: 'middle' | 'top' }) {
  if (!rail || (!rail.up && !rail.down)) return null
  const at = icon === 'middle' ? styles.railMiddle : styles.railTop
  return (
    <>
      {rail.up && <span className={`${styles.rail} ${styles.railUp} ${at}`} aria-hidden="true" />}
      {rail.down && <span className={`${styles.rail} ${styles.railDown} ${at}`} aria-hidden="true" />}
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Working label: what the run's current step is doing (the status line
// its decision gave, see streamSlice), or ``fallback`` ("Working") before
// any step gave one, with the dots cycling 1 → 2 → 3. A long line
// truncates; the dots stay.
// ─────────────────────────────────────────────────────────────────────

export function WorkingLabel({ status, fallback }: { status?: string; fallback: string }) {
  // The dots are the label's own: a line ending in "." or "…" drops them.
  const line = status?.replace(/[\s.…]+$/, '') || fallback
  return (
    <span className={styles.workingLabel}>
      <span key={line} className={styles.workingText} title={line}>{line}</span>
      {/* Their own box: the dot animation counts them 1 → 3 (nth-of-type). */}
      <span>
        <span className={styles.workingDot}>.</span>
        <span className={styles.workingDot}>.</span>
        <span className={styles.workingDot}>.</span>
      </span>
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Timeline blocks
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// Chunk header: one clickable row standing in for a whole
// reasoning+actions block between two chat bubbles. The chevron sits
// AFTER the label (always visible, rotates when open) so the row reads
// as expandable in every state.
//   - run in flight:  [spinner] Searching for weather sites… ›   12.3s
//                     ("Working…" until a step gives its status line)
//   - settled:        [       ] N Actions executed ›
// Shares the action-row geometry (32px icon slot + 8px gap) so the text
// edge lines up with every other timeline row.
// ─────────────────────────────────────────────────────────────────────

export function ChunkHeaderRow({
  count,
  expanded,
  working,
  status,
  startedAt,
  onToggle,
  rail,
}: {
  count: number
  expanded: boolean
  working: boolean
  /** The current step's status line, shown while working. */
  status?: string
  /** Run start (epoch ms); shows a live timer while working. */
  startedAt?: number
  onToggle: () => void
  rail?: Rail
}) {
  const { t } = useTranslation(['activity', 'common'])
  const chevron = (
    <ChevronRight
      size={13}
      className={`${styles.chunkChevron}${expanded ? ` ${styles.chunkChevronOpen}` : ''}`}
    />
  )
  return (
    <button
      type="button"
      className={styles.chunkHeader}
      onClick={onToggle}
      aria-expanded={expanded}
      title={expanded ? t('activity:chunk.hideSteps') : t('activity:chunk.showSteps')}
    >
      <RailLines rail={rail} icon="middle" />
      <span className={styles.actionRowStatus}>
        {working
          ? <StatusIndicator status="running" size="sm" />
          : <StatusIndicator status="completed" size="sm" />}
      </span>
      {working ? (
        <>
          <WorkingLabel status={status} fallback={t('activity:chunk.working')} />
          {chevron}
          {startedAt != null && <Elapsed since={startedAt} />}
        </>
      ) : (
        <>
          <span className={styles.chunkLabel}>
            {t('activity:chunk.actionsExecuted', { count })}
          </span>
          {chevron}
        </>
      )}
    </button>
  )
}

export function ReasoningBlock({ item, rail }: { item: ActionItem; rail?: Rail }) {
  const { t } = useTranslation(['activity', 'common'])
  return (
    <div id={`transcript-item-${item.id}`} className={styles.transcriptItem}>
      <RailLines rail={rail} icon="top" />
      <div className={styles.gutter}>
        <div className={styles.gutterIcon}>
          <div className={styles.reasoningCircle} aria-hidden="true" />
        </div>
      </div>
      <div className={styles.reasoningContent}>
        {item.output
          ? item.output
          : <span className={styles.reasoningPlaceholder}>{t('activity:reasoning.thinking')}</span>}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// The decision reply as the model writes it (streamSlice): its reasoning
// so far, then each action being prepared, as the same reasoning and
// action rows the timeline shows once they are real (pending until they
// start). The live status row renders it in place of "Working…";
// ``connected``: it continues the open work block above (the rail joins).
// ─────────────────────────────────────────────────────────────────────

export function StreamLiveRow({
  sessionId,
  reasoning,
  actions,
  connected = false,
}: {
  sessionId: string
  reasoning: StreamReasoning | null
  actions: StreamAction[]
  connected?: boolean
}) {
  const count = (reasoning ? 1 : 0) + actions.length
  const railAt = (index: number): Rail => ({ up: connected || index > 0, down: index < count - 1 })
  const offset = reasoning ? 1 : 0
  return (
    <div className={styles.streamLive} role="status">
      {reasoning && (
        <ReasoningBlock
          rail={railAt(0)}
          item={{
            id: reasoning.id,
            name: 'Reasoning',
            status: 'running',
            itemType: 'reasoning',
            sessionId,
            output: reasoning.text,
          }}
        />
      )}
      {actions.map((action, index) => (
        <ActionBlock
          key={action.id}
          rail={railAt(offset + index)}
          item={{
            id: action.id,
            name: action.name,
            status: 'pending',
            itemType: 'action',
            sessionId,
            input: action.input,
            displayParam: action.displayParam,
            icon: action.icon,
            integration: action.integration,
          }}
        />
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Row preview: one muted line with the value of the input the action
// declares for display (its display param: what the call acts on, or
// what it sends). An action the backend did not know shows its first
// text input.
// ─────────────────────────────────────────────────────────────────────

// First non-empty line, capped so the row's ellipsis has a sane input.
function firstLine(text: string): string {
  const line = text.split('\n').find(l => l.trim())?.trim() ?? ''
  return line.length > 200 ? `${line.slice(0, 200)}…` : line
}

// Human display name: "run_shell" → "Run shell".
function displayActionName(name: string): string {
  const words = normalizeActionName(name).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// One input value as one short line: text as its first line, lists as
// their items, objects as their fields.
function formatValue(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return firstLine(value)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  const part = (v: unknown) => (v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v))
  if (Array.isArray(value)) return firstLine(value.map(part).join(', '))
  if (typeof value === 'object') {
    return firstLine(Object.entries(value).map(([k, v]) => `${k}: ${part(v)}`).join(', '))
  }
  return ''
}

function getActionPreview(item: ActionItem, inputObj: Record<string, unknown> | null): string {
  // update_todos summarizes progress: "3/5 done".
  if (normalizeActionName(item.name) === 'update_todos') {
    const todos = extractTodos(inputObj)
    if (!todos) return ''
    const done = todos.filter(t => t.status === 'completed').length
    return `${done}/${todos.length} done`
  }
  if (item.displayParam !== undefined) {
    return item.displayParam && inputObj ? formatValue(inputObj[item.displayParam]) : ''
  }
  if (inputObj) {
    for (const [key, value] of Object.entries(inputObj)) {
      if (!key.startsWith('_') && typeof value === 'string' && value.trim()) return firstLine(value)
    }
  }
  return ''
}

// The integration's logo for an integration's action, else the action's
// lucide icon. The hint names the logo where the integration id alone does
// not (the same hints the Settings integration list gets).
const LOGO_HINT: Record<string, string> = {
  lark_drive: 'lark',
  lark_calendar: 'lark',
  figma: 'Figma',
  outlook: 'Inbox',
}
const LUCIDE = LucideIcons as unknown as Record<string, ComponentType<{ size?: number }>>
const LOGO_SIZE = 14

function ActionLogo({ item }: { item: ActionItem }) {
  if (item.integration) {
    return (
      <span className={styles.actionRowLogo}>
        <IntegrationIcon id={item.integration} icon={LOGO_HINT[item.integration]} size={LOGO_SIZE} />
      </span>
    )
  }
  const Icon = (item.icon && LUCIDE[item.icon]) || Wrench
  return (
    <span className={styles.actionRowLogo}>
      <Icon size={LOGO_SIZE} />
    </span>
  )
}

// Compact, Claude-Code-style action line — the ENTIRE rendering of an
// action item: status icon + logo + name + muted one-line input preview,
// plus a live timer on the right only while the action is running. Plain
// and non-interactive; on errors only the status icon goes red, with the
// error message's first line as the preview.
export function ActionBlock({ item, rail }: { item: ActionItem; rail?: Rail }) {
  const isError = item.status === 'error'
  const inputObj = parseDict(item.input)
  const preview = isError && item.error
    ? firstLine(item.error)
    : getActionPreview(item, inputObj)
  const runningSince = getRunningSince(item)

  return (
    <div
      id={`transcript-item-${item.id}`}
      className={styles.actionRow}
    >
      <RailLines rail={rail} icon="middle" />
      <span className={styles.actionRowStatus}>
        <StatusIndicator status={item.status} size="sm" />
      </span>
      <ActionLogo item={item} />
      <span className={styles.actionRowName}>{displayActionName(item.name)}</span>
      {preview && <span className={styles.actionRowPreview}>{preview}</span>}
      {runningSince != null && <Elapsed since={runningSince} />}
    </div>
  )
}
