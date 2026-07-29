import { useState } from 'react'
import { Activity, CheckCircle } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from './widgets.module.css'

export function IntegrationsWidget() {
  const { dashboardMetrics } = useWebSocket()
  const [showAll, setShowAll] = useState(false)

  const integrationConnected = dashboardMetrics?.integration?.connectedIntegrations ?? 0
  const integrationTotalCalls = dashboardMetrics?.integration?.totalCalls ?? 0
  const topIntegrations = dashboardMetrics?.integration?.topIntegrations ?? []

  return (
    <>
      <div className={styles.compactStats}>
        <div className={styles.compactStatItem}>
          <CheckCircle size={14} className={styles.successIcon} />
          <span className={styles.compactStatValue}>{integrationConnected}</span>
          <span className={styles.compactStatLabel}>Connected</span>
        </div>
        <div className={styles.compactStatItem}>
          <Activity size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{integrationTotalCalls}</span>
          <span className={styles.compactStatLabel}>Total Calls</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>Top Integrations</div>
        {topIntegrations.length > 0 ? (
          <div className={styles.usageList}>
            {(showAll ? topIntegrations : topIntegrations.slice(0, 3)).map((intg, index) => (
              <div key={intg.name} className={styles.usageItem}>
                <span className={styles.usageRank}>#{index + 1}</span>
                <span className={styles.usageName}>{intg.name}</span>
                <span className={styles.usageCount}>{intg.count}</span>
              </div>
            ))}
            {topIntegrations.length > 3 && (
              <button className={styles.viewAllButton} onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show less' : `View all (${topIntegrations.length})`}
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
