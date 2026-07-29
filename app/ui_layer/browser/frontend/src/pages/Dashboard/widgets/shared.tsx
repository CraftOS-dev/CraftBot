import { useCallback, useEffect, useState } from 'react'
import type { MetricsTimePeriod } from '../../../types'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import styles from './widgets.module.css'

export function formatBytes(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`
  }
  return `${mb.toFixed(1)} MB`
}

export function formatHour(hour: number): string {
  const ampm = hour >= 12 ? 'PM' : 'AM'
  const h = hour % 12 || 12
  return `${h}:00 ${ampm}`
}

export function getChartLabels(period: MetricsTimePeriod): { title: string; description: string } {
  switch (period) {
    case '1h':
      return { title: 'Last Hour', description: 'Requests by hour of day' }
    case '1d':
      return { title: 'Last 24 Hours', description: 'Requests by hour' }
    case '1w':
      return { title: 'Last 7 Days', description: 'Aggregated by hour of day' }
    case '1m':
      return { title: 'Last 30 Days', description: 'Aggregated by hour of day' }
    case 'total':
      return { title: 'All Time', description: 'Aggregated by hour of day' }
    default:
      return { title: 'Hourly Distribution', description: '' }
  }
}

// Each time-period-filterable widget owns its own period selection and
// requests+caches that period's metrics on demand (the cache is shared
// app-wide via Redux, so switching back to an already-seen period is free).
export function useMetricsPeriod(initial: MetricsTimePeriod = 'total') {
  const { connected, filteredMetricsCache, requestFilteredMetrics } = useWebSocket()
  const [period, setPeriod] = useState<MetricsTimePeriod>(initial)

  const onChange = useCallback((next: MetricsTimePeriod) => {
    setPeriod(next)
    if (!filteredMetricsCache[next]) {
      requestFilteredMetrics(next)
    }
  }, [filteredMetricsCache, requestFilteredMetrics])

  // Request the current period's data once connected, if not already cached
  // (mirrors the widget being newly added to a layout, or a fresh page load).
  useEffect(() => {
    if (connected && !filteredMetricsCache[period]) {
      requestFilteredMetrics(period)
    }
  }, [connected, period, filteredMetricsCache, requestFilteredMetrics])

  return { period, onChange, filteredData: filteredMetricsCache[period] }
}

interface TimePeriodSelectorProps {
  selected: MetricsTimePeriod
  onChange: (period: MetricsTimePeriod) => void
}

const PERIODS: MetricsTimePeriod[] = ['1h', '1d', '1w', '1m', 'total']
const PERIOD_LABELS: Record<MetricsTimePeriod, string> = {
  '1h': '1H',
  '1d': '1D',
  '1w': '1W',
  '1m': '1M',
  'total': 'All',
}

export function TimePeriodSelector({ selected, onChange }: TimePeriodSelectorProps) {
  return (
    <div className={styles.periodSelector}>
      {PERIODS.map(p => (
        <button
          key={p}
          className={`${styles.periodButton} ${selected === p ? styles.active : ''}`}
          onClick={() => onChange(p)}
        >
          {PERIOD_LABELS[p]}
        </button>
      ))}
    </div>
  )
}
