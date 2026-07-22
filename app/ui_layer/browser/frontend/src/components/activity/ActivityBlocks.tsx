import React, { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { StatusIndicator } from '../ui'
import { useWebSocket } from '../../contexts/WebSocketContext'
import type { ActionItem } from '../../types'
import { getActionRenderer, parseIO } from './renderers'
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

function formatTimestamp(ts?: number): string {
  if (!ts) return '-'
  return new Date(ts).toLocaleString()
}

// Returns the duration to display: the completed duration if available,
// otherwise the live elapsed time since createdAt for running items.
export function getElapsedMs(item: ActionItem): number | undefined {
  if (item.duration != null) return item.duration
  if ((item.status === 'running' || item.status === 'waiting') && item.createdAt) {
    return Date.now() - item.createdAt
  }
  return undefined
}

// ─────────────────────────────────────────────────────────────────────
// Structured content display (generic fallback for actions without a
// custom renderer)
// ─────────────────────────────────────────────────────────────────────

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

interface JsonViewerProps {
  data: unknown
  depth?: number
}

function JsonViewer({ data, depth = 0 }: JsonViewerProps) {
  const formatValue = (value: unknown): string => {
    if (value === null) return 'null'
    if (value === undefined) return 'undefined'
    if (typeof value === 'boolean') return value.toString()
    if (typeof value === 'number') return value.toString()
    if (typeof value === 'string') return value
    return String(value)
  }

  const isComplex = (value: unknown): boolean => {
    return value !== null && typeof value === 'object'
  }

  const renderValue = (value: unknown) => {
    const strValue = formatValue(value)
    return <ExpandableValue value={strValue} />
  }

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

  let inner = content.trim()
  if (inner.startsWith('{') && inner.endsWith('}')) {
    inner = inner.slice(1, -1).trim()
  }

  let i = 0
  while (i < inner.length) {
    while (i < inner.length && (inner[i] === ' ' || inner[i] === ',' || inner[i] === '\n')) i++
    if (i >= inner.length) break

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

    while (i < inner.length && (inner[i] === ':' || inner[i] === ' ')) i++

    if (i >= inner.length) break

    let value: unknown
    const valueStart = inner[i]

    if (valueStart === "'" || valueStart === '"') {
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
      let bracketCount = 1
      let start = i
      i++
      while (i < inner.length && bracketCount > 0) {
        if (inner[i] === '[') bracketCount++
        else if (inner[i] === ']') bracketCount--
        i++
      }
      value = inner.slice(start, i)
    } else {
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

function JsonDisplay({ content }: { content: string }) {
  const parsed = parsePythonDict(content)

  return (
    <dl className={styles.detailList}>
      <JsonViewer data={parsed} />
    </dl>
  )
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
// Timeline blocks
// ─────────────────────────────────────────────────────────────────────

export function ReasoningBlock({ item }: { item: ActionItem }) {
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

export interface ActionBlockProps {
  item: ActionItem
  expanded: boolean
  onToggleDetail: () => void
}

export function ActionBlock({ item, expanded, onToggleDetail }: ActionBlockProps) {
  const { openFile } = useWebSocket()
  const elapsed = getElapsedMs(item)

  // Look up a custom renderer for this action. If one is registered it
  // replaces the generic Input/Output sections with a tailored view (diff
  // for stream_edit, terminal for run_python, checklist for update_todos,
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
