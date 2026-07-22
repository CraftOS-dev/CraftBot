import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { Check, X, Loader2, Reply, RotateCw, Trash2 } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { IconButton, StatusIndicator } from '../../components/ui'
import { Chat } from '../../components/Chat'
import { MascotDisplay } from '@mascot'
import { getActivePlaceholder } from '../../utils/taskPlaceholder'
import { isEndedStatus } from '../../utils/taskStatus'
import { useTaskListAutoScroll, useTaskListFLIP, useMascotVisibility } from '../../hooks'
import type { ActionItem } from '../../types'
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
    completeTask,
    completingTaskId,
    resumeTask,
    resumingTaskId,
    deleteTask,
    deletingTaskId,
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

  // Split tasks into "in-progress" (running / waiting / paused / pending) and
  // "ended" (completed / error / cancelled). The active group is sorted
  // newest-first by createdAt so a freshly-started task lands on top of its
  // section; the ended group is sorted newest-first by completedAt (falling
  // back to createdAt for rows persisted before that field existed) so a task
  // that just ended pops to the top of the ended section. The combined
  // `tasks` array keeps active-then-ended order so the pagination hook's count
  // stays correct.
  const { tasks, activeTasks, endedTasks } = useMemo(() => {
    const taskItems = actions.filter(a => a.itemType === 'task')
    const byNewestFirst = (a: ActionItem, b: ActionItem) => (b.createdAt ?? 0) - (a.createdAt ?? 0)
    const byNewestEnded = (a: ActionItem, b: ActionItem) =>
      (b.completedAt ?? b.createdAt ?? 0) - (a.completedAt ?? a.createdAt ?? 0)
    const active = taskItems.filter(t => !isEndedStatus(t.status)).sort(byNewestFirst)
    const ended = taskItems.filter(t => isEndedStatus(t.status)).sort(byNewestEnded)
    return { tasks: [...active, ...ended], activeTasks: active, endedTasks: ended }
  }, [actions])
  const taskOrderKey = useMemo(() => tasks.map(t => t.id).join(','), [tasks])
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

  // FLIP animates a task sliding from active → ended (or vice-versa) and the
  // surrounding rows shifting up/down to accommodate. Each row registers its
  // outer <div> via `flipRef(task.id)`.
  const flipRef = useTaskListFLIP(taskOrderKey)

  const [mascotVisible] = useMascotVisibility()

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
        {mascotVisible && <MascotDisplay />}
        <div className={styles.panelHeader}>
          <h3>All Tasks</h3>
        </div>
        <div className={styles.actionList} ref={actionListRef}>
          {tasks.length === 0 ? (
            <div className={styles.emptyActions}>
              <p>No active tasks</p>
            </div>
          ) : (() => {
            const renderTaskRow = (task: ActionItem) => {
              const isExpanded = selectedTaskId === task.id
              const taskActions = isExpanded ? getActionsForTask(task.id) : []
              const listPlaceholder = isExpanded
                ? getActivePlaceholder(task.status, taskActions)
                : null
              const showListReply =
                listPlaceholder?.status === 'waiting' && !tasksAwaitingOption.has(task.id)

              return (
                <div ref={flipRef(task.id)} className={styles.taskGroup}>
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
                          className={styles.taskCompleteBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            completeTask(task.id)
                          }}
                          disabled={completingTaskId === task.id || cancellingTaskId === task.id}
                          title="Mark Task Complete"
                          icon={
                            completingTaskId === task.id ? (
                              <Loader2 size={12} className={styles.spinning} />
                            ) : (
                              <Check size={12} />
                            )
                          }
                        />
                        <IconButton
                          size="sm"
                          variant="ghost"
                          className={styles.taskCancelBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            cancelTask(task.id)
                          }}
                          disabled={cancellingTaskId === task.id || completingTaskId === task.id}
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
                    {(task.status === 'completed' || task.status === 'cancelled' || task.status === 'error') && (
                      <>
                        <IconButton
                          size="sm"
                          variant="ghost"
                          className={styles.taskResumeBtn}
                          onClick={(e) => {
                            e.stopPropagation()
                            resumeTask(task.id)
                          }}
                          disabled={resumingTaskId === task.id}
                          title="Continue Task"
                          icon={
                            resumingTaskId === task.id ? (
                              <Loader2 size={12} className={styles.spinning} />
                            ) : (
                              <RotateCw size={12} />
                            )
                          }
                        />
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
            }

            return (
              <>
                {activeTasks.length === 0 && endedTasks.length > 0 && (
                  <div className={styles.emptyActiveSection}>No active task now...</div>
                )}
                {tasks.map((task, i) => {
                  // Divider sits above the first ended row whenever the ended
                  // section has rows — when active is empty, it sits below
                  // the "No active tasks" placeholder.
                  const showDivider = i === activeTasks.length
                  return (
                    <React.Fragment key={task.id}>
                      {showDivider && <div className={styles.sectionDivider} />}
                      {renderTaskRow(task)}
                    </React.Fragment>
                  )
                })}
                {loadingOlderActions && (
                  <div className={styles.loadingOlder}>
                    <Loader2 size={14} className={styles.spinning} /> Loading older tasks...
                  </div>
                )}
              </>
            )
          })()}
        </div>
      </div>
    </div>
  )
}
