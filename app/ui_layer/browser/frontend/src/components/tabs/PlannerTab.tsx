import React from 'react'
import { CalendarRange, CheckCircle2, Circle, Clock, ArrowUp, ArrowRight, ArrowDown } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useDynamicTabs } from '../../hooks/useDynamicTabs'
import { PlannerTabData, PlannerTask } from '../../types/dynamicTabs'
import { MarkdownContent } from '../ui'
import styles from './DynamicTab.module.css'

interface PlannerTabProps {
  tabId: string
}

const TASK_STATUS_ICONS: Record<PlannerTask['status'], React.ReactNode> = {
  todo: <Circle size={14} />,
  'in-progress': <Clock size={14} className={styles.statusModified} />,
  done: <CheckCircle2 size={14} className={styles.statusAdded} />,
}

const PRIORITY_ICONS: Record<PlannerTask['priority'], React.ReactNode> = {
  high: <ArrowUp size={12} className={styles.statusDeleted} />,
  medium: <ArrowRight size={12} className={styles.statusModified} />,
  low: <ArrowDown size={12} />,
}

export const PlannerTab = React.memo(function PlannerTab({ tabId }: PlannerTabProps) {
  const { tabData, getTabById } = useDynamicTabs()
  const { actions } = useWebSocket()
  const tab = getTabById(tabId)
  const data = tabData[tabId] as PlannerTabData | undefined

  const taskActions = tab?.taskId
    ? actions.filter(a => a.parentId === tab.taskId || a.id === tab.taskId)
    : []

  const hasData = data && (data.milestones?.length || data.tasks?.length || data.summary)

  if (!hasData) {
    return (
      <div className={styles.tabContainer}>
        {taskActions.length > 0 ? (
          <div className={styles.taskContent}>
            <div className={styles.taskHeader}>
              <CalendarRange size={20} />
              <h3>Project Planner</h3>
            </div>
            <div className={styles.actionList}>
              {taskActions.map(action => (
                <div key={action.id} className={`${styles.actionItem} ${styles[action.status]}`}>
                  <span className={styles.actionStatus}>{action.status}</span>
                  <span className={styles.actionName}>{action.name}</span>
                  {action.output && (
                    <div className={styles.actionOutput}>
                      <MarkdownContent content={action.output} />
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className={styles.waitingText}>Waiting for planning data...</p>
          </div>
        ) : (
          <div className={styles.placeholder}>
            <CalendarRange size={48} strokeWidth={1.5} />
            <h2>Planner Board</h2>
            <p>Timelines, milestones, and project planning will appear here when a planning task runs.</p>
          </div>
        )}
      </div>
    )
  }

  // Group tasks by status for kanban-style view
  const tasksByStatus = {
    todo: data.tasks?.filter(t => t.status === 'todo') ?? [],
    'in-progress': data.tasks?.filter(t => t.status === 'in-progress') ?? [],
    done: data.tasks?.filter(t => t.status === 'done') ?? [],
  }

  return (
    <div className={styles.tabContainer}>
      <div className={styles.taskContent}>
        <div className={styles.taskHeader}>
          <CalendarRange size={20} />
          <h3>{data.title ?? tab?.label ?? 'Project Plan'}</h3>
        </div>

        {data.summary && (
          <div className={styles.summarySection}>
            <MarkdownContent content={data.summary} />
          </div>
        )}

        {data.milestones && data.milestones.length > 0 && (
          <div className={styles.dataSection}>
            <h4>Milestones</h4>
            <div className={styles.milestoneList}>
              {data.milestones.map(ms => (
                <div key={ms.id} className={`${styles.milestoneItem} ${styles[ms.status]}`}>
                  {ms.status === 'completed' ? <CheckCircle2 size={14} /> : <Circle size={14} />}
                  <span className={styles.milestoneName}>{ms.name}</span>
                  <span className={styles.milestoneDate}>{ms.date}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {data.tasks && data.tasks.length > 0 && (
          <div className={styles.dataSection}>
            <h4>Tasks ({data.tasks.length})</h4>
            <div className={styles.kanbanBoard}>
              {(Object.entries(tasksByStatus) as [PlannerTask['status'], PlannerTask[]][]).map(([status, tasks]) => (
                <div key={status} className={styles.kanbanColumn}>
                  <div className={styles.kanbanHeader}>
                    {TASK_STATUS_ICONS[status]}
                    <span>{status === 'in-progress' ? 'In Progress' : status.charAt(0).toUpperCase() + status.slice(1)}</span>
                    <span className={styles.kanbanCount}>{tasks.length}</span>
                  </div>
                  {tasks.map(task => (
                    <div key={task.id} className={styles.kanbanCard}>
                      <div className={styles.kanbanCardHeader}>
                        {PRIORITY_ICONS[task.priority]}
                        <span>{task.name}</span>
                      </div>
                      {task.assignee && <span className={styles.kanbanAssignee}>{task.assignee}</span>}
                      {task.dueDate && <span className={styles.kanbanDue}>Due: {task.dueDate}</span>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
})
