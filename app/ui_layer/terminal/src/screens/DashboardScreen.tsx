/**
 * The dashboard: one fixed layout of the browser's widgets, two columns at
 * 120 columns or wider and one below. Status and uptime, tasks, tokens
 * (with a per-step sparkline), requests by hour, system resources, MCP,
 * skills and integrations, the model, Agent Apps and recent activity.
 *
 * Live metrics arrive every two seconds while the screen is open
 * (subscribe_dashboard_metrics on open, unsubscribe on close, again after a
 * reconnect). `[` and `]` change the period of the tasks, tokens and
 * requests sections (dashboard_metrics_filter); "All time" reads the live
 * push, as the browser's widgets do. j/k scroll when it does not fit.
 */
import { useEffect, useMemo, useState } from 'react'
import { Box } from 'ink'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { getSocketClient } from '../../../browser/frontend/src/store/socket/socketInstance'
import { selectConnected, selectVersion } from '../../../browser/frontend/src/store/selectors/connection'
import { selectDashboardMetrics, selectFilteredMetricsCache } from '../../../browser/frontend/src/store/selectors/dashboard'
import { selectActivityOverview, selectRecentActivity } from '../../../browser/frontend/src/store/selectors/activity'
import { selectLatestMessage } from '../../../browser/frontend/src/store/selectors/messages'
import { selectAgentAppProjects } from '../../../browser/frontend/src/store/selectors/agentApp'
import { selectUiState } from '../../../browser/frontend/src/store/selectors/ui'
import { setUiState } from '../../../browser/frontend/src/store/slices/uiSlice'
import { UI_STATE } from '../../../browser/frontend/src/store/uiState'
import { RESOURCES, useResource } from '../../../browser/frontend/src/store/resources'
import { useDerivedAgentStatus } from '../../../browser/frontend/src/hooks/useDerivedAgentStatus'
import type { ActionItem, AgentState, DashboardMetrics, MetricsTimePeriod } from '../../../browser/frontend/src/types'
import { Frame, bodyRows } from '../ui/Frame'
import { bars, compactNumber, meter, sparkline } from '../ui/charts'
import { useScreen, useScreenKeys } from './context'
import { glyphs, ink } from '../theme/theme'
import { displayActionName, actionPreview } from '../chat/activity'
import { padEnd, width as cells } from '../text/width'
import { fitRow, joinColumns, seg, stackSections, type Row } from './dataRows'
import { RowView } from './dataRowView'
import { hourAxis, percent, recordTokens, splitTokens, startSeries, stepPeriod, uptimeParts, type TokenSeries } from './dataDashboard'

const TWO_COLUMNS_AT = 120
const GAP = 3
const LABEL = 13
const FILTER_REFRESH_MS = 10_000
const ACTIVITY_ROWS = 8
const BUCKET_MS = 10_000
const MAX_BUCKETS = 120

const PERIOD_STATE = UI_STATE.dashboard.metricsPeriod('terminal')

type T = TFunction<'screensData'>

function sendIfConnected(type: string, fields: Record<string, unknown> = {}): void {
  const client = getSocketClient()
  if (client.isConnected) client.send(type, fields)
}

function formatUptime(t: T, seconds: number): string {
  const p = uptimeParts(seconds)
  if (p.days > 0) return t('common.duration.dhm', { ...p })
  if (p.hours > 0) return t('common.duration.hm', { ...p })
  return t('common.duration.m', { ...p })
}

function ago(t: T, ms: number | undefined): string {
  if (!ms) return ''
  const diff = Date.now() - ms
  if (diff < 60_000) return t('common.justNow')
  if (diff < 3_600_000) return t('dashboard.activity.minutesAgo', { count: Math.floor(diff / 60_000) })
  if (diff < 86_400_000) return t('dashboard.activity.hoursAgo', { count: Math.floor(diff / 3_600_000) })
  return t('dashboard.activity.daysAgo', { count: Math.floor(diff / 86_400_000) })
}

/** "Tasks ────────── 1D": a section title with a rule to the column's edge. */
function titleRow(title: string, width: number, aside = ''): Row {
  const g = glyphs()
  const room = Math.max(0, width - cells(title) - cells(aside) - 2)
  return [seg(title, undefined, true), seg(` ${g.rule.repeat(room)} `, ink.muted), seg(aside, ink.muted)]
}

function label(text: string): Row[number] {
  return seg(padEnd(text, LABEL), ink.muted)
}

/** "CPU       ████░░░░  23%  detail": label, meter, percent, then the numbers. */
function meterRow(name: string, pct: number, width: number, detail: string, t: T): Row {
  const barWidth = Math.max(4, Math.min(24, width - LABEL - 6 - Math.min(cells(detail) + 2, 26)))
  const high = pct > 80
  return [
    label(name),
    seg(meter(pct / 100, barWidth), high ? ink.warn : ink.brand),
    seg(` ${String(Math.round(pct)).padStart(3)}%`, high ? ink.warn : undefined, high),
    seg(detail ? `  ${detail}` : '', ink.muted),
    seg(high ? `  ${t('dashboard.system.high')}` : '', ink.warn),
  ]
}

const STATE_GLYPH: Record<AgentState, 'idle' | 'busy' | 'unread' | 'failed'> = {
  idle: 'idle',
  thinking: 'busy',
  working: 'busy',
  waiting: 'unread',
  error: 'failed',
}

function activityGlyph(item: ActionItem): { mark: string; color?: string } {
  const g = glyphs()
  switch (item.status) {
    case 'completed':
      return { mark: g.done, color: ink.success }
    case 'error':
      return { mark: g.failed, color: ink.error }
    case 'cancelled':
      return { mark: g.failed, color: ink.muted }
    case 'running':
      return { mark: g.running, color: ink.brand }
    case 'waiting':
      return { mark: g.unread, color: ink.info }
    default:
      return { mark: g.pending, color: ink.muted }
  }
}

export function DashboardScreen() {
  const { t, i18n } = useTranslation('screensData')
  const dispatch = useAppDispatch()
  const { columns, rows } = useScreen()
  const connected = useAppSelector(selectConnected)
  const version = useAppSelector(selectVersion)
  const metrics = useAppSelector(selectDashboardMetrics)
  const filteredCache = useAppSelector(selectFilteredMetricsCache)
  const period = useAppSelector(s => selectUiState(s, PERIOD_STATE)) as MetricsTimePeriod
  const activity = useAppSelector(selectActivityOverview)
  const lastMessage = useAppSelector(selectLatestMessage)
  const recent = useAppSelector(s => selectRecentActivity(s, ACTIVITY_ROWS))
  const projects = useAppSelector(selectAgentAppProjects)
  const status = useDerivedAgentStatus({ activity, lastMessage, connected })
  const [top, setTop] = useState(0)
  useResource(RESOURCES.agentAppsList)

  // Live metrics while open; the server drops subscribers on disconnect, so
  // subscribe again after every reconnect.
  useEffect(() => {
    if (!connected) return
    sendIfConnected('subscribe_dashboard_metrics')
    return () => sendIfConnected('unsubscribe_dashboard_metrics')
  }, [connected])

  // A period other than "All time" is fetched, then refreshed while shown.
  useEffect(() => {
    if (!connected || period === 'total') return
    sendIfConnected('dashboard_metrics_filter', { period })
    const timer = setInterval(() => sendIfConnected('dashboard_metrics_filter', { period }), FILTER_REFRESH_MS)
    return () => clearInterval(timer)
  }, [connected, period])

  const setPeriod = (next: MetricsTimePeriod) => {
    dispatch(setUiState(PERIOD_STATE, next))
    setTop(0)
  }

  const twoColumns = columns >= TWO_COLUMNS_AT
  const usable = Math.max(20, columns - 1)
  const leftWidth = twoColumns ? Math.floor((usable - GAP) / 2) : usable
  const rightWidth = twoColumns ? usable - GAP - leftWidth : usable
  const height = bodyRows(rows)

  const filtered = period === 'total' ? undefined : filteredCache[period] ?? undefined
  // New tokens per 10 s since the screen opened, from the live pushes.
  const [series, setSeries] = useState<TokenSeries>(() => startSeries(BUCKET_MS, Date.now()))
  useEffect(() => {
    if (!metrics) return
    setSeries(prev => recordTokens(prev, splitTokens(metrics.token).total, Date.now(), MAX_BUCKETS))
  }, [metrics])

  const content = useMemo(() => {
    if (!metrics) return [[seg(t('dashboard.waiting'), ink.muted)]] as Row[]
    const sections = buildSections({
      t,
      metrics,
      filtered,
      period,
      statusState: status.state,
      statusMessage: status.message,
      version,
      series,
      locale: i18n.language,
      recent,
      projects,
    })
    if (!twoColumns) {
      const order = [sections.status, sections.tasks, sections.tokens, sections.usage, sections.system, sections.connections, sections.model, sections.apps, sections.activity]
      return stackSections(order.map(build => build(leftWidth))).map(row => fitRow(row, usable))
    }
    const left = stackSections([sections.status, sections.tasks, sections.tokens, sections.usage].map(build => build(leftWidth)))
    const right = stackSections([sections.system, sections.connections, sections.model, sections.apps, sections.activity].map(build => build(rightWidth)))
    return joinColumns(left, right, leftWidth, GAP, rightWidth)
  }, [t, metrics, filtered, period, status.state, status.message, version, series, i18n.language, recent, projects, twoColumns, leftWidth, rightWidth, usable])

  const maxTop = Math.max(0, content.length - height)
  const scroll = Math.min(top, maxTop)

  useScreenKeys((input, key) => {
    if (input === '[' || input === ']') {
      setPeriod(stepPeriod(period, input === ']' ? 1 : -1))
      return true
    }
    if (input === 'r') {
      sendIfConnected('subscribe_dashboard_metrics')
      if (period !== 'total') sendIfConnected('dashboard_metrics_filter', { period })
      return true
    }
    let next: number | null = null
    if (key.downArrow || input === 'j') next = scroll + 1
    else if (key.upArrow || input === 'k') next = scroll - 1
    else if (key.pageDown || input === ' ') next = scroll + height
    else if (key.pageUp) next = scroll - height
    else if (key.home || input === 'g') next = 0
    else if (key.end || input === 'G') next = maxTop
    if (next === null) return false
    setTop(Math.max(0, Math.min(maxTop, next)))
    return true
  })

  const hints = [
    { keys: '[ ]', label: t('dashboard.hint.period') },
    ...(maxTop > 0 ? [{ keys: 'j/k', label: t('common.scroll') }] : []),
    { keys: 'r', label: t('common.refresh') },
    { keys: 'Esc', label: t('common.back') },
  ]

  return (
    <Frame
      title={t('dashboard.title')}
      aside={t('dashboard.aside', { period: t(`dashboard.period.${period}`) })}
      hints={hints}
      columns={columns}
      rows={rows}
    >
      <Box flexDirection="column">
        {content.slice(scroll, scroll + height).map((row, i) => (
          <RowView key={scroll + i} row={row} />
        ))}
      </Box>
    </Frame>
  )
}

interface SectionInput {
  t: T
  metrics: DashboardMetrics
  filtered: { token: DashboardMetrics['token']; task: DashboardMetrics['task']; usage: DashboardMetrics['usage'] } | undefined
  period: MetricsTimePeriod
  statusState: AgentState
  statusMessage: string
  version: string
  series: TokenSeries
  locale: string
  recent: ActionItem[]
  projects: { id: string; name: string; status: string }[]
}

type Section = (width: number) => Row[]

function buildSections(input: SectionInput): Record<string, Section> {
  const { t, metrics, filtered, period, statusState, statusMessage, version, series, locale, recent, projects } = input
  const g = glyphs()
  const short = t(`dashboard.periodShort.${period}`)
  const task = filtered?.task ?? metrics.task
  const tokens = splitTokens(filtered?.token ?? metrics.token)
  const usage = filtered?.usage ?? metrics.usage
  const n = (v: number) => compactNumber(v)

  const status: Section = width => {
    const glyph = g[STATE_GLYPH[statusState] ?? 'idle']
    const color = statusState === 'error' ? ink.error : statusState === 'idle' ? ink.muted : statusState === 'waiting' ? ink.info : ink.brand
    return [
      titleRow(t('dashboard.status.title'), width),
      [seg(`${glyph} `, color), seg(statusMessage, undefined, statusState !== 'idle')],
      [
        seg(t('dashboard.status.uptime', { value: formatUptime(t, metrics.uptimeSeconds) }), ink.muted),
        seg(version ? `  ${g.bullet} ${t('dashboard.status.version', { value: version })}` : '', ink.muted),
      ],
    ]
  }

  const tasks: Section = width => {
    const rate = task.successRate ?? 100
    return [
      titleRow(t('dashboard.tasks.title'), width, short),
      [
        seg(`${g.done} `, ink.success),
        seg(t('dashboard.tasks.completed', { value: n(task.completed) })),
        seg(`   ${g.failed} `, task.failed > 0 ? ink.error : ink.muted),
        seg(t('dashboard.tasks.failed', { value: n(task.failed) })),
        seg(`   ${g.running} `, task.running > 0 ? ink.brand : ink.muted),
        seg(t('dashboard.tasks.running', { value: n(task.running) })),
        seg(`   ${t('dashboard.tasks.total', { value: n(task.total) })}`, ink.muted),
      ],
      [
        label(t('dashboard.tasks.success')),
        seg(meter(rate / 100, Math.max(4, Math.min(24, width - LABEL - 6))), rate < 80 ? ink.warn : ink.success),
        seg(` ${String(Math.round(rate)).padStart(3)}%`),
      ],
    ]
  }

  const tokenSection: Section = width => {
    const barWidth = Math.max(4, Math.min(20, width - LABEL - 14))
    const line = (name: string, value: number, color: string | undefined): Row => {
      const pct = percent(value, tokens.base)
      return [
        label(name),
        seg(meter(pct / 100, barWidth), color),
        seg(` ${String(pct).padStart(3)}%`),
        seg(`  ${n(value)}`, ink.muted),
      ]
    }
    const out: Row[] = [
      titleRow(t('dashboard.tokens.title'), width, `${t('dashboard.tokens.total', { value: n(tokens.total) })} ${g.bullet} ${short}`),
      line(t('dashboard.tokens.input'), tokens.input, ink.brand),
      line(t('dashboard.tokens.output'), tokens.output, ink.info),
      line(t('dashboard.tokens.cached'), tokens.cached, ink.success),
    ]
    const sparkWidth = Math.max(4, width - LABEL)
    const shown = series.buckets.slice(-sparkWidth)
    const since = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(series.start + (series.buckets.length - shown.length) * series.bucketMs)
    out.push([label(t('dashboard.tokens.live')), seg(sparkline(shown, sparkWidth), ink.brand)])
    out.push([
      seg(' '.repeat(LABEL)),
      seg(t('dashboard.tokens.liveLabel', {
        since,
        max: n(Math.max(0, ...shown)),
        last: n(shown[shown.length - 1] ?? 0),
      }), ink.muted),
    ])
    return out
  }

  const usageSection: Section = width => {
    const hourly = usage.hourlyDistribution?.length ? usage.hourlyDistribution : new Array<number>(24).fill(0)
    const requests = hourly.reduce((sum, v) => sum + v, 0)
    const peak = Math.max(...hourly)
    const peakHour = hourly.indexOf(peak)
    const out: Row[] = [titleRow(t('dashboard.usage.title'), width, short)]
    if (requests === 0) {
      out.push([seg(t('dashboard.usage.empty'), ink.muted)])
      return out
    }
    out.push([seg(t('dashboard.usage.summary', { requests: n(requests), hour: String(peakHour).padStart(2, '0'), peak: n(peak) }), ink.muted)])
    const scaleWidth = Math.max(cells(n(peak)), 1) + 1
    const chartWidth = Math.max(24, Math.min(72, width - scaleWidth - 1))
    const chart = bars(hourly, Math.floor(chartWidth / 24) * 24 || chartWidth, 4)
    const nowHour = new Date().getHours()
    chart.forEach((line, i) => {
      out.push([
        seg(line, ink.brand),
        seg(i === 0 ? ` ${n(peak)}` : i === chart.length - 1 ? ' 0' : '', ink.muted),
      ])
    })
    const axisWidth = chart[0]?.length ?? chartWidth
    out.push([
      seg(hourAxis(axisWidth, 24), ink.muted),
      // The last 24 hours: also name the current hour, as the browser marks it.
      seg(period === '1d' ? `  ${g.pointer} ${String(nowHour).padStart(2, '0')}:00 ${n(hourly[nowHour] ?? 0)}` : '', ink.muted),
    ])
    return out
  }

  const system: Section = width => {
    const s = metrics.system
    const pool = metrics.threadPool
    const gb = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`)
    return [
      titleRow(t('dashboard.system.title'), width),
      meterRow(t('dashboard.system.cpu'), s.cpuPercent ?? 0, width, '', t),
      meterRow(t('dashboard.system.memory'), s.memoryPercent ?? 0, width, `${gb(s.memoryUsedMb ?? 0)} / ${gb(s.memoryTotalMb ?? 0)}`, t),
      meterRow(t('dashboard.system.disk'), s.diskPercent ?? 0, width, `${(s.diskUsedGb ?? 0).toFixed(1)} / ${(s.diskTotalGb ?? 0).toFixed(1)} GB`, t),
      meterRow(t('dashboard.system.threads'), pool.utilizationPercent ?? 0, width, `${pool.activeThreads ?? 0} / ${pool.maxWorkers ?? 0}`, t),
      [
        label(t('dashboard.system.network')),
        seg(t('dashboard.system.networkValue', {
          up: (s.networkSentRateKbps ?? 0).toFixed(1),
          down: (s.networkRecvRateKbps ?? 0).toFixed(1),
        })),
      ],
    ]
  }

  const connections: Section = width => {
    const mcp = metrics.mcp
    const skill = metrics.skill
    const integration = metrics.integration
    const topList = (items: { name: string; count: number }[] | undefined): Row | null =>
      items && items.length
        ? [seg(' '.repeat(LABEL)), seg(t('dashboard.connections.top', { list: items.slice(0, 3).map(i => `${i.name} ${n(i.count)}`).join(', ') }), ink.muted)]
        : null
    const rowsOut: (Row | null)[] = [
      titleRow(t('dashboard.connections.title'), width),
      [
        label(t('dashboard.connections.mcp')),
        seg(`${(mcp?.connectedServers ?? 0) > 0 ? g.done : g.idle} `, (mcp?.connectedServers ?? 0) > 0 ? ink.success : ink.muted),
        seg(t('dashboard.connections.mcpValue', {
          connected: mcp?.connectedServers ?? 0,
          total: mcp?.totalServers ?? 0,
          tools: n(mcp?.totalTools ?? 0),
          calls: n(mcp?.totalCalls ?? 0),
        })),
      ],
      topList(mcp?.topTools),
      [
        label(t('dashboard.connections.skills')),
        seg(`${(skill?.enabledSkills ?? 0) > 0 ? g.done : g.idle} `, (skill?.enabledSkills ?? 0) > 0 ? ink.success : ink.muted),
        seg(t('dashboard.connections.skillsValue', {
          enabled: skill?.enabledSkills ?? 0,
          total: skill?.totalSkills ?? 0,
          calls: n(skill?.totalInvocations ?? 0),
        })),
      ],
      topList(skill?.topSkills),
      [
        label(t('dashboard.connections.integrations')),
        seg(`${(integration?.connectedIntegrations ?? 0) > 0 ? g.done : g.idle} `, (integration?.connectedIntegrations ?? 0) > 0 ? ink.success : ink.muted),
        seg(t('dashboard.connections.integrationsValue', {
          connected: integration?.connectedIntegrations ?? 0,
          total: integration?.totalIntegrations ?? 0,
          calls: n(integration?.totalCalls ?? 0),
        })),
      ],
      topList(integration?.topIntegrations),
    ]
    return rowsOut.filter((r): r is Row => r !== null)
  }

  const model: Section = width => {
    const m = metrics.model
    const none = t('dashboard.model.notConfigured')
    return [
      titleRow(t('dashboard.model.title'), width),
      [label(t('dashboard.model.provider')), seg(m?.provider || none)],
      [label(t('dashboard.model.model')), seg(m?.modelName || none, undefined, true)],
      [label(t('dashboard.model.id')), seg(m?.modelId || none, ink.muted)],
    ]
  }

  const apps: Section = width => {
    const running = projects.filter(p => p.status === 'running').length
    const out: Row[] = [titleRow(t('dashboard.apps.title'), width, t('dashboard.apps.summary', { installed: projects.length, running }))]
    if (projects.length === 0) {
      out.push([seg(t('dashboard.apps.empty'), ink.muted)])
      return out
    }
    const shown = projects.slice(0, 4)
    const nameWidth = Math.max(10, Math.min(32, width - 16))
    for (const p of shown) {
      const on = p.status === 'running'
      out.push([
        seg(`${on ? g.unread : g.idle} `, on ? ink.success : ink.muted),
        ...fitRow([seg(p.name)], nameWidth),
        seg(`  ${p.status}`, on ? ink.success : ink.muted),
      ])
    }
    if (projects.length > shown.length) out.push([seg(t('dashboard.apps.more', { count: projects.length - shown.length }), ink.muted)])
    return out
  }

  const activitySection: Section = width => {
    const items = recent.slice(-ACTIVITY_ROWS).reverse()
    const out: Row[] = [titleRow(t('dashboard.activity.title'), width)]
    if (items.length === 0) {
      out.push([seg(t('dashboard.activity.empty'), ink.muted)])
      return out
    }
    for (const item of items) {
      const { mark, color } = activityGlyph(item)
      const name = item.itemType === 'reasoning' ? t('dashboard.activity.reasoning') : displayActionName(item.name)
      const tokensUsed = (item.inputTokens ?? 0) + (item.outputTokens ?? 0)
      const meta = [ago(t, item.createdAt), tokensUsed > 0 ? t('dashboard.activity.tokens', { value: n(tokensUsed) }) : '']
        .filter(Boolean)
        .join(` ${g.bullet} `)
      const metaWidth = cells(meta)
      const nameWidth = Math.min(18, Math.max(8, Math.floor(width / 4)))
      const previewWidth = Math.max(0, width - 2 - nameWidth - 1 - metaWidth - 2)
      const preview = item.itemType === 'reasoning' ? '' : actionPreview(item).replace(/\s+/g, ' ')
      out.push([
        seg(`${mark} `, color),
        ...fitRow([seg(name)], nameWidth),
        seg(' '),
        ...fitRow([seg(preview, ink.muted)], previewWidth),
        seg(`  ${meta}`, ink.muted),
      ])
    }
    return out
  }

  return {
    status,
    tasks,
    tokens: tokenSection,
    usage: usageSection,
    system,
    connections,
    model,
    apps,
    activity: activitySection,
  }
}
