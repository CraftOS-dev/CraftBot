import { useTranslation } from 'react-i18next'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { formatNumber } from '../../../i18n/format'
import { TimePeriodSelector, formatHour, getChartLabels, useMetricsPeriod } from './shared'
import styles from './widgets.module.css'

export function UsagePatternsWidget() {
  const { t } = useTranslation(['dashboard'])
  const { dashboardMetrics } = useWebSocket()
  const { period, onChange, filteredData } = useMetricsPeriod()

  const peakHour = filteredData?.usage.peakHour ?? (dashboardMetrics?.usage.peakHour ?? 0)
  const hourlyDistribution = filteredData?.usage.hourlyDistribution ?? (dashboardMetrics?.usage.hourlyDistribution ?? Array(24).fill(0))
  const usageRequestCount = hourlyDistribution.reduce((sum, count) => sum + count, 0)
  const maxHourlyRequests = Math.max(...hourlyDistribution, 1)
  const labels = getChartLabels(period)

  return (
    <>
      <TimePeriodSelector selected={period} onChange={onChange} />
      <div className={styles.usageStats}>
        <div className={styles.usageStat}>
          <span className={styles.usageLabel}>{t('dashboard:widgets.usagePatterns.requests')}</span>
          <span className={styles.usageValue}>{formatNumber(usageRequestCount)}</span>
        </div>
        <div className={styles.usageStat}>
          <span className={styles.usageLabel}>{t('dashboard:widgets.usagePatterns.peakHour')}</span>
          <span className={styles.usageValue}>{formatHour(peakHour)}</span>
        </div>
        <div className={styles.usageStat}>
          <span className={styles.usageLabel}>{t('dashboard:widgets.usagePatterns.peakCount')}</span>
          <span className={styles.usageValue}>{formatNumber(Math.max(...hourlyDistribution))}</span>
        </div>
      </div>
      <div className={styles.hourlyChart}>
        <div className={styles.chartLabel}>
          {labels.title}
          <span className={styles.chartSubLabel}> · {labels.description}</span>
        </div>
        <div className={styles.chartBars}>
          {hourlyDistribution.map((count, hour) => (
            <div key={hour} className={styles.chartBarWrapper} title={t('dashboard:widgets.usagePatterns.barTooltip', { time: formatHour(hour), count })}>
              <div
                className={`${styles.chartBar} ${period === '1d' && hour === new Date().getHours() ? styles.currentHour : ''}`}
                style={{ height: `${(count / maxHourlyRequests) * 100}%` }}
              />
            </div>
          ))}
        </div>
        <div className={styles.chartTimeLabels}>
          <span>{formatHour(0)}</span>
          <span>{formatHour(6)}</span>
          <span>{formatHour(12)}</span>
          <span>{formatHour(18)}</span>
        </div>
      </div>
    </>
  )
}

// No title-bar badge here on purpose: the request count it showed is already
// the first of the three tiles in the body, and the all-time figure disagreed
// with them whenever a period other than All was selected.
