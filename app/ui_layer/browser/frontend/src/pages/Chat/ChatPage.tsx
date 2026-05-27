import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { X, Loader2, Reply } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { IconButton, StatusIndicator } from '../../components/ui'
import { Chat } from '../../components/Chat'
import { MascotDisplay } from '@mascot'
import { getActivePlaceholder } from '../../utils/taskPlaceholder'
import { useTaskListAutoScroll } from '../../hooks'
import styles from './ChatPage.module.css'

// Panel width limits
const DEFAULT_PANEL_WIDTH = 460
const MIN_PANEL_WIDTH = 200
const MAX_PANEL_WIDTH = 800

export function ChatPage() {
  const {
    actions,
    messages,
    cancelTask,
    cancellingTaskId,
    setReplyTarget,
    loadOlderActions,
    hasMoreActions,
    loadingOlderActions,
  } = useWebSocket()

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

  // Resizable panel state
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

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
      const newWidth = containerRect.right - e.clientX
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

  // Handle reply from task panel
  const handleTaskReply = useCallback((taskId: string, taskName: string) => {
    setReplyTarget({
      type: 'task',
      sessionId: taskId,
      displayName: taskName,
      originalContent: `Task: ${taskName}`,
    })
  }, [setReplyTarget])

  // Group actions by task
  const tasks = useMemo(() => actions.filter(a => a.itemType === 'task'), [actions])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)

  const getActionsForTask = (taskId: string) =>
    actions.filter(a => a.itemType === 'action' && a.parentId === taskId)

  // Scroll behavior + scroll-to-top pagination for the Tasks & Actions list.
  // Same hook as TasksPage's All Tasks list so they behave identically:
  // initial jump to latest, auto-follow only while near the bottom, and
  // anchor-preserving prepend when older tasks are loaded.
  const actionListRef = useRef<HTMLDivElement>(null)
  useTaskListAutoScroll(actionListRef, tasks.length, {
    hasMore: hasMoreActions,
    loading: loadingOlderActions,
    loadMore: loadOlderActions,
  })

  return (
    <div className={`${styles.chatPage} ${isResizing ? styles.resizing : ''}`} ref={containerRef}>
      {/* Chat Component */}
      <div className={styles.chatPanel}>
        <Chat />
      </div>

      {/* Resize Handle */}
      <div
        className={styles.resizeHandle}
        onMouseDown={handleMouseDown}
      />

      {/* Task/Action Panel
          Separate row rendering from TasksPage's All Tasks list by design:
          this is a lightweight live sidekick (action-only children, no
          reasoning, no detail panel) while TasksPage is the full browser.
          Scroll + pagination behavior is shared via useTaskListAutoScroll
          so the two stay in sync. */}
      <div className={styles.actionPanel} style={{ width: panelWidth, flexShrink: 0 }}>
        <MascotDisplay />
        <div className={styles.panelHeader}>
          <h3>Tasks & Actions</h3>
        </div>
        <div className={styles.actionList} ref={actionListRef}>
          {loadingOlderActions && (
            <div className={styles.loadingOlder}>
              <Loader2 size={14} className={styles.spinning} /> Loading older tasks...
            </div>
          )}
          {tasks.length === 0 ? (
            <div className={styles.emptyActions}>
              <p>No active tasks</p>
            </div>
          ) : (
            tasks.map(task => {
              const isExpanded = selectedTaskId === task.id
              const taskActions = isExpanded ? getActionsForTask(task.id) : []
              const listPlaceholder = isExpanded
                ? getActivePlaceholder(task.status, taskActions)
                : null
              const showListReply =
                listPlaceholder?.status === 'waiting' && !tasksAwaitingOption.has(task.id)

              return (
                <div key={task.id} className={styles.taskGroup}>
                  <div
                    className={`${styles.taskItem} ${isExpanded ? styles.selected : ''}`}
                    onClick={() => setSelectedTaskId(isExpanded ? null : task.id)}
                  >
                    <StatusIndicator status={task.status} size="sm" />
                    <span className={styles.taskName}>{task.name}</span>
                    {(task.status === 'running' || task.status === 'waiting') && (
                      <>
                        {!tasksAwaitingOption.has(task.id) && (
                          <IconButton
                            size="sm"
                            variant="ghost"
                            className={styles.taskReplyBtn}
                            onClick={(e) => {
                              e.stopPropagation()
                              handleTaskReply(task.id, task.name)
                            }}
                            title="Reply to Task"
                            icon={<Reply size={12} />}
                          />
                        )}
                        <IconButton
                          size="sm"
                          variant="ghost"
                          className={styles.taskCancelBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            cancelTask(task.id)
                          }}
                          disabled={cancellingTaskId === task.id}
                          title="Cancel Task"
                          icon={
                            cancellingTaskId === task.id ? (
                              <Loader2 size={12} className={styles.spinning} />
                            ) : (
                              <X size={12} />
                            )
                          }
                        />
                      </>
                    )}
                  </div>
                  {isExpanded && (
                    <div className={styles.actionsList}>
                      {taskActions.map(action => (
                        <div key={action.id} className={styles.actionItem}>
                          <StatusIndicator status={action.status} size="sm" />
                          <span className={styles.actionName}>{action.name}</span>
                        </div>
                      ))}
                      {listPlaceholder && (
                        <div className={styles.placeholderItem}>
                          <StatusIndicator status={listPlaceholder.status} size="sm" />
                          <span className={styles.actionName}>{listPlaceholder.label}</span>
                          {showListReply && (
                            <IconButton
                              size="sm"
                              variant="ghost"
                              className={styles.placeholderReplyBtn}
                              onClick={(e) => {
                                e.stopPropagation()
                                handleTaskReply(task.id, task.name)
                              }}
                              title="Reply to Task"
                              icon={<Reply size={12} />}
                            />
                          )}
                        </div>
                      )}
                      {taskActions.length === 0 && !listPlaceholder && (
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
    </div>
  )
}
