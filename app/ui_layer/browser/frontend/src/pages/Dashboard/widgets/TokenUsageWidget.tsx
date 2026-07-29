import { useWebSocket } from '../../../contexts/WebSocketContext'
import { Badge } from '../../../components/ui'
import { TimePeriodSelector, useMetricsPeriod } from './shared'
import styles from './widgets.module.css'

export function TokenUsageWidget() {
  const { dashboardMetrics } = useWebSocket()
  const { period, onChange, filteredData } = useMetricsPeriod()

  const inputTokens = filteredData?.token.input ?? (dashboardMetrics?.token.input ?? 0)
  const outputTokens = filteredData?.token.output ?? (dashboardMetrics?.token.output ?? 0)
  const totalTokens = filteredData?.token.total ?? (dashboardMetrics?.token.total ?? 0)
  const cachedTokens = filteredData?.token.cached ?? (dashboardMetrics?.token.cached ?? 0)

  const inputRatio = totalTokens > 0 ? Math.round((inputTokens / totalTokens) * 100) : 0
  const outputRatio = totalTokens > 0 ? Math.round((outputTokens / totalTokens) * 100) : 0
  const cachedRatio = inputTokens > 0 ? Math.min(100, Math.round((cachedTokens / inputTokens) * 100)) : 0

  return (
    <>
      <TimePeriodSelector selected={period} onChange={onChange} />
      <div className={styles.tokenRatioDisplay}>
        <div className={styles.tokenRatioBar}>
          <div className={styles.tokenInputBar} style={{ width: `${inputRatio}%` }} />
          <div className={styles.tokenOutputBar} style={{ width: `${outputRatio}%` }} />
        </div>
        <div className={styles.tokenRatioLabels}>
          <div className={styles.tokenRatioItem}>
            <span className={styles.tokenInputDot} />
            <span>Input</span>
            <span className={styles.tokenRatioValue}>{inputRatio}%</span>
          </div>
          <div className={styles.tokenRatioItem}>
            <span className={styles.tokenOutputDot} />
            <span>Output</span>
            <span className={styles.tokenRatioValue}>{outputRatio}%</span>
          </div>
          <div className={styles.tokenRatioItem}>
            <span className={styles.tokenCachedDot} />
            <span>Cached</span>
            <span className={styles.tokenRatioValue}>{cachedRatio}%</span>
          </div>
        </div>
      </div>
      <div className={styles.tokenDetails}>
        <div className={styles.tokenDetail}>
          <span className={styles.tokenDetailLabel}>Input</span>
          <span className={styles.tokenDetailValue}>{inputTokens.toLocaleString()}</span>
        </div>
        <div className={styles.tokenDetail}>
          <span className={styles.tokenDetailLabel}>Output</span>
          <span className={styles.tokenDetailValue}>{outputTokens.toLocaleString()}</span>
        </div>
        <div className={styles.tokenDetail}>
          <span className={styles.tokenDetailLabel}>Cached</span>
          <span className={styles.tokenDetailValue}>{cachedTokens.toLocaleString()}</span>
        </div>
      </div>
    </>
  )
}

// Rendered separately, in WidgetChrome's title bar — see TaskStatsHeaderBadge
// for why this always shows the all-time total rather than the currently
// selected period.
export function TokenUsageHeaderBadge() {
  const { dashboardMetrics } = useWebSocket()
  return <Badge variant="default">{(dashboardMetrics?.token.total ?? 0).toLocaleString()} total</Badge>
}
