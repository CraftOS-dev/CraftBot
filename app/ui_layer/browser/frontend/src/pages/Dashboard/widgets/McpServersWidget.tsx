import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, CheckCircle } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { formatNumber } from '../../../i18n/format'
import styles from './widgets.module.css'

export function McpServersWidget() {
  const { t } = useTranslation(['dashboard', 'common'])
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
          <span className={styles.compactStatValue}>{formatNumber(mcpConnectedServers)}</span>
          <span className={styles.compactStatLabel}>{t('common:status.connected')}</span>
        </div>
        <div className={styles.compactStatItem}>
          <Activity size={14} className={styles.primaryIcon} />
          <span className={styles.compactStatValue}>{formatNumber(mcpTotalCalls)}</span>
          <span className={styles.compactStatLabel}>{t('dashboard:widgets.mcpServers.calls')}</span>
        </div>
      </div>
      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>{t('dashboard:widgets.mcpServers.topTools')}</div>
        {mcpTopTools.length > 0 ? (
          <div className={styles.usageList}>
            {(showAll ? mcpTopTools : mcpTopTools.slice(0, 3)).map((tool, index) => (
              <div key={tool.name} className={styles.usageItem}>
                <span className={styles.usageRank}>#{index + 1}</span>
                <span className={styles.usageName}>{tool.name}</span>
                <span className={styles.usageCount}>{formatNumber(tool.count)}</span>
              </div>
            ))}
            {mcpTopTools.length > 3 && (
              <button className={styles.viewAllButton} onClick={() => setShowAll(!showAll)}>
                {showAll ? t('common:actions.showLess') : t('dashboard:widgets.common.viewAllCount', { count: mcpTopTools.length })}
              </button>
            )}
          </div>
        ) : (
          <div className={styles.emptyUsage}>{t('dashboard:widgets.common.noUsage')}</div>
        )}
      </div>
    </>
  )
}
