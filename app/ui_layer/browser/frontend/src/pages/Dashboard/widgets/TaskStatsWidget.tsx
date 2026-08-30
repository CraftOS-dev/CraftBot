import { CheckCircle, PlayCircle, TrendingUp, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { Badge } from '../../../components/ui'
import { formatNumber } from '../../../i18n/format'
import { TimePeriodSelector, useMetricsPeriod } from './shared'
import styles from './widgets.module.css'

export function TaskStatsWidget() {
  const { t } = useTranslation(['dashboard'])
  const { dashboardMetrics } = useWebSocket()
  const { period, onChange, filteredData } = useMetricsPeriod()

  const taskCompleted = filteredData?.task.completed ?? (dashboardMetrics?.task.completed ?? 0)
  const taskFailed = filteredData?.task.failed ?? (dashboardMetrics?.task.failed ?? 0)
  const taskRunning = filteredData?.task.running ?? (dashboardMetrics?.task.running ?? 0)
  const taskSuccessRate = filteredData?.task.successRate ?? (dashboardMetrics?.task.successRate ?? 100)

  return (
    <>
      <TimePeriodSelector selected={period} onChange={onChange} />
      <div className={styles.statsGrid}>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <CheckCircle size={12} className={styles.successIcon} />
            <span className={styles.statLabel}>{t('dashboard:widgets.taskStats.completed')}</span>
          </div>
          <span className={styles.statValue}>{formatNumber(taskCompleted)}</span>
        </div>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <XCircle size={12} className={styles.errorIcon} />
            <span className={styles.statLabel}>{t('dashboard:widgets.taskStats.failed')}</span>
          </div>
          <span className={styles.statValue}>{formatNumber(taskFailed)}</span>
        </div>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <PlayCircle size={12} className={styles.primaryIcon} />
            <span className={styles.statLabel}>{t('dashboard:widgets.taskStats.running')}</span>
          </div>
          <span className={styles.statValue}>{formatNumber(taskRunning)}</span>
        </div>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <TrendingUp size={12} className={styles.successIcon} />
            <span className={styles.statLabel}>{t('dashboard:widgets.taskStats.success')}</span>
          </div>
          <span className={styles.statValue}>{taskSuccessRate.toFixed(0)}%</span>
        </div>
      </div>
    </>
  )
}

// Rendered separately, in WidgetChrome's title bar. Always shows the
// all-time total (dashboardMetrics), independent of whichever period the
// body's TimePeriodSelector currently has selected — the badge and body
// are separate React subtrees with no shared local state.
export function TaskStatsHeaderBadge() {
  const { t } = useTranslation(['dashboard'])
  const { dashboardMetrics } = useWebSocket()
  const total = dashboardMetrics?.task.total ?? 0
  return <Badge variant="default">{t('dashboard:widgets.taskStats.total', { total: formatNumber(total) })}</Badge>
}
