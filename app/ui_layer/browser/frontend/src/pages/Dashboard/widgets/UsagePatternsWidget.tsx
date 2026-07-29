import { useWebSocket } from '../../../contexts/WebSocketContext'
import { Badge } from '../../../components/ui'
import { TimePeriodSelector, formatHour, getChartLabels, useMetricsPeriod } from './shared'
import styles from './widgets.module.css'

export function UsagePatternsWidget() {
  const { dashboardMetrics } = useWebSocket()
  const { period, onChange, filteredData } = useMetricsPeriod()

  const peakHour = filteredData?.usage.peakHour ?? (dashboardMetrics?.usage.peakHour ?? 0)
  const hourlyDistribution = filteredData?.usage.hourlyDistribution ?? (dashboardMetrics?.usage.hourlyDistribution ?? Array(24).fill(0))
  const usageRequestCount = hourlyDistribution.reduce((sum, count) => sum + count, 0)
  const maxHourlyRequests = Math.max(...hourlyDistribution, 1)
  const labels = getChartLabels(period)

  return (
    <>
      <div className={styles.bodyBadgeRow}>
        <Badge variant="default">{usageRequestCount} requests</Badge>
      </div>
      <TimePeriodSelector selected={period} onChange={onChange} />
      <div className={styles.usageStats}>
        <div className={styles.usageStat}>
          <span className={styles.usageLabel}>Requests</span>
          <span className={styles.usageValue}>{usageRequestCount}</span>
        </div>
        <div className={styles.usageStat}>
          <span className={styles.usageLabel}>Peak Hour</span>
          <span className={styles.usageValue}>{formatHour(peakHour)}</span>
        </div>
        <div className={styles.usageStat}>
          <span className={styles.usageLabel}>Peak Count</span>
          <span className={styles.usageValue}>{Math.max(...hourlyDistribution)}</span>
        </div>
      </div>
      <div className={styles.hourlyChart}>
        <div className={styles.chartLabel}>
          {labels.title}
          <span className={styles.chartSubLabel}> · {labels.description}</span>
        </div>
        <div className={styles.chartBars}>
          {hourlyDistribution.map((count, hour) => (
            <div key={hour} className={styles.chartBarWrapper} title={`${formatHour(hour)}: ${count} requests`}>
              <div
                className={`${styles.chartBar} ${period === '1d' && hour === new Date().getHours() ? styles.currentHour : ''}`}
                style={{ height: `${(count / maxHourlyRequests) * 100}%` }}
              />
            </div>
          ))}
        </div>
        <div className={styles.chartTimeLabels}>
          <span>12AM</span>
          <span>6AM</span>
          <span>12PM</span>
          <span>6PM</span>
        </div>
      </div>
    </>
  )
}
