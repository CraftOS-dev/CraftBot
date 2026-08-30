import { ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { StatusIndicator } from '../ui'
import type { ActionItem } from '../../types'
import { normalizeActionName, extractTodos } from './actionNames'
import { strField, parseDict } from './parse'
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

// Live elapsed time for an in-flight action. The row only shows a timer
// while the action is running/waiting — finished actions (success or
// error) show no duration.
function getRunningElapsedMs(item: ActionItem): number | undefined {
  if ((item.status === 'running' || item.status === 'waiting') && item.createdAt) {
    return Date.now() - item.createdAt
  }
  return undefined
}

// ─────────────────────────────────────────────────────────────────────
// Timeline blocks
// ─────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────
// Chunk header: one clickable row standing in for a whole
// reasoning+actions block between two chat bubbles. The chevron sits
// AFTER the label (always visible, rotates when open) so the row reads
// as expandable in every state.
//   - run in flight:  [spinner] Working… ›        12.3s
//   - settled:        [       ] N Actions executed ›
// Shares the action-row geometry (32px icon slot + 8px gap) so the text
// edge lines up with every other timeline row.
// ─────────────────────────────────────────────────────────────────────

export function ChunkHeaderRow({
  count,
  expanded,
  working,
  elapsedMs,
  onToggle,
}: {
  count: number
  expanded: boolean
  working: boolean
  elapsedMs?: number
  onToggle: () => void
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
      <span className={styles.actionRowStatus}>
        {working
          ? <StatusIndicator status="running" size="sm" />
          : <StatusIndicator status="completed" size="sm" />}
      </span>
      {working ? (
        <>
          <span className={styles.workingLabel}>
            {t('activity:chunk.working')}
            <span className={styles.workingDot}>.</span>
            <span className={styles.workingDot}>.</span>
            <span className={styles.workingDot}>.</span>
          </span>
          {chevron}
          {elapsedMs != null && (
            <span className={styles.actionRowDuration}>{formatDuration(elapsedMs)}</span>
          )}
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

export function ReasoningBlock({ item }: { item: ActionItem }) {
  const { t } = useTranslation(['activity', 'common'])
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
          : <span className={styles.reasoningPlaceholder}>{t('activity:reasoning.thinking')}</span>}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Row preview: one muted line summarizing the PRIMARY input of the
// action (query for web_search, path for file ops, command for
// run_shell, …). Falls back to the first string param, then raw input.
// ─────────────────────────────────────────────────────────────────────

const PREVIEW_KEYS: Record<string, string[]> = {
  // web / search
  web_search: ['query'],
  memory_search: ['query'],
  web_fetch: ['url'],
  http_request: ['url'],
  // file ops
  read_file: ['file_path'],
  write_file: ['file_path'],
  stream_edit: ['file_path'],
  read_pdf: ['file_path'],
  find_files: ['pattern'],
  grep_files: ['pattern'],
  list_folder: ['path'],
  convert_to_pdf: ['source_path', 'url', 'output_path'],
  convert_from_pdf: ['source_path', 'output_path'],
  convert_to_markdown: ['input_file'],
  // code execution
  run_shell: ['command'],
  run_python: ['code'],
  // media
  generate_image: ['prompt'],
  describe_image: ['image_path'],
  perform_ocr: ['image_path'],
  understand_video: ['video_path'],
  // messaging
  send_message_with_attachment: ['message'],
}

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

function getActionPreview(item: ActionItem, inputObj: Record<string, unknown> | null): string {
  const normalized = normalizeActionName(item.name)

  // update_todos summarizes progress: "3/5 done".
  if (normalized === 'update_todos') {
    const todos = extractTodos(inputObj)
    if (!todos) return ''
    const done = todos.filter(t => t.status === 'completed').length
    return `${done}/${todos.length} done`
  }

  const keys = PREVIEW_KEYS[normalized]
  if (keys) {
    for (const key of keys) {
      const value = strField(inputObj, key)
      if (value?.trim()) return firstLine(value)
    }
  }
  if (inputObj) {
    for (const value of Object.values(inputObj)) {
      if (typeof value === 'string' && value.trim()) return firstLine(value)
    }
  }
  return item.input ? firstLine(item.input) : ''
}

// Compact, Claude-Code-style action line — the ENTIRE rendering of an
// action item: status icon + name + muted one-line input preview, plus a
// live timer on the right only while the action is running. Plain and
// non-interactive; on errors only the status icon goes red, with the
// error message's first line as the preview.
export function ActionBlock({ item }: { item: ActionItem }) {
  const isError = item.status === 'error'
  const inputObj = parseDict(item.input)
  const preview = isError && item.error
    ? firstLine(item.error)
    : getActionPreview(item, inputObj)
  const elapsed = getRunningElapsedMs(item)

  return (
    <div
      id={`transcript-item-${item.id}`}
      className={styles.actionRow}
    >
      <span className={styles.actionRowStatus}>
        <StatusIndicator status={item.status} size="sm" />
      </span>
      <span className={styles.actionRowName}>{displayActionName(item.name)}</span>
      {preview && <span className={styles.actionRowPreview}>{preview}</span>}
      {elapsed != null && (
        <span className={styles.actionRowDuration}>{formatDuration(elapsed)}</span>
      )}
    </div>
  )
}
