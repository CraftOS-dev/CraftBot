import { useState, useEffect, useCallback } from 'react'
import {
  Activity,
  Package,
  CheckCircle,
  XCircle,
  Cpu,
  TrendingUp,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  Timer,
  PlayCircle,
  Hammer,
  Bot,
  Building2,
  Hash,
  Globe
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { Badge, StatusIndicator } from '../../components/ui'
import { useDerivedAgentStatus } from '../../hooks'
import type { MetricsTimePeriod } from '../../types'
import styles from './DashboardPage.module.css'

// Compact time period selector for inside cards
interface TimePeriodSelectorProps {
  selected: MetricsTimePeriod
  onChange: (period: MetricsTimePeriod) => void
}

function TimePeriodSelector({ selected, onChange }: TimePeriodSelectorProps) {
  const periods: MetricsTimePeriod[] = ['1h', '1d', '1w', '1m', 'total']
  const labels: Record<MetricsTimePeriod, string> = {
    '1h': '1H',
    '1d': '1D',
    '1w': '1W',
    '1m': '1M',
    'total': 'All'
  }

  return (
    <div className={styles.periodSelector}>
      {periods.map(p => (
        <button
          key={p}
          className={`${styles.periodButton} ${selected === p ? styles.active : ''}`}
          onClick={() => onChange(p)}
        >
          {labels[p]}
        </button>
      ))}
    </div>
  )
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)

  if (days > 0) {
    return `${days}d ${hours}h ${mins}m`
  }
  if (hours > 0) {
    return `${hours}h ${mins}m`
  }
  return `${mins}m`
}

function formatBytes(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`
  }
  return `${mb.toFixed(1)} MB`
}

function formatHour(hour: number): string {
  const ampm = hour >= 12 ? 'PM' : 'AM'
  const h = hour % 12 || 12
  return `${h}:00 ${ampm}`
}

function getChartLabels(period: MetricsTimePeriod): { title: string; description: string } {
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

export function DashboardPage() {
  const { connected, actions, messages, dashboardMetrics, filteredMetricsCache, requestFilteredMetrics, subscribeDashboardMetrics, unsubscribeDashboardMetrics } = useWebSocket()

  // Derive agent status from actions and messages
  const status = useDerivedAgentStatus({
    actions,
    messages,
    connected,
  })

  // Time period state for each card
  const [taskPeriod, setTaskPeriod] = useState<MetricsTimePeriod>('total')
  const [tokenPeriod, setTokenPeriod] = useState<MetricsTimePeriod>('total')
  const [usagePeriod, setUsagePeriod] = useState<MetricsTimePeriod>('total')

  // Expand/collapse state for top tools/skills/integrations lists
  const [showAllTools, setShowAllTools] = useState(false)
  const [showAllSkills, setShowAllSkills] = useState(false)
  const [showAllIntegrations, setShowAllIntegrations] = useState(false)

  // Request filtered metrics when period changes (for all periods including 'total')
  const handlePeriodChange = useCallback((
    period: MetricsTimePeriod,
    setter: (p: MetricsTimePeriod) => void
  ) => {
    setter(period)
    if (!filteredMetricsCache[period]) {
      // Request if not already cached (including 'total' for historical data)
      requestFilteredMetrics(period)
    }
  }, [requestFilteredMetrics, filteredMetricsCache])

  // Subscribe to live metrics while on this page, unsubscribe on leave
  useEffect(() => {
    subscribeDashboardMetrics()
    return () => {
      unsubscribeDashboardMetrics()
    }
  }, [subscribeDashboardMetrics, unsubscribeDashboardMetrics])

  // Request 'total' metrics on initial load
  useEffect(() => {
    if (connected && !filteredMetricsCache['total']) {
      requestFilteredMetrics('total')
    }
  }, [connected, requestFilteredMetrics, filteredMetricsCache])

  // Use metrics from WebSocket if available
  const metrics = dashboardMetrics

  // Calculate values with fallbacks
  const uptime = metrics?.uptimeSeconds ? formatUptime(metrics.uptimeSeconds) : '0m'

  // Token metrics - use cached filtered metrics for all periods (including 'total')
  const tokenFilteredData = filteredMetricsCache[tokenPeriod]
  const inputTokens = tokenFilteredData?.token.input ?? (metrics?.token.input ?? 0)
  const outputTokens = tokenFilteredData?.token.output ?? (metrics?.token.output ?? 0)
  const totalTokens = tokenFilteredData?.token.total ?? (metrics?.token.total ?? 0)
  const cachedTokens = tokenFilteredData?.token.cached ?? (metrics?.token.cached ?? 0)

  // Calculate token ratios
  const inputRatio = totalTokens > 0 ? Math.round((inputTokens / totalTokens) * 100) : 0
  const outputRatio = totalTokens > 0 ? Math.round((outputTokens / totalTokens) * 100) : 0
  const cachedRatio = inputTokens > 0 ? Math.min(100, Math.round((cachedTokens / inputTokens) * 100)) : 0

  const cpuPercent = metrics?.system.cpuPercent ?? 0
  const memoryPercent = metrics?.system.memoryPercent ?? 0
  const memoryUsed = metrics?.system.memoryUsedMb ?? 0
  const memoryTotal = metrics?.system.memoryTotalMb ?? 0
  const diskPercent = metrics?.system.diskPercent ?? 0
  const diskUsed = metrics?.system.diskUsedGb ?? 0
  const diskTotal = metrics?.system.diskTotalGb ?? 0
  const networkSentRate = metrics?.system.networkSentRateKbps ?? 0
  const networkRecvRate = metrics?.system.networkRecvRateKbps ?? 0

  const threadPoolActive = metrics?.threadPool.activeThreads ?? 0
  const threadPoolMax = metrics?.threadPool.maxWorkers ?? 16
  const threadPoolUtil = metrics?.threadPool.utilizationPercent ?? 0

  // Usage metrics - use cached filtered metrics for all periods (including 'total')
  const usageFilteredData = filteredMetricsCache[usagePeriod]
  const peakHour = usageFilteredData?.usage.peakHour ?? (metrics?.usage.peakHour ?? 0)
  const hourlyDistribution = usageFilteredData?.usage.hourlyDistribution ?? (metrics?.usage.hourlyDistribution ?? Array(24).fill(0))
  const usageRequestCount = hourlyDistribution.reduce((sum, count) => sum + count, 0)

  // Find max for scaling the hourly chart
  const maxHourlyRequests = Math.max(...hourlyDistribution, 1)

  // Task counts - use cached filtered metrics for all periods (including 'total')
  const taskFilteredData = filteredMetricsCache[taskPeriod]
  const taskCompleted = taskFilteredData?.task.completed ?? (metrics?.task.completed ?? 0)
  const taskFailed = taskFilteredData?.task.failed ?? (metrics?.task.failed ?? 0)
  const taskRunning = taskFilteredData?.task.running ?? (metrics?.task.running ?? 0)
  const taskTotal = taskFilteredData?.task.total ?? (metrics?.task.total ?? 0)
  const taskSuccessRate = taskFilteredData?.task.successRate ?? (metrics?.task.successRate ?? 100)

  // MCP metrics
  const mcpConnectedServers = metrics?.mcp?.connectedServers ?? 0
  const mcpTotalCalls = metrics?.mcp?.totalCalls ?? 0
  const mcpTopTools = metrics?.mcp?.topTools ?? []

  // Skill metrics
  const skillEnabled = metrics?.skill?.enabledSkills ?? 0
  const skillTotalInvocations = metrics?.skill?.totalInvocations ?? 0
  const topSkills = metrics?.skill?.topSkills ?? []

  // Integration metrics
  const integrationConnected = metrics?.integration?.connectedIntegrations ?? 0
  const integrationTotalCalls = metrics?.integration?.totalCalls ?? 0
  const topIntegrations = metrics?.integration?.topIntegrations ?? []

  // Model metrics
  const modelProvider = metrics?.model?.provider ?? ''
  const modelId = metrics?.model?.modelId ?? ''
  const modelName = metrics?.model?.modelName ?? ''

  return (
    <div className={styles.dashboard}>
      {/* Header Section */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <div className={styles.agentStatus}>
            <StatusIndicator status={status.state} size="lg" variant="dot" />
            <div>
              <h2>Agent Status</h2>
              <p>{status.message}</p>
            </div>
          </div>
          <div className={styles.headerRight}>
            <div className={styles.uptimeDisplay}>
              <Timer size={12} />
              <span>Uptime: {uptime}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Panels Section */}
      <div className={styles.panelsGrid}>
        {/* Task Stats Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Activity size={16} />
            <h3>Task Statistics</h3>
            <Badge variant="default">{taskTotal} total</Badge>
          </div>
          <div className={styles.panelContent}>
            <TimePeriodSelector
              selected={taskPeriod}
              onChange={(p) => handlePeriodChange(p, setTaskPeriod)}
            />
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
          </div>
        </div>

        {/* Token Usage Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <TrendingUp size={16} />
            <h3>Token Usage</h3>
            <Badge variant="default">{totalTokens.toLocaleString()} total</Badge>
          </div>
          <div className={styles.panelContent}>
            <TimePeriodSelector
              selected={tokenPeriod}
              onChange={(p) => handlePeriodChange(p, setTokenPeriod)}
            />
            <div className={styles.tokenRatioDisplay}>
              <div className={styles.tokenRatioBar}>
                <div
                  className={styles.tokenInputBar}
                  style={{ width: `${inputRatio}%` }}
                />
                <div
                  className={styles.tokenOutputBar}
                  style={{ width: `${outputRatio}%` }}
                />
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
          </div>
        </div>

        {/* System Resources Panel (CPU, Memory, Disk, Thread Pool, Network) */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Cpu size={16} />
            <h3>System Resources</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.resourceGrid}>
              <div className={styles.resourceItem}>
                <div className={styles.resourceHeader}>
                  <span>CPU</span>
                  <span className={cpuPercent > 80 ? styles.warning : ''}>{cpuPercent.toFixed(0)}%</span>
                </div>
                <div className={styles.resourceBar}>
                  <div
                    className={`${styles.resourceFill} ${cpuPercent > 80 ? styles.fillWarning : ''}`}
                    style={{ width: `${Math.min(cpuPercent, 100)}%` }}
                  />
                </div>
              </div>
              <div className={styles.resourceItem}>
                <div className={styles.resourceHeader}>
                  <span>Memory</span>
                  <span className={memoryPercent > 80 ? styles.warning : ''}>
                    {formatBytes(memoryUsed)} / {formatBytes(memoryTotal)}
                  </span>
                </div>
                <div className={styles.resourceBar}>
                  <div
                    className={`${styles.resourceFill} ${memoryPercent > 80 ? styles.fillWarning : ''}`}
                    style={{ width: `${Math.min(memoryPercent, 100)}%` }}
                  />
                </div>
              </div>
              <div className={styles.resourceItem}>
                <div className={styles.resourceHeader}>
                  <span>Disk</span>
                  <span className={diskPercent > 80 ? styles.warning : ''}>
                    {diskUsed.toFixed(1)} GB / {diskTotal.toFixed(1)} GB
                  </span>
                </div>
                <div className={styles.resourceBar}>
                  <div
                    className={`${styles.resourceFill} ${diskPercent > 80 ? styles.fillWarning : ''}`}
                    style={{ width: `${Math.min(diskPercent, 100)}%` }}
                  />
                </div>
              </div>
              <div className={styles.resourceItem}>
                <div className={styles.resourceHeader}>
                  <span>Thread Pool</span>
                  <span className={threadPoolUtil > 80 ? styles.warning : ''}>
                    {threadPoolActive} / {threadPoolMax} ({threadPoolUtil.toFixed(0)}%)
                  </span>
                </div>
                <div className={styles.resourceBar}>
                  <div
                    className={`${styles.resourceFill} ${threadPoolUtil > 80 ? styles.fillWarning : ''}`}
                    style={{ width: `${Math.min(threadPoolUtil, 100)}%` }}
                  />
                </div>
              </div>
            </div>
            {/* Network I/O */}
            <div className={styles.networkRow}>
              <div className={styles.networkStat}>
                <ArrowUpRight size={14} className={styles.uploadIcon} />
                <span className={styles.networkLabel}>Upload:</span>
                <span className={styles.networkValue}>{networkSentRate.toFixed(1)} KB/s</span>
              </div>
              <div className={styles.networkStat}>
                <ArrowDownRight size={14} className={styles.downloadIcon} />
                <span className={styles.networkLabel}>Download:</span>
                <span className={styles.networkValue}>{networkRecvRate.toFixed(1)} KB/s</span>
              </div>
            </div>
          </div>
        </div>

        {/* Usage Patterns Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <BarChart3 size={16} />
            <h3>Usage Patterns</h3>
            <Badge variant="default">{usageRequestCount} requests</Badge>
          </div>
          <div className={styles.panelContent}>
            <TimePeriodSelector
              selected={usagePeriod}
              onChange={(p) => handlePeriodChange(p, setUsagePeriod)}
            />
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
                {getChartLabels(usagePeriod).title}
                <span className={styles.chartSubLabel}> · {getChartLabels(usagePeriod).description}</span>
              </div>
              <div className={styles.chartBars}>
                {hourlyDistribution.map((count, hour) => (
                  <div
                    key={hour}
                    className={styles.chartBarWrapper}
                    title={`${formatHour(hour)}: ${count} requests`}
                  >
                    <div
                      className={`${styles.chartBar} ${usagePeriod === '1d' && hour === new Date().getHours() ? styles.currentHour : ''}`}
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
          </div>
        </div>

        {/* MCP Servers Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Hammer size={16} />
            <h3>MCP Servers</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.compactStats}>
              <div className={styles.compactStatItem}>
                <CheckCircle size={14} className={styles.successIcon} />
                <span className={styles.compactStatValue}>{mcpConnectedServers}</span>
                <span className={styles.compactStatLabel}>Connected</span>
              </div>
              <div className={styles.compactStatItem}>
                <Activity size={14} className={styles.primaryIcon} />
                <span className={styles.compactStatValue}>{mcpTotalCalls}</span>
                <span className={styles.compactStatLabel}>Calls</span>
              </div>
            </div>
            <div className={styles.usageSection}>
              <div className={styles.usageSectionHeader}>Top Tools</div>
              {mcpTopTools.length > 0 ? (
                <div className={styles.usageList}>
                  {(showAllTools ? mcpTopTools : mcpTopTools.slice(0, 3)).map((tool, index) => (
                    <div key={tool.name} className={styles.usageItem}>
                      <span className={styles.usageRank}>#{index + 1}</span>
                      <span className={styles.usageName}>{tool.name}</span>
                      <span className={styles.usageCount}>{tool.count}</span>
                    </div>
                  ))}
                  {mcpTopTools.length > 3 && (
                    <button
                      className={styles.viewAllButton}
                      onClick={() => setShowAllTools(!showAllTools)}
                    >
                      {showAllTools ? 'Show less' : `View all (${mcpTopTools.length})`}
                    </button>
                  )}
                </div>
              ) : (
                <div className={styles.emptyUsage}>No usage yet</div>
              )}
            </div>
          </div>
        </div>

        {/* Skills Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Package size={16} />
            <h3>Skills</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.compactStats}>
              <div className={styles.compactStatItem}>
                <CheckCircle size={14} className={styles.successIcon} />
                <span className={styles.compactStatValue}>{skillEnabled}</span>
                <span className={styles.compactStatLabel}>Enabled</span>
              </div>
              <div className={styles.compactStatItem}>
                <Activity size={14} className={styles.primaryIcon} />
                <span className={styles.compactStatValue}>{skillTotalInvocations}</span>
                <span className={styles.compactStatLabel}>Invocations</span>
              </div>
            </div>
            <div className={styles.usageSection}>
              <div className={styles.usageSectionHeader}>Top Skills</div>
              {topSkills.length > 0 ? (
                <div className={styles.usageList}>
                  {(showAllSkills ? topSkills : topSkills.slice(0, 3)).map((skill, index) => (
                    <div key={skill.name} className={styles.usageItem}>
                      <span className={styles.usageRank}>#{index + 1}</span>
                      <span className={styles.usageName}>{skill.name}</span>
                      <span className={styles.usageCount}>{skill.count}</span>
                    </div>
                  ))}
                  {topSkills.length > 3 && (
                    <button
                      className={styles.viewAllButton}
                      onClick={() => setShowAllSkills(!showAllSkills)}
                    >
                      {showAllSkills ? 'Show less' : `View all (${topSkills.length})`}
                    </button>
                  )}
                </div>
              ) : (
                <div className={styles.emptyUsage}>No usage yet</div>
              )}
            </div>
          </div>
        </div>

        {/* Integrations Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Globe size={16} />
            <h3>Integrations</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.compactStats}>
              <div className={styles.compactStatItem}>
                <CheckCircle size={14} className={styles.successIcon} />
                <span className={styles.compactStatValue}>{integrationConnected}</span>
                <span className={styles.compactStatLabel}>Connected</span>
              </div>
              <div className={styles.compactStatItem}>
                <Activity size={14} className={styles.primaryIcon} />
                <span className={styles.compactStatValue}>{integrationTotalCalls}</span>
                <span className={styles.compactStatLabel}>Total Calls</span>
              </div>
            </div>
            <div className={styles.usageSection}>
              <div className={styles.usageSectionHeader}>Top Integrations</div>
              {topIntegrations.length > 0 ? (
                <div className={styles.usageList}>
                  {(showAllIntegrations ? topIntegrations : topIntegrations.slice(0, 3)).map((intg, index) => (
                    <div key={intg.name} className={styles.usageItem}>
                      <span className={styles.usageRank}>#{index + 1}</span>
                      <span className={styles.usageName}>{intg.name}</span>
                      <span className={styles.usageCount}>{intg.count}</span>
                    </div>
                  ))}
                  {topIntegrations.length > 3 && (
                    <button
                      className={styles.viewAllButton}
                      onClick={() => setShowAllIntegrations(!showAllIntegrations)}
                    >
                      {showAllIntegrations ? 'Show less' : `View all (${topIntegrations.length})`}
                    </button>
                  )}
                </div>
              ) : (
                <div className={styles.emptyUsage}>No usage yet</div>
              )}
            </div>
          </div>
        </div>

        {/* Model Information Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Bot size={16} />
            <h3>Model Information</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.modelInfo}>
              <div className={styles.modelItem}>
                <Building2 size={14} className={styles.mutedIcon} />
                <span className={styles.modelLabel}>Provider</span>
                <span className={styles.modelValue}>{modelProvider || 'Not configured'}</span>
              </div>
              <div className={styles.modelItem}>
                <Bot size={14} className={styles.primaryIcon} />
                <span className={styles.modelLabel}>Model</span>
                <span className={styles.modelValue}>{modelName || 'Not configured'}</span>
              </div>
              <div className={styles.modelItem}>
                <Hash size={14} className={styles.mutedIcon} />
                <span className={styles.modelLabel}>Model ID</span>
                <span className={styles.modelValueSmall}>{modelId || 'N/A'}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
