import { useEffect, useState } from 'react'
import { AlertTriangle, Timer } from 'lucide-react'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { StatusIndicator } from '../../../components/ui'
import { useDerivedAgentStatus } from '../../../hooks'
import styles from './widgets.module.css'

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  return `${minutes}m ${seconds}s`
}

function displayActionName(name: string): string {
  const words = name.toLowerCase().replace(/[\s-]+/g, '_').replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function AgentStatusWidget() {
  const { connected, actions, messages } = useWebSocket()
  const status = useDerivedAgentStatus({ actions, messages, connected })

  const runningActions = actions.filter(a => a.itemType === 'action' && a.status === 'running')
  const earliestRunningStart = runningActions.reduce<number | undefined>((min, a) => {
    if (a.createdAt == null) return min
    return min == null ? a.createdAt : Math.min(min, a.createdAt)
  }, undefined)

  // Tick once a second while something is running so the task-elapsed
  // timer stays live (coarser than Chat's 100ms ticker — not needed here).
  const [, forceTick] = useState(0)
  useEffect(() => {
    if (earliestRunningStart == null) return
    const id = setInterval(() => forceTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [earliestRunningStart])

  const taskElapsed = earliestRunningStart != null ? formatDuration(Date.now() - earliestRunningStart) : null

  const lastError = [...actions]
    .filter(a => a.status === 'error')
    .sort((a, b) => (b.completedAt ?? b.createdAt ?? 0) - (a.completedAt ?? a.createdAt ?? 0))[0]

  return (
    <>
      <div className={styles.agentStatusHeader}>
        <StatusIndicator status={status.state} size="lg" variant="dot" />
        <span className={styles.agentStatusMessage}>{status.message}</span>
      </div>

      {/* Uptime lives in the dashboard header now — this widget carries only
          what the header has no room for. The row is conditional because
          there'd otherwise be an empty tile strip whenever nothing is running. */}
      {taskElapsed && (
        <div className={styles.compactStats}>
          <div className={styles.compactStatItem}>
            <Timer size={14} className={styles.successIcon} />
            <span className={styles.compactStatValue}>{taskElapsed}</span>
            <span className={styles.compactStatLabel}>Task time</span>
          </div>
        </div>
      )}

      <div className={styles.usageSection}>
        <div className={styles.usageSectionHeader}>Running</div>
        {runningActions.length > 0 ? (
          <div className={styles.usageList}>
            {runningActions.map(a => (
              <div key={a.id} className={styles.usageItem}>
                <span className={styles.usageName}>{displayActionName(a.name)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.emptyUsage}>Idle — nothing running</div>
        )}
      </div>

      {lastError && (
        <div className={styles.usageSection}>
          <div className={styles.usageSectionHeader}>Last Error</div>
          <div className={styles.errorBox}>
            <AlertTriangle size={12} className={styles.errorIcon} />
            <span>{displayActionName(lastError.name)}: {(lastError.error ?? '').split('\n')[0]}</span>
          </div>
        </div>
      )}
    </>
  )
}
