import { useState } from 'react'
import { Activity, CheckCircle } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from './widgets.module.css'

export function McpServersWidget() {
  const { dashboardMetrics } = useWebSocket()
  const [showAll, setShowAll] = useState(false)

  const mcpConnectedServers = dashboardMetrics?.mcp?.connectedServers ?? 0
  const mcpTotalCalls = dashboardMetrics?.mcp?.totalCalls ?? 0
  const mcpTopTools = dashboardMetrics?.mcp?.topTools ?? []

  return (
    <>
      <div className={styles.compactStats}>
        <div className={styles.compactStatItem}>
          <CheckCircle size={14} className={styles.successIcon} />
          <span className={styles.compactStatValue}>{mcpConnectedServers}</span>
          <span className={styles.compactStatLabel}>Connected</span>
        </div>
        <div className={styles.compactStatItem}>
          <Activity size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{mcpTotalCalls}</span>
          <span className={styles.compactStatLabel}>Calls</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>Top Tools</div>
        {mcpTopTools.length > 0 ? (
          <div className={styles.usageList}>
            {(showAll ? mcpTopTools : mcpTopTools.slice(0, 3)).map((tool, index) => (
              <div key={tool.name} className={styles.usageItem}>
                <span className={styles.usageRank}>#{index + 1}</span>
                <span className={styles.usageName}>{tool.name}</span>
                <span className={styles.usageCount}>{tool.count}</span>
              </div>
            ))}
            {mcpTopTools.length > 3 && (
              <button className={styles.viewAllButton} onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show less' : `View all (${mcpTopTools.length})`}
              </button>
            )}
          </div>
        ) : (
          <div className={styles.emptyUsage}>No usage yet</div>
        )}
      </div>
    </>
  )
}
