import { useEffect } from 'react'
import { Timer } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { StatusIndicator } from '../../components/ui'
import { useDerivedAgentStatus } from '../../hooks'
import { DashboardGrid } from './layout/DashboardGrid'
import { DashboardToolbar } from './layout/DashboardToolbar'
import { useDashboardLayouts } from './layout/useDashboardLayouts'
import styles from './DashboardPage.module.css'

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

export function DashboardPage() {
  const {
    connected, actions, messages, dashboardMetrics,
    requestFilteredMetrics, subscribeDashboardMetrics, unsubscribeDashboardMetrics,
  } = useWebSocket()

  const status = useDerivedAgentStatus({ actions, messages, connected })
  const uptime = dashboardMetrics?.uptimeSeconds ? formatUptime(dashboardMetrics.uptimeSeconds) : '0m'

  const {
    layouts, activeLayout, activeLayoutId, setActiveLayoutId,
    updateActiveGridLayouts, addWidget, removeWidget,
    createLayout, renameLayout, deleteLayout,
  } = useDashboardLayouts()

  // Subscribe to live metrics while on this page, unsubscribe on leave.
  useEffect(() => {
    subscribeDashboardMetrics()
    return () => {
      unsubscribeDashboardMetrics()
    }
  }, [subscribeDashboardMetrics, unsubscribeDashboardMetrics])

  // Request 'total' metrics (backs the header uptime/overview) on initial load.
  useEffect(() => {
    if (connected) {
      requestFilteredMetrics('total')
    }
  }, [connected, requestFilteredMetrics])

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

      <DashboardToolbar
        layouts={layouts}
        activeLayout={activeLayout}
        activeLayoutId={activeLayoutId}
        onSelectLayout={setActiveLayoutId}
        onCreateLayout={createLayout}
        onRenameLayout={renameLayout}
        onDeleteLayout={deleteLayout}
        onAddWidget={addWidget}
      />

      <DashboardGrid
        activeLayout={activeLayout}
        onLayoutsChange={updateActiveGridLayouts}
        onRemoveWidget={removeWidget}
      />
    </div>
  )
}
