import { useWebSocket } from '../../../contexts/WebSocketContext'
import { Badge } from '../../../components/ui'
import { TimePeriodSelector, useMetricsPeriod } from './shared'
import styles from './widgets.module.css'

export function TokenUsageWidget() {
  const { dashboardMetrics } = useWebSocket()
  const { period, onChange, filteredData } = useMetricsPeriod()

  const rawInputTokens = filteredData?.token.input ?? (dashboardMetrics?.token.input ?? 0)
  const outputTokens = filteredData?.token.output ?? (dashboardMetrics?.token.output ?? 0)
  const cachedTokens = filteredData?.token.cached ?? (dashboardMetrics?.token.cached ?? 0)

  // `token.input` from the API is the full prompt size — cache reads included.
  // The Input tile shows only the genuinely new tokens; Cached shows the rest.
  const inputTokens = Math.max(0, rawInputTokens - cachedTokens)

  // Denominator for all three ratios, so the segments of the bar sum to 100%.
  // Deliberately not `token.total` from the API: that is rawInput + output, so
  // it double-counts cache reads and made the three percentages sum past 100.
  const ratioBase = inputTokens + outputTokens + cachedTokens

  const inputRatio = ratioBase > 0 ? Math.round((inputTokens / ratioBase) * 100) : 0
  const outputRatio = ratioBase > 0 ? Math.round((outputTokens / ratioBase) * 100) : 0
  const cachedRatio = ratioBase > 0 ? Math.min(100, Math.round((cachedTokens / ratioBase) * 100)) : 0

  return (
    <>
      <TimePeriodSelector selected={period} onChange={onChange} />
      <div className={styles.tokenRatioDisplay}>
        <div className={styles.tokenRatioBar}>
          <div className={styles.tokenInputBar} style={{ width: `${inputRatio}%` }} />
          <div className={styles.tokenOutputBar} style={{ width: `${outputRatio}%` }} />
          <div className={styles.tokenCachedBar} style={{ width: `${cachedRatio}%` }} />
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
  // Derived rather than read from `token.total`, which is rawInput + output and
  // so double-counts cache reads. Counts new tokens only, matching the tiles.
  const rawInput = dashboardMetrics?.token.input ?? 0
  const output = dashboardMetrics?.token.output ?? 0
  const cached = dashboardMetrics?.token.cached ?? 0
  const total = Math.max(0, rawInput - cached) + output
  return <Badge variant="default">{total.toLocaleString()} total</Badge>
}
