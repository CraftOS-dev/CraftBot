import React from 'react'
import { LayoutPanelLeft } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useDynamicTabs } from '../../hooks/useDynamicTabs'
import { CustomTabData } from '../../types/dynamicTabs'
import { MarkdownContent } from '../ui'
import styles from './DynamicTab.module.css'

interface CustomTabProps {
  tabId: string
}

export const CustomTab = React.memo(function CustomTab({ tabId }: CustomTabProps) {
  const { tabData, getTabById } = useDynamicTabs()
  const { actions } = useWebSocket()
  const tab = getTabById(tabId)
  const data = tabData[tabId] as CustomTabData | undefined

  const taskActions = tab?.taskId
    ? actions.filter(a => a.parentId === tab.taskId || a.id === tab.taskId)
    : []

  const hasData = data && (data.content || data.title)

  if (!hasData) {
    return (
      <div className={styles.tabContainer}>
        {taskActions.length > 0 ? (
          <div className={styles.taskContent}>
            <div className={styles.taskHeader}>
              <LayoutPanelLeft size={20} />
              <h3>{tab?.label ?? 'Custom Tab'}</h3>
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
          </div>
        ) : (
          <div className={styles.placeholder}>
            <LayoutPanelLeft size={48} strokeWidth={1.5} />
            <h2>Custom Tab</h2>
            <p>Custom content will appear here.</p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.tabContainer}>
      <div className={styles.taskContent}>
        <div className={styles.taskHeader}>
          <LayoutPanelLeft size={20} />
          <h3>{data.title ?? tab?.label ?? 'Custom'}</h3>
        </div>
        {data.content && (
          <div className={styles.summarySection}>
            <MarkdownContent content={data.content} />
          </div>
        )}
      </div>
    </div>
  )
})
