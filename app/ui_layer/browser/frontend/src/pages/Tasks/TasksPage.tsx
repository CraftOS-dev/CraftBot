import React, { useState, useRef, useEffect, useCallback } from 'react'
import { ChevronRight, XCircle } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { StatusIndicator, Badge, Button } from '../../components/ui'
import type { ActionItem } from '../../types'
import styles from './TasksPage.module.css'

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

// Panel width limits (1:3 ratio default)
const DEFAULT_PANEL_WIDTH = 350
const MIN_PANEL_WIDTH = 200
const MAX_PANEL_WIDTH = 600

export function TasksPage() {
  const { actions, cancelTask, cancellingTaskId } = useWebSocket()
  const [selectedItem, setSelectedItem] = useState<ActionItem | null>(null)

  // Resizable panel state
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const tasks = actions.filter(a => a.itemType === 'task')

  // Get all items (actions + reasoning) for a task
  const getItemsForTask = (taskId: string) =>
    actions.filter(a => (a.itemType === 'action' || a.itemType === 'reasoning') && a.parentId === taskId)

  // Get only actual actions (not reasoning) for count
  const getActionCountForTask = (taskId: string) =>
    actions.filter(a => a.itemType === 'action' && a.parentId === taskId).length

  const formatDuration = (ms?: number) => {
    if (!ms) return '-'
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
    return `${(ms / 60000).toFixed(1)}m`
  }

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
      // Calculate width from left edge (since panel is on the left)
      const newWidth = e.clientX - containerRect.left
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

  return (
    <div className={`${styles.tasksPage} ${isResizing ? styles.resizing : ''}`} ref={containerRef}>
      {/* Task List - Left Side (resizable) */}
      <div className={styles.taskList} style={{ width: panelWidth, flexShrink: 0 }}>
        <div className={styles.listHeader}>
          <h3>All Tasks</h3>
          <Badge variant="default">{tasks.length}</Badge>
        </div>

        <div className={styles.listContent}>
          {tasks.length === 0 ? (
            <div className={styles.emptyState}>
              <p>No tasks yet</p>
            </div>
          ) : (
            tasks.map(task => {
              const taskItems = getItemsForTask(task.id)
              const actionCount = getActionCountForTask(task.id)
              const isExpanded = selectedItem?.id === task.id ||
                taskItems.some(a => a.id === selectedItem?.id)

              return (
                <div key={task.id} className={styles.taskGroup}>
                  <button
                    className={`${styles.taskItem} ${selectedItem?.id === task.id ? styles.selected : ''}`}
                    onClick={() => {
                      // Toggle: if task is selected, deselect; otherwise select
                      if (selectedItem?.id === task.id) {
                        setSelectedItem(null)
                      } else {
                        setSelectedItem(task)
                      }
                    }}
                  >
                    <ChevronRight
                      size={14}
                      className={`${styles.chevron} ${isExpanded ? styles.expanded : ''}`}
                    />
                    <StatusIndicator status={task.status} size="sm" />
                    <span className={styles.itemName}>{task.name}</span>
                    <Badge
                      variant={
                        task.status === 'completed' ? 'success' :
                        (task.status === 'error' || task.status === 'cancelled') ? 'error' :
                        task.status === 'running' ? 'primary' : 'default'
                      }
                    >
                      {actionCount} actions
                    </Badge>
                  </button>

                  {isExpanded && (
                    <div className={styles.actionsList}>
                      {taskItems.length > 0 ? (
                        taskItems.map(action => (
                          <button
                            key={action.id}
                            className={`${styles.actionItem} ${action.itemType === 'reasoning' ? styles.reasoningItem : ''} ${selectedItem?.id === action.id ? styles.selected : ''}`}
                            onClick={() => setSelectedItem(action)}
                          >
                            {action.itemType !== 'reasoning' && (
                              <StatusIndicator status={action.status} size="sm" />
                            )}
                            <span className={styles.itemName}>{action.name}</span>
                          </button>
                        ))
                      ) : (
                        <div className={styles.noActions}>No actions yet</div>
                      )}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Resize Handle */}
      <div
        className={styles.resizeHandle}
        onMouseDown={handleMouseDown}
      />

      {/* Detail Panel - Right Side */}
      <div className={styles.detailPanel}>
        {selectedItem ? (
          <>
            <div className={styles.detailHeader}>
              <div className={styles.detailTitle}>
                <StatusIndicator status={selectedItem.status} size="md" />
                <h2>{selectedItem.name}</h2>
              </div>
              {selectedItem.itemType === 'task' && (
                <div className={styles.detailActions}>
                  {selectedItem.status === 'running' ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<XCircle size={14} />}
                      loading={cancellingTaskId === selectedItem.id}
                      onClick={() => cancelTask(selectedItem.id)}
                      className={styles.cancelButton}
                    >
                      {cancellingTaskId === selectedItem.id ? 'Cancelling...' : 'Cancel Task'}
                    </Button>
                  ) : (selectedItem.status === 'error' || selectedItem.status === 'cancelled') && (
                    <Badge variant="error">Aborted</Badge>
                  )}
                </div>
              )}
            </div>

            <div className={styles.detailContent}>
              <div className={styles.detailSection}>
                <h4>Details</h4>
                <dl className={styles.detailList}>
                  <dt>Type</dt>
                  <dd>{selectedItem.itemType}</dd>
                  <dt>ID</dt>
                  <dd className={styles.mono}>{selectedItem.id}</dd>
                  {selectedItem.parentId && (
                    <>
                      <dt>Parent Task</dt>
                      <dd className={styles.mono}>{selectedItem.parentId}</dd>
                    </>
                  )}
                  <dt>Duration</dt>
                  <dd>{formatDuration(selectedItem.duration)}</dd>
                </dl>
              </div>

              {selectedItem.itemType === 'reasoning' ? (
                selectedItem.output && (
                  <div className={styles.detailSection}>
                    <h4>Content</h4>
                    <div className={styles.reasoningContent}>
                      {selectedItem.output}
                    </div>
                  </div>
                )
              ) : (
                <>
                  {selectedItem.input && (
                    <div className={styles.detailSection}>
                      <h4>Input</h4>
                      <JsonDisplay content={selectedItem.input} />
                    </div>
                  )}

                  {selectedItem.output && (
                    <div className={styles.detailSection}>
                      <h4>Output</h4>
                      <JsonDisplay content={selectedItem.output} />
                    </div>
                  )}
                </>
              )}

              {selectedItem.error && (
                <div className={styles.detailSection}>
                  <h4>Error</h4>
                  <pre className={`${styles.codeBlock} ${styles.errorBlock}`}>
                    {selectedItem.error}
                  </pre>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className={styles.emptyDetail}>
            <p>Select a task or action to view details</p>
          </div>
        )}
      </div>
    </div>
  )
}
