import { useCallback, useEffect } from 'react'
import { useStore } from 'react-redux'
import { useTranslation } from 'react-i18next'
import type { MetricsTimePeriod } from '../../../types'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { usePersistedState } from '../../../hooks'
import type { RootState } from '../../../store'
import { useAppSelector } from '../../../store/hooks'
import { selectConnected } from '../../../store/selectors/connection'
import {
  selectFilteredMetricsCache,
  selectFilteredMetricsReceivedAt,
} from '../../../store/selectors/dashboard'
import { UI_STATE } from '../../../store/uiState'
import i18n from '../../../i18n/config'
import { formatNumber, formatTime } from '../../../i18n/format'
import styles from './widgets.module.css'

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)

  if (days > 0) {
    return i18n.t('dashboard:duration.dhm', { days, hours, minutes })
  }
  if (hours > 0) {
    return i18n.t('dashboard:duration.hm', { hours, minutes })
  }
  return i18n.t('dashboard:duration.m', { minutes })
}

/**
 * Token counts, abbreviated once they stop being readable: 1,532,532 → "1.5M".
 * Below a million the exact figure still scans, and the tiles showing these are
 * fixed-height, so a long number would have to ellipsize instead.
 *
 * The B branch isn't reachable today but keeps a long-lived agent from
 * rendering "1532.5M".
 */
export function formatTokenCount(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  return formatNumber(n)
}

export function formatBytes(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`
  }
  return `${mb.toFixed(1)} MB`
}

export function formatHour(hour: number): string {
  // Locale-aware hour label (e.g. "3 PM", "15時"). The date's day is irrelevant;
  // only the hour-of-day is formatted.
  return formatTime(new Date(2000, 0, 1, hour), { hour: 'numeric' })
}

export function getChartLabels(period: MetricsTimePeriod): { title: string; description: string } {
  switch (period) {
    case '1h':
      return {
        title: i18n.t('dashboard:widgets.usagePatterns.chart.lastHourTitle'),
        description: i18n.t('dashboard:widgets.usagePatterns.chart.lastHourDesc'),
      }
    case '1d':
      return {
        title: i18n.t('dashboard:widgets.usagePatterns.chart.last24Title'),
        description: i18n.t('dashboard:widgets.usagePatterns.chart.last24Desc'),
      }
    case '1w':
      return {
        title: i18n.t('dashboard:widgets.usagePatterns.chart.last7Title'),
        description: i18n.t('dashboard:widgets.usagePatterns.chart.aggregatedDesc'),
      }
    case '1m':
      return {
        title: i18n.t('dashboard:widgets.usagePatterns.chart.last30Title'),
        description: i18n.t('dashboard:widgets.usagePatterns.chart.aggregatedDesc'),
      }
    case 'total':
      return {
        title: i18n.t('dashboard:widgets.usagePatterns.chart.allTimeTitle'),
        description: i18n.t('dashboard:widgets.usagePatterns.chart.aggregatedDesc'),
      }
    default:
      return {
        title: i18n.t('dashboard:widgets.usagePatterns.chart.defaultTitle'),
        description: '',
      }
  }
}

// How old a period's cached metrics may get while a widget shows them.
const FILTERED_METRICS_MAX_AGE_MS = 10_000
// Last request per period across all widgets, so several widgets showing the
// same period ask once, not once each.
const lastFilteredRequestAt: Partial<Record<MetricsTimePeriod, number>> = {}

// Each time-period-filterable widget owns its own period selection
// (remembered per widget id). "All" reads the live `dashboard_metrics` push
// (the widgets fall back to it), so it ticks with the dashboard. Other periods
// come from the shared Redux cache and are re-requested while shown once they
// are older than FILTERED_METRICS_MAX_AGE_MS.
export function useMetricsPeriod(widgetId: string) {
  const { requestFilteredMetrics } = useWebSocket()
  const connected = useAppSelector(selectConnected)
  const filteredMetricsCache = useAppSelector(selectFilteredMetricsCache)
  const store = useStore<RootState>()
  const [period, setPeriod] = usePersistedState(UI_STATE.dashboard.metricsPeriod(widgetId))

  const refreshIfStale = useCallback((target: MetricsTimePeriod) => {
    if (target === 'total') return
    const now = Date.now()
    const receivedAt = selectFilteredMetricsReceivedAt(store.getState())[target] ?? 0
    const requestedAt = lastFilteredRequestAt[target] ?? 0
    if (now - Math.max(receivedAt, requestedAt) < FILTERED_METRICS_MAX_AGE_MS) return
    lastFilteredRequestAt[target] = now
    requestFilteredMetrics(target)
  }, [store, requestFilteredMetrics])

  const onChange = useCallback((next: MetricsTimePeriod) => {
    setPeriod(next)
    refreshIfStale(next)
  }, [refreshIfStale])

  useEffect(() => {
    if (!connected || period === 'total') return
    refreshIfStale(period)
    const id = window.setInterval(() => refreshIfStale(period), FILTERED_METRICS_MAX_AGE_MS / 2)
    return () => window.clearInterval(id)
  }, [connected, period, refreshIfStale])

  return {
    period,
    onChange,
    filteredData: period === 'total' ? undefined : filteredMetricsCache[period] ?? undefined,
  }
}

interface TimePeriodSelectorProps {
  selected: MetricsTimePeriod
  onChange: (period: MetricsTimePeriod) => void
}

const PERIODS: MetricsTimePeriod[] = ['1h', '1d', '1w', '1m', 'total']
// 1H/1D/1W/1M are compact unit codes shared across locales; only "All" is a word.
const PERIOD_SHORT: Record<Exclude<MetricsTimePeriod, 'total'>, string> = {
  '1h': '1H',
  '1d': '1D',
  '1w': '1W',
  '1m': '1M',
}

export function TimePeriodSelector({ selected, onChange }: TimePeriodSelectorProps) {
  const { t } = useTranslation(['dashboard'])
  return (
    <div className={styles.periodSelector}>
      {PERIODS.map(p => (
        <button
          key={p}
          className={`${styles.periodButton} ${selected === p ? styles.active : ''}`}
          onClick={() => onChange(p)}
        >
          {p === 'total' ? t('dashboard:widgets.periodSelector.all') : PERIOD_SHORT[p]}
        </button>
      ))}
    </div>
  )
}
