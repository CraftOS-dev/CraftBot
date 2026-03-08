import React from 'react'
import {
  Activity,
  Zap,
  CheckCircle,
  XCircle,
  Clock,
  Cpu,
  HardDrive,
  Wifi,
  Package,
  Plug,
  TrendingUp,
  Hash
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { Badge, StatusIndicator } from '../../components/ui'
import styles from './DashboardPage.module.css'

interface StatCardProps {
  icon: React.ReactNode
  label: string
  value: string | number
  subtext?: string
  variant?: 'default' | 'primary' | 'success' | 'warning' | 'error'
}

function StatCard({ icon, label, value, subtext, variant = 'default' }: StatCardProps) {
  return (
    <div className={`${styles.statCard} ${styles[variant]}`}>
      <div className={styles.statIcon}>{icon}</div>
      <div className={styles.statContent}>
        <span className={styles.statLabel}>{label}</span>
        <span className={styles.statValue}>{value}</span>
        {subtext && <span className={styles.statSubtext}>{subtext}</span>}
      </div>
    </div>
  )
}

export function DashboardPage() {
  const { status, actions, messages } = useWebSocket()

  // Calculate statistics
  const tasks = actions.filter(a => a.itemType === 'task')
  const completedTasks = tasks.filter(t => t.status === 'completed').length
  const failedTasks = tasks.filter(t => t.status === 'error').length
  const runningTasks = tasks.filter(t => t.status === 'running').length
  const totalActions = actions.filter(a => a.itemType === 'action').length

  // Placeholder data (would come from backend in real implementation)
  const tokenUsage = {
    input: 12450,
    output: 8320,
    total: 20770,
    cost: 0.42,
  }

  const mcpServers = [
    { name: 'filesystem', status: 'connected' as const, tools: 5 },
    { name: 'browser', status: 'connected' as const, tools: 8 },
    { name: 'shell', status: 'connected' as const, tools: 3 },
  ]

  const skills = [
    { name: 'Code Analysis', enabled: true },
    { name: 'File Management', enabled: true },
    { name: 'Web Search', enabled: false },
    { name: 'Image Processing', enabled: true },
  ]

  const uptime = '2h 34m'

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
          <Badge variant={status.state === 'idle' ? 'success' : 'primary'}>
            {status.state.toUpperCase()}
          </Badge>
        </div>
      </div>

      {/* Stats Grid */}
      <div className={styles.statsGrid}>
        <StatCard
          icon={<CheckCircle size={20} />}
          label="Tasks Completed"
          value={completedTasks}
          variant="success"
        />
        <StatCard
          icon={<XCircle size={20} />}
          label="Tasks Failed"
          value={failedTasks}
          variant="error"
        />
        <StatCard
          icon={<Activity size={20} />}
          label="Running"
          value={runningTasks}
          variant="primary"
        />
        <StatCard
          icon={<Zap size={20} />}
          label="Total Actions"
          value={totalActions}
        />
        <StatCard
          icon={<Hash size={20} />}
          label="Messages"
          value={messages.length}
        />
        <StatCard
          icon={<Clock size={20} />}
          label="Uptime"
          value={uptime}
        />
      </div>

      {/* Panels Section */}
      <div className={styles.panelsGrid}>
        {/* Token Usage Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <TrendingUp size={16} />
            <h3>Token Usage</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.tokenStats}>
              <div className={styles.tokenStat}>
                <span className={styles.tokenLabel}>Input</span>
                <span className={styles.tokenValue}>{tokenUsage.input.toLocaleString()}</span>
              </div>
              <div className={styles.tokenStat}>
                <span className={styles.tokenLabel}>Output</span>
                <span className={styles.tokenValue}>{tokenUsage.output.toLocaleString()}</span>
              </div>
              <div className={styles.tokenStat}>
                <span className={styles.tokenLabel}>Total</span>
                <span className={`${styles.tokenValue} ${styles.highlight}`}>
                  {tokenUsage.total.toLocaleString()}
                </span>
              </div>
              <div className={styles.tokenStat}>
                <span className={styles.tokenLabel}>Est. Cost</span>
                <span className={styles.tokenValue}>${tokenUsage.cost.toFixed(2)}</span>
              </div>
            </div>
            <div className={styles.progressBar}>
              <div
                className={styles.progressFill}
                style={{ width: `${(tokenUsage.input / tokenUsage.total) * 100}%` }}
              />
            </div>
            <div className={styles.progressLabels}>
              <span>Input ({Math.round((tokenUsage.input / tokenUsage.total) * 100)}%)</span>
              <span>Output ({Math.round((tokenUsage.output / tokenUsage.total) * 100)}%)</span>
            </div>
          </div>
        </div>

        {/* MCP Servers Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Plug size={16} />
            <h3>MCP Servers</h3>
            <Badge variant="success">{mcpServers.length} connected</Badge>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.serverList}>
              {mcpServers.map(server => (
                <div key={server.name} className={styles.serverItem}>
                  <StatusIndicator
                    status={server.status === 'connected' ? 'completed' : 'error'}
                    size="sm"
                  />
                  <span className={styles.serverName}>{server.name}</span>
                  <Badge variant="default">{server.tools} tools</Badge>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Skills Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Package size={16} />
            <h3>Skills</h3>
            <Badge variant="default">
              {skills.filter(s => s.enabled).length}/{skills.length}
            </Badge>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.skillsList}>
              {skills.map(skill => (
                <div key={skill.name} className={styles.skillItem}>
                  <span className={styles.skillName}>{skill.name}</span>
                  <Badge variant={skill.enabled ? 'success' : 'default'}>
                    {skill.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* System Panel */}
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <Cpu size={16} />
            <h3>System</h3>
          </div>
          <div className={styles.panelContent}>
            <div className={styles.systemStats}>
              <div className={styles.systemStat}>
                <Cpu size={14} />
                <span>Model</span>
                <span className={styles.systemValue}>Claude 3.5 Sonnet</span>
              </div>
              <div className={styles.systemStat}>
                <HardDrive size={14} />
                <span>Workspace</span>
                <span className={styles.systemValue}>workspace/</span>
              </div>
              <div className={styles.systemStat}>
                <Wifi size={14} />
                <span>Connection</span>
                <span className={styles.systemValue}>WebSocket</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
