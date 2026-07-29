import { useEffect } from 'react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { DashboardGrid } from './layout/DashboardGrid'
import { DashboardToolbar } from './layout/DashboardToolbar'
import { useDashboardLayouts } from './layout/useDashboardLayouts'
import styles from './DashboardPage.module.css'

export function DashboardPage() {
  const { connected, requestFilteredMetrics, subscribeDashboardMetrics, unsubscribeDashboardMetrics } = useWebSocket()

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

  // Request 'total' metrics on initial load.
  useEffect(() => {
    if (connected) {
      requestFilteredMetrics('total')
    }
  }, [connected, requestFilteredMetrics])

  return (
    <div className={styles.dashboard}>
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
