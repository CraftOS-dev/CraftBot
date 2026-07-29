import { CheckCircle, PlayCircle, TrendingUp, XCircle } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { Badge } from '../../../components/ui'
import { TimePeriodSelector, useMetricsPeriod } from './shared'
import styles from './widgets.module.css'

export function TaskStatsWidget() {
  const { dashboardMetrics } = useWebSocket()
  const { period, onChange, filteredData } = useMetricsPeriod()

  const taskCompleted = filteredData?.task.completed ?? (dashboardMetrics?.task.completed ?? 0)
  const taskFailed = filteredData?.task.failed ?? (dashboardMetrics?.task.failed ?? 0)
  const taskRunning = filteredData?.task.running ?? (dashboardMetrics?.task.running ?? 0)
  const taskTotal = filteredData?.task.total ?? (dashboardMetrics?.task.total ?? 0)
  const taskSuccessRate = filteredData?.task.successRate ?? (dashboardMetrics?.task.successRate ?? 100)

  return (
    <>
      <div className={styles.bodyBadgeRow}>
        <Badge variant="default">{taskTotal} total</Badge>
      </div>
      <TimePeriodSelector selected={period} onChange={onChange} />
      <div className={styles.statsGrid}>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <CheckCircle size={12} className={styles.successIcon} />
            <span className={styles.statLabel}>Completed</span>
          </div>
          <span className={styles.statValue}>{taskCompleted}</span>
        </div>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <XCircle size={12} className={styles.errorIcon} />
            <span className={styles.statLabel}>Failed</span>
          </div>
          <span className={styles.statValue}>{taskFailed}</span>
        </div>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <PlayCircle size={12} className={styles.primaryIcon} />
            <span className={styles.statLabel}>Running</span>
          </div>
          <span className={styles.statValue}>{taskRunning}</span>
        </div>
        <div className={styles.statItem}>
          <div className={styles.statHeader}>
            <TrendingUp size={12} className={styles.successIcon} />
            <span className={styles.statLabel}>Success</span>
          </div>
          <span className={styles.statValue}>{taskSuccessRate.toFixed(0)}%</span>
        </div>
      </div>
    </>
  )
}
